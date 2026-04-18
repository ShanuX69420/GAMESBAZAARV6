from decimal import Decimal
import mimetypes
from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from django.core import signing
from django.http import FileResponse, Http404
from django.db.models import Count, F, OuterRef, Prefetch, Q, Subquery
from django.db import transaction as db_transaction
from .models import (
    Game, GameCategory, UserProfile, Listing, Conversation, Message,
    Wallet, WalletTransaction, TopUpRequest, Order, SellerCommissionOverride,
)
from .serializers import (
    GameListSerializer, GameDetailSerializer, GameCategoryDetailSerializer,
    RegisterSerializer, UserSerializer, SellerApplicationSerializer,
    build_listing_filter_display_map,
    ListingSerializer, CreateListingSerializer,
    ConversationListSerializer, ConversationDetailSerializer, MessageSerializer,
    WalletSerializer, WalletTransactionSerializer,
    TopUpRequestSerializer, CreateTopUpRequestSerializer,
    OrderSerializer, BuyListingSerializer,
)
from .services import (
    CHAT_WS_TICKET_MAX_AGE_SECONDS,
    create_chat_ws_ticket,
    decode_private_media_ticket,
    get_or_create_locked_wallet,
    validate_uploaded_image,
)


DEFAULT_LISTING_PAGE_SIZE = 48
MAX_LISTING_PAGE_SIZE = 100


class ScopedPostThrottleMixin:
    """Apply a scoped throttle only to mutating POST endpoints."""
    throttle_classes = [ScopedRateThrottle]
    throttle_methods = {'POST'}

    def get_throttles(self):
        if self.request.method not in self.throttle_methods:
            return []
        return super().get_throttles()


def has_valid_private_media_ticket(request, *, kind, object_id):
    ticket = request.query_params.get('ticket')
    if not ticket:
        return False
    try:
        payload = decode_private_media_ticket(ticket)
    except (signing.BadSignature, signing.SignatureExpired, KeyError, TypeError, ValueError):
        return False
    return payload['kind'] == kind and payload['object_id'] == int(object_id)


def private_file_response(file_field):
    if not file_field:
        raise Http404
    try:
        opened_file = file_field.open('rb')
    except (FileNotFoundError, OSError):
        raise Http404
    content_type = mimetypes.guess_type(file_field.name)[0] or 'application/octet-stream'
    return FileResponse(opened_file, content_type=content_type)


def get_pagination_params(request, default_limit=DEFAULT_LISTING_PAGE_SIZE, max_limit=MAX_LISTING_PAGE_SIZE):
    try:
        limit = int(request.query_params.get('limit', default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    try:
        offset = int(request.query_params.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0

    limit = max(1, min(limit, max_limit))
    offset = max(0, offset)
    return limit, offset


def get_pagination_payload(total_count, limit, offset):
    next_offset = offset + limit if offset + limit < total_count else None
    previous_offset = max(offset - limit, 0) if offset > 0 else None
    return {
        'count': total_count,
        'limit': limit,
        'offset': offset,
        'next_offset': next_offset,
        'previous_offset': previous_offset,
    }


# ── Public Game / Category / Filter views ────────────────────────────────────

class GameListView(generics.ListAPIView):
    """GET /api/games/ — List all active games."""
    serializer_class = GameListSerializer
    queryset = Game.objects.filter(is_active=True).prefetch_related('game_categories')


class GameDetailView(generics.RetrieveAPIView):
    """GET /api/games/{slug}/ — Game detail with its categories."""
    serializer_class = GameDetailSerializer
    lookup_field = 'slug'
    queryset = Game.objects.filter(is_active=True).prefetch_related(
        'game_categories__category'
    )


class GameCategoryDetailView(APIView):
    """GET /api/games/{game_slug}/{category_slug}/ — Category with filters + listings."""

    def get(self, request, game_slug, category_slug):
        game_category = get_object_or_404(
            GameCategory.objects.select_related('game', 'category').prefetch_related(
                'assigned_filters__filter__options'
            ),
            game__slug=game_slug,
            category__slug=category_slug,
            game__is_active=True,
        )

        # Build category detail (filters)
        from .serializers import GameCategoryDetailSerializer
        cat_data = GameCategoryDetailSerializer(game_category).data

        # Query listings with optional filters
        listings_qs = Listing.objects.filter(
            game_category=game_category,
            status='active',
        ).select_related('seller', 'game_category__game', 'game_category__category')

        # Apply filter params from query string: ?filter_{filter_id}={option_value}
        for key, value in request.query_params.items():
            if key.startswith('filter_') and value:
                filter_id = key.replace('filter_', '')
                # Use __contains for proper dict key matching (numeric-looking keys
                # are misinterpreted as array indices by Django's __ path lookup)
                listings_qs = listings_qs.filter(
                    filter_values__contains={filter_id: value}
                )

        total_count = listings_qs.count()
        limit, offset = get_pagination_params(request)
        listings = list(listings_qs[offset:offset + limit])
        listing_context = {
            'request': request,
            'filter_option_display_map': build_listing_filter_display_map(listings),
        }
        listings_data = ListingSerializer(
            listings,
            many=True,
            context=listing_context,
        ).data
        cat_data['listings'] = listings_data
        cat_data['listing_pagination'] = get_pagination_payload(total_count, limit, offset)
        return Response(cat_data)


# ── Auth views ───────────────────────────────────────────────────────────────

class LoginView(ScopedPostThrottleMixin, TokenObtainPairView):
    throttle_scope = 'auth_login'


class RefreshTokenView(ScopedPostThrottleMixin, TokenRefreshView):
    throttle_scope = 'auth_refresh'


class RegisterView(ScopedPostThrottleMixin, generics.CreateAPIView):
    """POST /api/auth/register/ — Register a new user."""
    serializer_class = RegisterSerializer
    throttle_scope = 'auth_register'

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response({
            'message': 'Account created successfully.',
            'user': UserSerializer(user).data,
        }, status=status.HTTP_201_CREATED)


class MeView(APIView):
    """GET /api/auth/me/ — Get current user info."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


# ── Seller views ─────────────────────────────────────────────────────────────

class SellerApplyView(APIView):
    """POST /api/seller/apply/ — Submit a seller application."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        profile = request.user.profile
        if profile.seller_status == 'approved':
            return Response({'error': 'You are already an approved seller.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if profile.seller_status == 'pending':
            return Response({'error': 'Your application is already pending.'},
                            status=status.HTTP_400_BAD_REQUEST)

        serializer = SellerApplicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        profile.seller_status = 'pending'
        profile.seller_application_note = serializer.validated_data['note']
        profile.save()

        return Response({'message': 'Seller application submitted.'})


class SellerStatusView(APIView):
    """GET /api/seller/status/ — Check seller application status."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile = request.user.profile
        return Response({
            'seller_status': profile.seller_status,
            'is_seller': profile.is_seller,
            'application_note': profile.seller_application_note,
        })


# ── Listing views ────────────────────────────────────────────────────────────

class ListingCreateView(generics.CreateAPIView):
    """POST /api/listings/ — Create a listing (sellers only)."""
    serializer_class = CreateListingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        if not self.request.user.profile.is_seller:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You must be an approved seller to create listings.')
        serializer.save()


class MyListingsView(generics.ListAPIView):
    """GET /api/listings/mine/ — Get current user's listings."""
    serializer_class = ListingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Listing.objects.filter(
            seller=self.request.user
        ).select_related('game_category__game', 'game_category__category')

    def list(self, request, *args, **kwargs):
        listings = list(self.get_queryset())
        serializer = self.get_serializer(
            listings,
            many=True,
            context={
                **self.get_serializer_context(),
                'filter_option_display_map': build_listing_filter_display_map(listings),
            },
        )
        return Response(serializer.data)


class ListingDetailView(APIView):
    """GET /api/listings/{id}/ — Get listing detail.
    PUT /api/listings/{id}/ — Edit listing (owner only).
    DELETE /api/listings/{id}/ — Delete listing (owner only).
    """
    permission_classes = []

    def get_permissions(self):
        if self.request.method == 'GET':
            return []
        return [permissions.IsAuthenticated()]

    def get(self, request, pk):
        listing = get_object_or_404(
            Listing.objects.select_related(
                'seller', 'game_category__game', 'game_category__category'
            ), pk=pk
        )
        return Response(ListingSerializer(
            listing,
            context={
                'request': request,
                'filter_option_display_map': build_listing_filter_display_map([listing]),
            },
        ).data)

    def put(self, request, pk):
        from .serializers import UpdateListingSerializer
        listing = get_object_or_404(Listing, pk=pk, seller=request.user)
        serializer = UpdateListingSerializer(listing, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        listing.refresh_from_db()
        return Response(ListingSerializer(
            listing,
            context={
                'request': request,
                'filter_option_display_map': build_listing_filter_display_map([listing]),
            },
        ).data)

    def delete(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk, seller=request.user)
        listing.delete()
        return Response({'message': 'Listing deleted.'}, status=204)

class ConversationListView(APIView):
    """GET /api/chat/ — List all conversations for current user."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        latest_message = Message.objects.filter(
            conversation=OuterRef('pk')
        ).order_by('-created_at', '-pk')
        conversations = Conversation.objects.filter(
            participants=request.user
        ).annotate(
            unread_messages_count=Count(
                'messages',
                filter=Q(messages__is_read=False) & ~Q(messages__sender=request.user),
            ),
            latest_message_content=Subquery(latest_message.values('content')[:1]),
            latest_message_sender_name=Subquery(latest_message.values('sender__username')[:1]),
            latest_message_created_at=Subquery(latest_message.values('created_at')[:1]),
        ).prefetch_related(
            Prefetch('participants', queryset=User.objects.select_related('profile')),
        ).order_by(F('latest_message_created_at').desc(nulls_last=True), '-updated_at', '-pk')
        data = ConversationListSerializer(conversations, many=True,
                                           context={'request': request}).data
        return Response(data)


class StartConversationView(ScopedPostThrottleMixin, APIView):
    """POST /api/chat/start/ — Find or create a conversation with a user.
    Body: {"user_id": 5, "message": "Hi, is this still available?"}
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'chat_start'

    def post(self, request):
        other_user_id = request.data.get('user_id')
        initial_message = request.data.get('message', '').strip()

        if not other_user_id:
            return Response({'error': 'user_id is required.'}, status=400)

        if int(other_user_id) == request.user.id:
            return Response({'error': 'Cannot chat with yourself.'}, status=400)

        other_user = get_object_or_404(User, id=other_user_id)

        # Find existing conversation between these two users
        conversation = Conversation.objects.filter(
            participants=request.user
        ).filter(
            participants=other_user
        ).first()

        if not conversation:
            conversation = Conversation.objects.create()
            conversation.participants.add(request.user, other_user)

        # Send initial message if provided
        if initial_message:
            Message.objects.create(
                conversation=conversation,
                sender=request.user,
                content=initial_message,
            )
            conversation.save()  # Update updated_at

        data = ConversationDetailSerializer(conversation, context={'request': request}).data
        return Response(data, status=201)


class ConversationDetailView(APIView):
    """GET /api/chat/{id}/ — Get conversation with messages."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        conversation = get_object_or_404(
            Conversation.objects.prefetch_related('participants', 'messages__sender'),
            pk=pk,
            participants=request.user,
        )

        # Mark unread messages from the other user as read
        conversation.messages.filter(is_read=False).exclude(
            sender=request.user
        ).update(is_read=True)

        data = ConversationDetailSerializer(conversation, context={'request': request}).data
        return Response(data)


class ChatWebSocketTicketView(APIView):
    """POST /api/chat/{id}/ws-ticket/ — Issue a short-lived chat WebSocket ticket."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        conversation = get_object_or_404(Conversation, pk=pk, participants=request.user)
        return Response({
            'ticket': create_chat_ws_ticket(request.user, conversation.pk),
            'expires_in': CHAT_WS_TICKET_MAX_AGE_SECONDS,
        })


class SendMessageView(APIView):
    """POST /api/chat/{id}/send/ — Send a message in a conversation."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        conversation = get_object_or_404(
            Conversation, pk=pk, participants=request.user
        )

        content = request.data.get('content', '').strip()
        if not content:
            return Response({'error': 'Message cannot be empty.'}, status=400)

        message = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            content=content,
        )
        conversation.save()  # Update updated_at

        data = MessageSerializer(message, context={'request': request}).data
        return Response(data, status=201)


class SendImageView(ScopedPostThrottleMixin, APIView):
    """POST /api/chat/{id}/send-image/ — Send an image message."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'chat_upload'

    def post(self, request, pk):
        conversation = get_object_or_404(
            Conversation, pk=pk, participants=request.user
        )

        image = request.FILES.get('image')
        if not image:
            return Response({'error': 'No image provided.'}, status=400)

        validation_error = validate_uploaded_image(image)
        if validation_error:
            return Response({'error': validation_error}, status=400)

        content = request.data.get('content', '').strip()
        message = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            content=content,
            image=image,
        )
        conversation.save()

        data = MessageSerializer(message, context={'request': request}).data
        return Response(data, status=201)


class ChatMessageImageView(APIView):
    """GET /api/chat/messages/{id}/image/ — Serve a protected chat image."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        message = get_object_or_404(
            Message.objects.select_related('conversation'),
            pk=pk,
        )
        has_ticket = has_valid_private_media_ticket(
            request,
            kind='chat_message_image',
            object_id=message.pk,
        )
        is_participant = (
            request.user.is_authenticated and
            Conversation.objects.filter(
                pk=message.conversation_id,
                participants=request.user,
            ).exists()
        )
        if not (has_ticket or is_participant):
            raise Http404
        return private_file_response(message.image)


class UnreadCountView(APIView):
    """GET /api/chat/unread/ — Count of conversations with unread messages."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        count = Message.objects.filter(
            conversation__participants=request.user,
            is_read=False,
        ).exclude(sender=request.user).values(
            'conversation'
        ).distinct().count()
        return Response({'unread_count': count})


class HeartbeatView(ScopedPostThrottleMixin, APIView):
    """POST /api/heartbeat/ — Update user's last_active timestamp."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'heartbeat'

    def post(self, request):
        from django.utils import timezone
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.last_active = timezone.now()
        profile.save(update_fields=['last_active'])
        return Response({'status': 'ok'})


# ── Wallet views ──────────────────────────────────────────────────────────────

class WalletView(APIView):
    """GET /api/wallet/ — Get wallet balance + recent transactions."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        transactions = wallet.transactions.all()[:20]
        return Response({
            'balance': str(wallet.balance),
            'transactions': WalletTransactionSerializer(transactions, many=True).data,
        })


class WalletTransactionsView(APIView):
    """GET /api/wallet/transactions/ — Full transaction history."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        transactions = wallet.transactions.all()
        return Response(WalletTransactionSerializer(transactions, many=True).data)


class TopUpRequestView(ScopedPostThrottleMixin, APIView):
    """POST /api/wallet/top-up/ — Create a top-up request.
    GET /api/wallet/top-up/ — List my top-up requests.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'topup_request'

    def get(self, request):
        requests_qs = TopUpRequest.objects.filter(user=request.user)
        return Response(TopUpRequestSerializer(requests_qs, many=True,
                                               context={'request': request}).data)

    def post(self, request):
        serializer = CreateTopUpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Handle payment proof image upload
        payment_proof = request.FILES.get('payment_proof')
        if payment_proof:
            validation_error = validate_uploaded_image(payment_proof)
            if validation_error:
                return Response({'error': validation_error}, status=400)

        topup = TopUpRequest.objects.create(
            user=request.user,
            amount=data['amount'],
            payment_method=data.get('payment_method', ''),
            transaction_id=data.get('transaction_id', ''),
            payment_proof=payment_proof,
        )

        return Response(
            TopUpRequestSerializer(topup, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class TopUpProofView(APIView):
    """GET /api/wallet/top-up/{id}/proof/ — Serve a protected payment proof."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        topup = get_object_or_404(TopUpRequest, pk=pk)
        has_ticket = has_valid_private_media_ticket(
            request,
            kind='topup_proof',
            object_id=topup.pk,
        )
        can_view = (
            request.user.is_authenticated and
            (topup.user_id == request.user.id or request.user.is_staff)
        )
        if not (has_ticket or can_view):
            raise Http404
        return private_file_response(topup.payment_proof)


# ── Order views ───────────────────────────────────────────────────────────────

def get_commission_rate(seller, category):
    """Get the commission rate for a seller+category.
    Checks for seller-specific override first, falls back to category default.
    """
    try:
        override = SellerCommissionOverride.objects.get(
            seller=seller, category=category
        )
        return override.commission_rate
    except SellerCommissionOverride.DoesNotExist:
        return category.commission_rate


class BuyListingView(APIView):
    """POST /api/orders/buy/ — Purchase a listing. Deducts from buyer wallet (escrow)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = BuyListingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        qty = data.get('quantity', 1)

        with db_transaction.atomic():
            listing = get_object_or_404(
                Listing.objects.select_for_update().select_related(
                    'seller',
                    'game_category__category',
                ),
                id=data['listing_id'],
            )

            # Run validations after locking the listing so stock/status cannot
            # change between the check and the stock decrement.
            if listing.status != 'active':
                return Response({'error': 'This listing is no longer available.'}, status=400)

            if listing.seller == request.user:
                return Response({'error': 'You cannot buy your own listing.'}, status=400)

            if listing.quantity is not None and qty > listing.quantity:
                return Response({'error': f'Only {listing.quantity} available.'}, status=400)

            total = listing.price * qty
            if total <= 0:
                return Response({'error': 'Invalid listing price.'}, status=400)

            wallet = get_or_create_locked_wallet(request.user)

            if wallet.balance < total:
                return Response({'error': 'Insufficient wallet balance.'}, status=400)

            category = listing.game_category.category
            rate = get_commission_rate(listing.seller, category)
            commission = (total * rate / Decimal('100')).quantize(Decimal('0.01'))
            seller_receives = total - commission

            # Deduct from buyer
            wallet.balance -= total
            wallet.save(update_fields=['balance', 'updated_at'])

            # Create order
            order = Order.objects.create(
                buyer=request.user,
                seller=listing.seller,
                listing=listing,
                listing_title=listing.title,
                quantity=qty,
                unit_price=listing.price,
                total_amount=total,
                commission_rate=rate,
                commission_amount=commission,
                seller_amount=seller_receives,
                status='pending',
            )

            # Log transaction
            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type='purchase',
                amount=total,
                balance_after=wallet.balance,
                description=f'Purchase: {listing.title} (x{qty})',
                reference_id=f'order_{order.pk}',
            )

            # Reduce listing stock only if not evergreen (quantity is not null)
            if listing.quantity is not None:
                listing.quantity -= qty
                if listing.quantity <= 0:
                    listing.quantity = 0
                    listing.status = 'sold'
                listing.save(update_fields=['quantity', 'status'])

            # Auto-create or find conversation for the order
            conversation = Conversation.objects.filter(
                participants=request.user
            ).filter(
                participants=listing.seller
            ).first()

            if not conversation:
                conversation = Conversation.objects.create()
                conversation.participants.add(request.user, listing.seller)

            order.conversation = conversation
            order.save(update_fields=['conversation'])

        return Response(OrderSerializer(order).data, status=201)


class MyOrdersView(APIView):
    """GET /api/orders/mine/ — Orders where I'm the buyer."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        orders = Order.objects.filter(
            buyer=request.user
        ).select_related('listing', 'seller', 'conversation')
        return Response(OrderSerializer(orders, many=True).data)


class MySalesView(APIView):
    """GET /api/orders/sales/ — Orders where I'm the seller."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        orders = Order.objects.filter(
            seller=request.user
        ).select_related('listing', 'buyer', 'conversation')
        return Response(OrderSerializer(orders, many=True).data)


class OrderDetailView(APIView):
    """GET /api/orders/<id>/ — Get order detail."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        order = get_object_or_404(
            Order.objects.select_related('listing', 'buyer', 'seller', 'conversation'),
            pk=pk,
        )
        # Only buyer or seller can view
        if request.user not in (order.buyer, order.seller):
            return Response({'error': 'Not authorized.'}, status=403)

        # Auto-link conversation if missing
        if not order.conversation:
            conversation = Conversation.objects.filter(
                participants=order.buyer
            ).filter(
                participants=order.seller
            ).first()

            if not conversation:
                conversation = Conversation.objects.create()
                conversation.participants.add(order.buyer, order.seller)

            order.conversation = conversation
            order.save(update_fields=['conversation'])

        return Response(OrderSerializer(order).data)


class DeliverOrderView(APIView):
    """POST /api/orders/<id>/deliver/ — Seller marks order as delivered."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        with db_transaction.atomic():
            order = get_object_or_404(
                Order.objects.select_for_update(),
                pk=pk,
                seller=request.user,
            )

            if order.status != 'pending':
                return Response({'error': 'Order can only be delivered when pending.'}, status=400)

            delivery_note = request.data.get('delivery_note', '').strip()
            order.status = 'delivered'
            order.delivery_note = delivery_note
            order.save(update_fields=['status', 'delivery_note', 'updated_at'])

        return Response(OrderSerializer(order).data)


class ConfirmOrderView(APIView):
    """POST /api/orders/<id>/confirm/ — Buyer confirms delivery. Releases funds to seller."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        with db_transaction.atomic():
            order = get_object_or_404(
                Order.objects.select_for_update().select_related('seller'),
                pk=pk,
                buyer=request.user,
            )

            if order.status == 'completed':
                return Response(OrderSerializer(order).data)

            if order.status not in ('pending', 'delivered'):
                return Response({'error': 'Order cannot be confirmed in current state.'}, status=400)

            # Release funds to seller (minus commission)
            seller_wallet = get_or_create_locked_wallet(order.seller)
            seller_wallet.balance += order.seller_amount
            seller_wallet.save(update_fields=['balance', 'updated_at'])

            # Log sale transaction for seller
            WalletTransaction.objects.create(
                wallet=seller_wallet,
                transaction_type='sale',
                amount=order.seller_amount,
                balance_after=seller_wallet.balance,
                description=f'Sale completed: {order.listing_title} (x{order.quantity})',
                reference_id=f'order_{order.pk}',
            )

            # Log commission transaction for seller
            if order.commission_amount > 0:
                WalletTransaction.objects.create(
                    wallet=seller_wallet,
                    transaction_type='commission',
                    amount=order.commission_amount,
                    balance_after=seller_wallet.balance,
                    description=f'Commission ({order.commission_rate}%): {order.listing_title}',
                    reference_id=f'order_{order.pk}',
                )

            order.status = 'completed'
            order.save(update_fields=['status', 'updated_at'])

        return Response(OrderSerializer(order).data)


class DisputeOrderView(APIView):
    """POST /api/orders/<id>/dispute/ — Buyer opens a dispute."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response({'error': 'Please provide a reason for the dispute.'}, status=400)

        with db_transaction.atomic():
            order = get_object_or_404(
                Order.objects.select_for_update(),
                pk=pk,
                buyer=request.user,
            )

            if order.status not in ('pending', 'delivered'):
                return Response({'error': 'Cannot dispute in current state.'}, status=400)

            order.status = 'disputed'
            order.dispute_reason = reason
            order.save(update_fields=['status', 'dispute_reason', 'updated_at'])

        return Response(OrderSerializer(order).data)


class RefundOrderView(APIView):
    """POST /api/orders/<id>/refund/ — Seller voluntarily refunds the buyer."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        with db_transaction.atomic():
            order = get_object_or_404(
                Order.objects.select_for_update().select_related('buyer', 'seller'),
                pk=pk,
                seller=request.user,
            )

            if order.status == 'cancelled':
                return Response(OrderSerializer(order).data)

            listing = None
            if order.listing_id:
                listing = Listing.objects.select_for_update().filter(pk=order.listing_id).first()
                if listing and listing.quantity is None:
                    listing = None

            # If order was completed, seller already received funds — deduct from seller
            if order.status == 'completed':
                seller_wallet = get_or_create_locked_wallet(order.seller)
                if seller_wallet.balance < order.seller_amount:
                    return Response({
                        'error': f'Insufficient seller wallet balance. You need PKR {order.seller_amount} to refund.'
                    }, status=400)
                seller_wallet.balance -= order.seller_amount
                seller_wallet.save(update_fields=['balance', 'updated_at'])
                WalletTransaction.objects.create(
                    wallet=seller_wallet,
                    transaction_type='refund',
                    amount=order.seller_amount,
                    balance_after=seller_wallet.balance,
                    description=f'Refund issued: {order.listing_title} (x{order.quantity})',
                    reference_id=f'order_{order.pk}',
                )

            # Refund buyer the full amount
            buyer_wallet = get_or_create_locked_wallet(order.buyer)
            buyer_wallet.balance += order.total_amount
            buyer_wallet.save(update_fields=['balance', 'updated_at'])

            WalletTransaction.objects.create(
                wallet=buyer_wallet,
                transaction_type='refund',
                amount=order.total_amount,
                balance_after=buyer_wallet.balance,
                description=f'Refund: {order.listing_title} (x{order.quantity})',
                reference_id=f'order_{order.pk}',
            )

            # Restore stock if listing exists and has finite stock
            if listing:
                listing.quantity += order.quantity
                if listing.status == 'sold':
                    listing.status = 'active'
                listing.save(update_fields=['quantity', 'status'])

            order.status = 'cancelled'
            order.save(update_fields=['status', 'updated_at'])

        return Response(OrderSerializer(order).data)

