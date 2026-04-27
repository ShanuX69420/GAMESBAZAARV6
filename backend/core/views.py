from decimal import Decimal
import hashlib
import mimetypes
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.conf import settings
from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from django.core import signing
from django.http import FileResponse, Http404
from django.db.models import Avg, Count, F, OuterRef, Prefetch, Q, Subquery, Sum
from django.db import transaction as db_transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from .models import (
    Game, GameCategory, UserProfile, Listing, Conversation, Message,
    Wallet, WalletTransaction, TopUpRequest, Order, SellerCommissionOverride,
    Review, Notification,
)
from .serializers import (
    GameListSerializer, GameDetailSerializer, GameCategoryDetailSerializer,
    RegisterSerializer, EmailTokenObtainPairSerializer, UserSerializer, SellerApplicationSerializer,
    build_listing_filter_display_map,
    ListingSerializer, CreateListingSerializer,
    ConversationListSerializer, ConversationDetailSerializer, MessageSerializer,
    WalletSerializer, WalletTransactionSerializer,
    TopUpRequestSerializer, CreateTopUpRequestSerializer,
    OrderSerializer, BuyListingSerializer,
    ReviewSerializer, CreateReviewSerializer,
    NotificationSerializer,
)
from .services import (
    CHAT_MESSAGE_EMPTY_ERROR,
    CHAT_WS_TICKET_MAX_AGE_SECONDS,
    create_chat_ws_ticket,
    decode_private_media_ticket,
    apply_wallet_delta_once,
    get_or_create_locked_wallet,
    release_order_funds_to_seller_once,
    record_platform_ledger_once,
    ALLOWED_IMAGE_CONTENT_TYPES,
    validate_chat_message_content,
    validate_uploaded_image,
)
from .authentication import enforce_trusted_origin


DEFAULT_LISTING_PAGE_SIZE = 48
MAX_LISTING_PAGE_SIZE = 100
DEFAULT_CONVERSATION_PAGE_SIZE = 30
MAX_CONVERSATION_PAGE_SIZE = 100
DEFAULT_MESSAGE_PAGE_SIZE = 50
MAX_MESSAGE_PAGE_SIZE = 100
DEFAULT_TRANSACTION_PAGE_SIZE = 25
MAX_TRANSACTION_PAGE_SIZE = 100
DEFAULT_TOPUP_REQUEST_PAGE_SIZE = 20
MAX_TOPUP_REQUEST_PAGE_SIZE = 100
DEFAULT_ORDER_PAGE_SIZE = 20
MAX_ORDER_PAGE_SIZE = 100
DEFAULT_REVIEW_PAGE_SIZE = 20
MAX_REVIEW_PAGE_SIZE = 100
HEARTBEAT_MIN_WRITE_INTERVAL_SECONDS = 30
MAX_SEARCH_QUERY_LENGTH = 80
SEARCH_CACHE_SECONDS = 60
SEARCH_RESULT_LIMIT = 50
DEFAULT_NOTIFICATION_PAGE_SIZE = 30
MAX_NOTIFICATION_PAGE_SIZE = 100


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
    return (
        request.user.is_authenticated and
        payload['kind'] == kind and
        payload['object_id'] == int(object_id) and
        payload['viewer_user_id'] == request.user.id
    )


def private_file_response(file_field):
    if not file_field:
        raise Http404
    try:
        opened_file = file_field.open('rb')
    except (FileNotFoundError, OSError):
        raise Http404
    content_type = mimetypes.guess_type(file_field.name)[0] or 'application/octet-stream'
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        opened_file.close()
        raise Http404
    response = FileResponse(opened_file, content_type=content_type)
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response


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


def parse_query_date(value):
    if not value:
        return None
    try:
        return parse_date(value)
    except (TypeError, ValueError):
        return None


def create_notification(*, recipient, notification_type, title, message='', order=None, review=None):
    """Create a notification for a user."""
    return Notification.objects.create(
        recipient=recipient,
        notification_type=notification_type,
        title=title,
        message=message,
        order=order,
        review=review,
    )


# ── Public Game / Category / Filter views ────────────────────────────────────

def broadcast_chat_message(message, request):
    """Broadcast a REST-created message to any open WebSocket clients."""
    channel_layer = get_channel_layer()
    message_data = dict(MessageSerializer(message, context={'request': request}).data)
    if channel_layer is not None:
        async_to_sync(channel_layer.group_send)(
            f'chat_{message.conversation_id}',
            {
                'type': 'chat.message',
                'message': message_data,
            },
        )
    return message_data


def get_or_create_private_conversation(user, other_user):
    """Create a two-person conversation while serializing concurrent creators."""
    user_ids = sorted([user.pk, other_user.pk])
    with db_transaction.atomic():
        list(User.objects.select_for_update().filter(pk__in=user_ids).order_by('pk'))
        conversation = Conversation.objects.filter(
            participants=user
        ).filter(
            participants=other_user
        ).first()
        if conversation:
            return conversation, False

        conversation = Conversation.objects.create()
        conversation.participants.add(user, other_user)
        return conversation, True


class GameListView(generics.ListAPIView):
    """GET /api/games/ — List all active games."""
    serializer_class = GameListSerializer
    permission_classes = [permissions.AllowAny]
    queryset = Game.objects.filter(is_active=True).prefetch_related('game_categories')


class GameDetailView(generics.RetrieveAPIView):
    """GET /api/games/{slug}/ — Game detail with its categories."""
    serializer_class = GameDetailSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = 'slug'
    queryset = Game.objects.filter(is_active=True).prefetch_related(
        'game_categories__category'
    )


class GameCategoryDetailView(APIView):
    """GET /api/games/{game_slug}/{category_slug}/ — Category with filters + listings."""

    permission_classes = [permissions.AllowAny]

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
        ).select_related('seller', 'seller__profile', 'game_category__game', 'game_category__category')

        # Apply filter params from query string: ?filter_{filter_id}={option_value}
        for key, value in request.query_params.items():
            if key.startswith('filter_') and value:
                filter_id = key.replace('filter_', '')
                # Use __contains for proper dict key matching (numeric-looking keys
                # are misinterpreted as array indices by Django's __ path lookup)
                listings_qs = listings_qs.filter(
                    filter_values__contains={filter_id: value}
                )

        # Instant delivery filter: only show auto-delivery listings
        if request.query_params.get('instant_delivery') == 'true':
            listings_qs = listings_qs.filter(is_auto_delivery=True)

        # Search filter: filter by title
        search_q = request.query_params.get('search', '').strip()
        if search_q:
            listings_qs = listings_qs.filter(title__icontains=search_q)

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

        # Include all sibling categories (same game) with active listing counts
        sibling_gcs = GameCategory.objects.filter(
            game=game_category.game,
            game__is_active=True,
        ).select_related('category').order_by('order', 'category__name')

        from django.db.models import Count, Q
        sibling_gcs = sibling_gcs.annotate(
            listing_count=Count(
                'listings',
                filter=Q(listings__status='active'),
            )
        )
        cat_data['all_categories'] = [
            {
                'slug': gc.category.slug,
                'name': gc.category.name,
                'icon': gc.category.icon,
                'listing_count': gc.listing_count,
                'allow_auto_delivery': gc.allow_auto_delivery,
            }
            for gc in sibling_gcs
        ]

        return Response(cat_data)


# ── Auth views ───────────────────────────────────────────────────────────────

def set_auth_cookie(response, name, value, max_age):
    response.set_cookie(
        name,
        str(value),
        max_age=max_age,
        httponly=settings.JWT_AUTH_COOKIE_HTTP_ONLY,
        secure=settings.JWT_AUTH_COOKIE_SECURE,
        samesite=settings.JWT_AUTH_COOKIE_SAMESITE,
        path=settings.JWT_AUTH_COOKIE_PATH,
    )


def set_jwt_auth_cookies(response, access=None, refresh=None):
    if access:
        set_auth_cookie(
            response,
            settings.JWT_AUTH_COOKIE_ACCESS,
            access,
            int(api_settings.ACCESS_TOKEN_LIFETIME.total_seconds()),
        )
    if refresh:
        set_auth_cookie(
            response,
            settings.JWT_AUTH_COOKIE_REFRESH,
            refresh,
            int(api_settings.REFRESH_TOKEN_LIFETIME.total_seconds()),
        )


def clear_jwt_auth_cookies(response):
    for cookie_name in (settings.JWT_AUTH_COOKIE_ACCESS, settings.JWT_AUTH_COOKIE_REFRESH):
        response.delete_cookie(
            cookie_name,
            path=settings.JWT_AUTH_COOKIE_PATH,
            samesite=settings.JWT_AUTH_COOKIE_SAMESITE,
        )


class LoginView(ScopedPostThrottleMixin, TokenObtainPairView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    serializer_class = EmailTokenObtainPairSerializer
    throttle_scope = 'auth_login'

    def post(self, request, *args, **kwargs):
        enforce_trusted_origin(request)
        response = super().post(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            access = response.data.get('access')
            refresh = response.data.get('refresh')
            set_jwt_auth_cookies(
                response,
                access=access,
                refresh=refresh,
            )
            response.data = {'message': 'Logged in.'}
        return response


class RefreshTokenView(ScopedPostThrottleMixin, TokenRefreshView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'auth_refresh'

    def post(self, request, *args, **kwargs):
        enforce_trusted_origin(request)
        data = request.data.copy()
        if not data.get('refresh'):
            cookie_refresh = request.COOKIES.get(settings.JWT_AUTH_COOKIE_REFRESH)
            if cookie_refresh:
                data['refresh'] = cookie_refresh

        serializer = self.get_serializer(data=data)

        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0])

        response = Response({'message': 'Token refreshed.'}, status=status.HTTP_200_OK)
        set_jwt_auth_cookies(
            response,
            access=serializer.validated_data.get('access'),
            refresh=serializer.validated_data.get('refresh'),
        )
        return response


class LogoutView(APIView):
    """POST /api/auth/logout/ - Clear auth cookies."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        enforce_trusted_origin(request)
        response = Response({'message': 'Logged out.'})
        clear_jwt_auth_cookies(response)
        return response


class RegisterView(ScopedPostThrottleMixin, generics.CreateAPIView):
    """POST /api/auth/register/ — Register a new user."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
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
        ).select_related('seller', 'seller__profile', 'game_category__game', 'game_category__category')

    def list(self, request, *args, **kwargs):
        all_qs = self.get_queryset()
        include_facets = request.query_params.get('include_facets') != '0'

        summary = None
        status_counts = None
        seller_games = None
        if include_facets:
            # Summary always reflects ALL listings (unfiltered)
            summary = all_qs.aggregate(
                total_count=Count('id'),
                active_count=Count('id', filter=Q(status='active')),
                sold_count=Count('id', filter=Q(status='sold')),
                inactive_count=Count('id', filter=Q(status='inactive')),
            )

            # Status counts for tab badges
            status_counts = {
                'active': summary['active_count'],
                'inactive': summary['inactive_count'],
                'sold': summary['sold_count'],
            }

            # Build game → categories breakdown from ALL user listings
            gc_stats = (
                all_qs
                .values(
                    'game_category__game__slug',
                    'game_category__game__name',
                    'game_category__category__slug',
                    'game_category__category__name',
                    'game_category__category__icon',
                )
                .annotate(listing_count=Count('id'))
                .order_by('game_category__game__name', 'game_category__category__name')
            )
            games_map = {}
            for row in gc_stats:
                g_slug = row['game_category__game__slug']
                g_name = row['game_category__game__name']
                if g_slug not in games_map:
                    games_map[g_slug] = {
                        'slug': g_slug,
                        'name': g_name,
                        'listing_count': 0,
                        'categories': [],
                    }
                games_map[g_slug]['listing_count'] += row['listing_count']
                games_map[g_slug]['categories'].append({
                    'slug': row['game_category__category__slug'],
                    'name': row['game_category__category__name'],
                    'icon': row['game_category__category__icon'],
                    'listing_count': row['listing_count'],
                })
            seller_games = list(games_map.values())

        # Apply filters
        listings_qs = all_qs

        status_filter = request.query_params.get('status', '').strip()
        if status_filter in ('active', 'inactive', 'sold'):
            listings_qs = listings_qs.filter(status=status_filter)

        search_q = request.query_params.get('search', '').strip()
        if search_q:
            listings_qs = listings_qs.filter(title__icontains=search_q)

        game_filter = request.query_params.get('game', '').strip()
        if game_filter:
            listings_qs = listings_qs.filter(game_category__game__slug=game_filter)

        category_filter = request.query_params.get('category', '').strip()
        if category_filter:
            listings_qs = listings_qs.filter(game_category__category__slug=category_filter)

        limit, offset = get_pagination_params(request)
        filtered_count = listings_qs.count()
        listings = list(listings_qs[offset:offset + limit])
        serializer = self.get_serializer(
            listings,
            many=True,
            context={
                **self.get_serializer_context(),
                'filter_option_display_map': build_listing_filter_display_map(listings),
            },
        )
        payload = {
            'listings': serializer.data,
            'pagination': get_pagination_payload(filtered_count, limit, offset),
        }
        if include_facets:
            payload.update({
                'summary': summary,
                'status_counts': status_counts,
                'seller_games': seller_games,
            })
        return Response(payload)


class ListingDetailView(APIView):
    """GET /api/listings/{id}/ — Get listing detail.
    PUT /api/listings/{id}/ — Edit listing (owner only).
    DELETE /api/listings/{id}/ — Delete listing (owner only).
    """
    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
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
        conversations_qs = Conversation.objects.filter(participants=request.user)
        other_user_id = request.query_params.get('other_user_id')
        if other_user_id not in (None, ''):
            try:
                other_user_id = int(other_user_id)
            except (TypeError, ValueError):
                return Response({'error': 'other_user_id must be a valid user id.'}, status=400)
            if other_user_id <= 0 or other_user_id == request.user.id:
                return Response({'error': 'other_user_id must be a valid user id.'}, status=400)
            conversations_qs = conversations_qs.filter(participants__id=other_user_id)

        latest_message = Message.objects.filter(
            conversation=OuterRef('pk')
        ).order_by('-created_at', '-pk')
        conversations = conversations_qs.annotate(
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

        if any(param in request.query_params for param in ('limit', 'offset', 'other_user_id')):
            limit, offset = get_pagination_params(
                request,
                default_limit=DEFAULT_CONVERSATION_PAGE_SIZE,
                max_limit=MAX_CONVERSATION_PAGE_SIZE,
            )
            total_count = conversations_qs.count()
            page = list(conversations[offset:offset + limit])
            return Response({
                'conversations': ConversationListSerializer(
                    page,
                    many=True,
                    context={'request': request},
                ).data,
                'pagination': get_pagination_payload(total_count, limit, offset),
            })

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
        initial_message, validation_error = validate_chat_message_content(
            request.data.get('message', ''),
            allow_empty=True,
        )
        if validation_error and validation_error != CHAT_MESSAGE_EMPTY_ERROR:
            return Response({'error': validation_error}, status=400)

        if other_user_id in (None, ''):
            return Response({'error': 'user_id is required.'}, status=400)

        try:
            other_user_id = int(other_user_id)
        except (TypeError, ValueError):
            return Response({'error': 'user_id must be a valid user id.'}, status=400)

        if other_user_id <= 0:
            return Response({'error': 'user_id must be a valid user id.'}, status=400)

        if other_user_id == request.user.id:
            return Response({'error': 'Cannot chat with yourself.'}, status=400)

        other_user = get_object_or_404(User, id=other_user_id)

        conversation, _ = get_or_create_private_conversation(request.user, other_user)

        # Send initial message if provided
        if initial_message:
            message = Message.objects.create(
                conversation=conversation,
                sender=request.user,
                content=initial_message,
            )
            conversation.save()  # Update updated_at
            broadcast_chat_message(message, request)

        data = ConversationDetailSerializer(conversation, context={'request': request}).data
        return Response(data, status=201)


class ConversationDetailView(APIView):
    """GET /api/chat/{id}/ — Get conversation with messages."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        conversation = get_object_or_404(
            Conversation.objects.prefetch_related('participants'),
            pk=pk,
            participants=request.user,
        )

        # Mark unread messages from the other user as read
        conversation.messages.filter(is_read=False).exclude(
            sender=request.user
        ).update(is_read=True)

        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_MESSAGE_PAGE_SIZE,
            max_limit=MAX_MESSAGE_PAGE_SIZE,
        )
        messages_qs = conversation.messages.select_related('sender').order_by('-pk')
        total_count = messages_qs.count()
        before_id = None
        if request.query_params.get('before_id') not in (None, ''):
            try:
                before_id = int(request.query_params.get('before_id'))
            except (TypeError, ValueError):
                return Response({'error': 'before_id must be a valid message id.'}, status=400)
            if before_id <= 0:
                return Response({'error': 'before_id must be a valid message id.'}, status=400)

        if before_id is not None:
            page_qs = messages_qs.filter(pk__lt=before_id)
            page_desc = list(page_qs[:limit + 1])
            has_more = len(page_desc) > limit
            page_desc = page_desc[:limit]
            messages = list(reversed(page_desc))
            pagination = {
                'count': total_count,
                'limit': limit,
                'before_id': before_id,
                'next_before_id': page_desc[-1].pk if has_more and page_desc else None,
                'has_more': has_more,
            }
        elif 'offset' in request.query_params:
            messages = list(reversed(list(messages_qs[offset:offset + limit])))
            pagination = get_pagination_payload(total_count, limit, offset)
        else:
            page_desc = list(messages_qs[:limit + 1])
            has_more = len(page_desc) > limit
            page_desc = page_desc[:limit]
            messages = list(reversed(page_desc))
            pagination = {
                'count': total_count,
                'limit': limit,
                'before_id': None,
                'next_before_id': page_desc[-1].pk if has_more and page_desc else None,
                'has_more': has_more,
            }

        data = ConversationDetailSerializer(
            conversation,
            context={'request': request, 'messages': messages},
        ).data
        data['message_pagination'] = pagination
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


class SendMessageView(ScopedPostThrottleMixin, APIView):
    """POST /api/chat/{id}/send/ — Send a message in a conversation."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'chat_message'

    def post(self, request, pk):
        conversation = get_object_or_404(
            Conversation, pk=pk, participants=request.user
        )

        content, validation_error = validate_chat_message_content(request.data.get('content', ''))
        if validation_error:
            return Response({'error': validation_error}, status=400)

        message = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            content=content,
        )
        conversation.save()  # Update updated_at

        data = broadcast_chat_message(message, request)
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

        content, validation_error = validate_chat_message_content(
            request.data.get('content', ''),
            allow_empty=True,
        )
        if validation_error and validation_error != CHAT_MESSAGE_EMPTY_ERROR:
            return Response({'error': validation_error}, status=400)
        message = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            content=content,
            image=image,
        )
        conversation.save()

        data = broadcast_chat_message(message, request)
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
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        now = timezone.now()
        should_update = (
            profile.last_active is None or
            (now - profile.last_active).total_seconds() >= HEARTBEAT_MIN_WRITE_INTERVAL_SECONDS
        )
        if should_update:
            profile.last_active = now
            profile.save(update_fields=['last_active'])
        return Response({'status': 'ok', 'updated': should_update})


# ── Wallet views ──────────────────────────────────────────────────────────────

class WalletView(APIView):
    """GET /api/wallet/ — Get wallet balance + recent transactions."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        limit, offset = get_pagination_params(
            request,
            default_limit=20,
            max_limit=MAX_TRANSACTION_PAGE_SIZE,
        )
        transactions_qs = wallet.transactions.all()
        total_count = transactions_qs.count()
        transactions = transactions_qs[offset:offset + limit]
        return Response({
            'balance': str(wallet.balance),
            'transactions': WalletTransactionSerializer(transactions, many=True).data,
            'transaction_pagination': get_pagination_payload(total_count, limit, offset),
        })


class WalletTransactionsView(APIView):
    """GET /api/wallet/transactions/ — Full transaction history."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_TRANSACTION_PAGE_SIZE,
            max_limit=MAX_TRANSACTION_PAGE_SIZE,
        )
        transactions_qs = wallet.transactions.all()
        total_count = transactions_qs.count()
        transactions = transactions_qs[offset:offset + limit]
        return Response({
            'transactions': WalletTransactionSerializer(transactions, many=True).data,
            'pagination': get_pagination_payload(total_count, limit, offset),
        })


class TopUpRequestView(ScopedPostThrottleMixin, APIView):
    """POST /api/wallet/top-up/ — Create a top-up request.
    GET /api/wallet/top-up/ — List my top-up requests.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'topup_request'

    def get(self, request):
        requests_qs = TopUpRequest.objects.filter(user=request.user)
        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_TOPUP_REQUEST_PAGE_SIZE,
            max_limit=MAX_TOPUP_REQUEST_PAGE_SIZE,
        )
        total_count = requests_qs.count()
        topup_requests = requests_qs[offset:offset + limit]
        return Response({
            'topup_requests': TopUpRequestSerializer(
                topup_requests,
                many=True,
                context={'request': request},
            ).data,
            'pagination': get_pagination_payload(total_count, limit, offset),
        })

    def post(self, request):
        serializer = CreateTopUpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Handle payment proof image upload
        payment_proof = request.FILES.get('payment_proof')
        if not payment_proof:
            return Response(
                {'payment_proof': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

            is_auto = listing.is_auto_delivery
            if is_auto:
                all_lines = [line for line in listing.auto_delivery_data.splitlines() if line.strip()]
                if len(all_lines) < qty:
                    item_label = 'item' if len(all_lines) == 1 else 'items'
                    return Response({'error': f'Only {len(all_lines)} {item_label} remaining for auto-delivery.'}, status=400)
                delivered_lines = all_lines[:qty]
                remaining_lines = all_lines[qty:]
                delivery_note = '\n'.join(delivered_lines)
                # Append delivery instructions if seller provided them
                if listing.delivery_instructions.strip():
                    delivery_note += '\n\n--- Seller Instructions ---\n' + listing.delivery_instructions.strip()
                initial_status = 'delivered'
            else:
                initial_status = 'pending'
                delivery_note = ''

            wallet = get_or_create_locked_wallet(request.user)

            if wallet.balance < total:
                return Response({'error': 'Insufficient wallet balance.'}, status=400)

            category = listing.game_category.category
            rate = get_commission_rate(listing.seller, category)
            commission = (total * rate / Decimal('100')).quantize(Decimal('0.01'))
            seller_receives = total - commission

            # Deduct from buyer only after all purchase validations have passed.
            wallet.balance -= total
            wallet.save(update_fields=['balance', 'updated_at'])

            if is_auto:
                # Update the listing's remaining auto_delivery_data and quantity
                listing.auto_delivery_data = '\n'.join(remaining_lines)
                listing.quantity = len(remaining_lines)
                if listing.quantity <= 0:
                    listing.quantity = 0
                    listing.status = 'sold'
                listing.save(update_fields=['auto_delivery_data', 'quantity', 'status'])
            else:
                # Reduce listing stock only if not evergreen (quantity is not null)
                if listing.quantity is not None:
                    listing.quantity -= qty
                    if listing.quantity <= 0:
                        listing.quantity = 0
                        listing.status = 'sold'
                    listing.save(update_fields=['quantity', 'status'])

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
                status=initial_status,
                delivery_note=delivery_note,
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

            conversation, _ = get_or_create_private_conversation(request.user, listing.seller)

            order.conversation = conversation
            order.save(update_fields=['conversation'])

            # Notify seller about new order
            create_notification(
                recipient=listing.seller,
                notification_type='new_order',
                title=f'New order from {request.user.username}',
                message=f'{request.user.username} purchased "{listing.title}" (x{qty}) for PKR {total}.',
                order=order,
            )

            # For auto-delivery, also notify buyer that it's delivered
            if is_auto:
                create_notification(
                    recipient=request.user,
                    notification_type='order_delivered',
                    title='Your order has been automatically delivered!',
                    message=f'Your order "{listing.title}" has been automatically delivered. Check your order for the delivery details.',
                    order=order,
                )

        return Response(OrderSerializer(order).data, status=201)


class MyOrdersView(APIView):
    """GET /api/orders/mine/ — Orders where I'm the buyer.
    Query params: status, search, date_from, date_to, limit, offset
    """
    permission_classes = [permissions.IsAuthenticated]

    def _apply_filters(self, request, orders_qs):
        status_filter = request.query_params.get('status', '').strip()
        if status_filter:
            orders_qs = orders_qs.filter(status=status_filter)

        search = request.query_params.get('search', '').strip()
        if search:
            orders_qs = orders_qs.filter(
                Q(listing_title__icontains=search) | Q(seller__username__icontains=search)
            )

        date_from = request.query_params.get('date_from', '').strip()
        if date_from:
            parsed_date = parse_query_date(date_from)
            if parsed_date:
                orders_qs = orders_qs.filter(created_at__date__gte=parsed_date)

        date_to = request.query_params.get('date_to', '').strip()
        if date_to:
            parsed_date = parse_query_date(date_to)
            if parsed_date:
                orders_qs = orders_qs.filter(created_at__date__lte=parsed_date)

        return orders_qs

    def get(self, request):
        orders_qs = Order.objects.filter(
            buyer=request.user
        ).select_related('listing', 'seller', 'conversation')

        orders_qs = self._apply_filters(request, orders_qs)

        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_ORDER_PAGE_SIZE,
            max_limit=MAX_ORDER_PAGE_SIZE,
        )
        total_count = orders_qs.count()
        orders = orders_qs[offset:offset + limit]
        # Status counts (unfiltered) for tab badges
        status_counts = Order.objects.filter(buyer=request.user).values('status').annotate(
            count=Count('id')
        )
        counts = {item['status']: item['count'] for item in status_counts}

        return Response({
            'orders': OrderSerializer(orders, many=True).data,
            'pagination': get_pagination_payload(total_count, limit, offset),
            'status_counts': counts,
        })


class MySalesView(APIView):
    """GET /api/orders/sales/ — Orders where I'm the seller.
    Query params: status, search, date_from, date_to, limit, offset
    """
    permission_classes = [permissions.IsAuthenticated]

    def _apply_filters(self, request, orders_qs):
        status_filter = request.query_params.get('status', '').strip()
        if status_filter:
            orders_qs = orders_qs.filter(status=status_filter)

        search = request.query_params.get('search', '').strip()
        if search:
            orders_qs = orders_qs.filter(
                Q(listing_title__icontains=search) | Q(buyer__username__icontains=search)
            )

        date_from = request.query_params.get('date_from', '').strip()
        if date_from:
            parsed_date = parse_query_date(date_from)
            if parsed_date:
                orders_qs = orders_qs.filter(created_at__date__gte=parsed_date)

        date_to = request.query_params.get('date_to', '').strip()
        if date_to:
            parsed_date = parse_query_date(date_to)
            if parsed_date:
                orders_qs = orders_qs.filter(created_at__date__lte=parsed_date)

        return orders_qs

    def get(self, request):
        orders_qs = Order.objects.filter(
            seller=request.user
        ).select_related('listing', 'buyer', 'conversation')

        orders_qs = self._apply_filters(request, orders_qs)

        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_ORDER_PAGE_SIZE,
            max_limit=MAX_ORDER_PAGE_SIZE,
        )
        total_count = orders_qs.count()
        orders = orders_qs[offset:offset + limit]
        # Status counts (unfiltered) for tab badges
        status_counts = Order.objects.filter(seller=request.user).values('status').annotate(
            count=Count('id')
        )
        counts = {item['status']: item['count'] for item in status_counts}
        summary = Order.objects.filter(seller=request.user).aggregate(
            pending_count=Count('id', filter=Q(status='pending')),
            completed_count=Count('id', filter=Q(status='completed')),
            total_revenue=Sum('seller_amount', filter=Q(status='completed')),
        )
        summary['total_revenue'] = str(summary['total_revenue'] or Decimal('0.00'))

        return Response({
            'sales': OrderSerializer(orders, many=True).data,
            'pagination': get_pagination_payload(total_count, limit, offset),
            'summary': summary,
            'status_counts': counts,
        })


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
            conversation, _ = get_or_create_private_conversation(order.buyer, order.seller)

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

            # Notify buyer that seller delivered
            create_notification(
                recipient=order.buyer,
                notification_type='order_delivered',
                title='Your order has been delivered',
                message=f'{request.user.username} marked order "{order.listing_title}" as delivered.',
                order=order,
            )

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

            if order.status != 'delivered':
                return Response({'error': 'Order cannot be confirmed in current state.'}, status=400)

            release_order_funds_to_seller_once(
                order,
                sale_description=f'Sale completed: {order.listing_title} (x{order.quantity})',
                commission_description=f'Commission ({order.commission_rate}%): {order.listing_title}',
                ledger_description=f'Commission collected: {order.listing_title} (x{order.quantity})',
            )

            order.status = 'completed'
            order.save(update_fields=['status', 'updated_at'])

            # Notify seller that buyer confirmed
            create_notification(
                recipient=order.seller,
                notification_type='order_confirmed',
                title='Order confirmed — funds released!',
                message=f'{request.user.username} confirmed delivery of "{order.listing_title}". PKR {order.seller_amount} has been credited to your wallet.',
                order=order,
            )

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

            # Notify seller about dispute
            create_notification(
                recipient=order.seller,
                notification_type='order_disputed',
                title='Order disputed by buyer',
                message=f'{request.user.username} has disputed order "{order.listing_title}". Reason: {reason}',
                order=order,
            )

        return Response(OrderSerializer(order).data)


class ResolveDisputeView(APIView):
    """POST /api/admin/orders/<id>/resolve-dispute/ - Staff resolves a disputed order."""
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        resolution_action = request.data.get('resolution_action')
        if resolution_action not in ('refund_buyer', 'pay_seller'):
            return Response({
                'error': 'resolution_action must be refund_buyer or pay_seller.',
            }, status=400)

        with db_transaction.atomic():
            order = get_object_or_404(
                Order.objects.select_for_update().select_related('buyer', 'seller'),
                pk=pk,
            )

            if order.status != 'disputed':
                return Response({'error': 'Only disputed orders can be resolved.'}, status=400)

            if resolution_action == 'refund_buyer':
                apply_wallet_delta_once(
                    order.buyer,
                    delta=order.total_amount,
                    transaction_type='refund',
                    amount=order.total_amount,
                    description=f'Dispute resolved (buyer): {order.listing_title}',
                    reference_id=f'order_{order.pk}',
                )

                if order.listing_id:
                    listing = Listing.objects.select_for_update().filter(pk=order.listing_id).first()
                    if listing and listing.quantity is not None and not listing.is_auto_delivery:
                        listing.quantity += order.quantity
                        if listing.status == 'sold':
                            listing.status = 'active'
                        listing.save(update_fields=['quantity', 'status'])

                order.status = 'cancelled'

                # Notify both parties
                create_notification(
                    recipient=order.buyer,
                    notification_type='order_cancelled',
                    title='Dispute resolved — refund issued',
                    message=f'Your dispute for "{order.listing_title}" has been resolved. PKR {order.total_amount} has been refunded to your wallet.',
                    order=order,
                )
                create_notification(
                    recipient=order.seller,
                    notification_type='order_cancelled',
                    title='Dispute resolved — order cancelled',
                    message=f'The dispute for "{order.listing_title}" has been resolved in favour of the buyer. The order has been cancelled.',
                    order=order,
                )
            else:
                release_order_funds_to_seller_once(
                    order,
                    sale_description=f'Dispute resolved (seller): {order.listing_title}',
                    commission_description=f'Commission ({order.commission_rate}%): {order.listing_title}',
                    ledger_description=f'Commission collected: {order.listing_title}',
                )
                order.status = 'completed'

                # Notify both parties
                create_notification(
                    recipient=order.seller,
                    notification_type='order_confirmed',
                    title='Dispute resolved — funds released!',
                    message=f'The dispute for "{order.listing_title}" has been resolved in your favour. PKR {order.seller_amount} has been credited.',
                    order=order,
                )
                create_notification(
                    recipient=order.buyer,
                    notification_type='order_confirmed',
                    title='Dispute resolved — order completed',
                    message=f'The dispute for "{order.listing_title}" has been resolved. The order is now marked as completed.',
                    order=order,
                )

            order.save(update_fields=['status', 'updated_at'])

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
                if listing and (listing.quantity is None or listing.is_auto_delivery):
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
                if order.commission_amount > 0:
                    record_platform_ledger_once(
                        entry_type='commission_reversed',
                        amount=-order.commission_amount,
                        description=f'Commission reversed: {order.listing_title} (x{order.quantity})',
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

            # Notify buyer about the refund
            create_notification(
                recipient=order.buyer,
                notification_type='order_cancelled',
                title='Refund received',
                message=f'{order.seller.username} has refunded your order "{order.listing_title}". PKR {order.total_amount} has been credited to your wallet.',
                order=order,
            )

        return Response(OrderSerializer(order).data)


# ── Reviews ───────────────────────────────────────────────────────────────────────

class CreateReviewView(APIView):
    """POST /api/reviews/ — Submit a review for a completed order."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = CreateReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        order = get_object_or_404(Order, pk=data['order_id'], buyer=request.user)

        if order.status != 'completed':
            return Response({'error': 'You can only review completed orders.'}, status=400)

        if hasattr(order, 'review'):
            return Response({'error': 'You have already reviewed this order.'}, status=400)

        review = Review.objects.create(
            order=order,
            reviewer=request.user,
            seller=order.seller,
            rating=data['rating'],
            comment=data.get('comment', ''),
        )

        # Notify seller about new review
        create_notification(
            recipient=order.seller,
            notification_type='new_review',
            title=f'New {data["rating"]}★ review from {request.user.username}',
            message=f'{request.user.username} left a {data["rating"]}-star review for "{order.listing_title}".' + (f' "{data.get("comment", "")}"' if data.get('comment') else ''),
            order=order,
            review=review,
        )

        return Response(ReviewSerializer(review).data, status=201)


class SellerReviewsView(APIView):
    """GET /api/reviews/seller/<username>/ — Get all reviews for a seller."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, username):
        seller = get_object_or_404(User, username=username)
        reviews_qs = Review.objects.filter(
            seller=seller
        ).select_related('reviewer', 'order')
        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_REVIEW_PAGE_SIZE,
            max_limit=MAX_REVIEW_PAGE_SIZE,
        )
        total_count = reviews_qs.count()
        reviews = reviews_qs[offset:offset + limit]
        return Response({
            'reviews': ReviewSerializer(reviews, many=True).data,
            'pagination': get_pagination_payload(total_count, limit, offset),
        })


class SellerProfileView(APIView):
    """GET /api/seller/profile/<username>/ — Public seller profile with stats."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, username):
        seller = get_object_or_404(User, username=username)
        profile = seller.profile

        if profile.seller_status != 'approved':
            return Response({'error': 'Seller not found.'}, status=404)

        review_stats = Review.objects.filter(seller=seller).aggregate(
            review_count=Count('id'),
            avg_rating=Avg('rating'),
        )
        review_count = review_stats['review_count']
        avg_rating = (
            round(float(review_stats['avg_rating']), 1)
            if review_stats['avg_rating'] is not None else None
        )

        # Get completed sales count
        completed_sales = Order.objects.filter(
            seller=seller, status='completed'
        ).count()

        # Get active listings count
        active_listings = Listing.objects.filter(
            seller=seller, status='active'
        ).count()

        # Member since
        member_since = seller.date_joined

        # Online status
        is_online = profile.is_online
        last_active = profile.last_active

        return Response({
            'username': seller.username,
            'member_since': member_since,
            'is_online': is_online,
            'last_active': last_active,
            'avg_rating': avg_rating,
            'review_count': review_count,
            'completed_sales': completed_sales,
            'active_listings': active_listings,
        })


class SearchView(APIView):
    """GET /api/search/?q=<query> — Search game-categories."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'search'

    def get(self, request):
        query = request.query_params.get('q', '').strip()
        if not query or len(query) < 2:
            return Response({'query': query, 'results': []})
        if len(query) > MAX_SEARCH_QUERY_LENGTH:
            return Response({
                'error': f'Search query cannot be longer than {MAX_SEARCH_QUERY_LENGTH} characters.',
            }, status=400)

        normalized_query = ' '.join(query.split()).casefold()
        cache_key = 'search:v1:' + hashlib.sha256(
            normalized_query.encode('utf-8')
        ).hexdigest()
        cached_results = cache.get(cache_key)
        if cached_results is not None:
            return Response({'query': query, 'results': cached_results})

        # Search GameCategory via game name, game keywords, or category name
        game_categories = GameCategory.objects.filter(
            game__is_active=True,
        ).filter(
            Q(game__name__icontains=query) |
            Q(game__search_keywords__icontains=query) |
            Q(category__name__icontains=query)
        ).select_related('game', 'category').order_by(
            'game__order', 'game__name', 'order', 'category__name'
        )[:SEARCH_RESULT_LIMIT]

        results = []
        for gc in game_categories:
            icon_url = None
            if gc.game.icon:
                icon_url = request.build_absolute_uri(gc.game.icon.url)
            results.append({
                'id': gc.id,
                'display_name': f'{gc.game.name} {gc.category.name}',
                'game_name': gc.game.name,
                'game_slug': gc.game.slug,
                'game_icon_url': icon_url,
                'category_name': gc.category.name,
                'category_slug': gc.category.slug,
            })

        cache.set(cache_key, results, SEARCH_CACHE_SECONDS)
        return Response({'query': query, 'results': results})


# ── Notifications ────────────────────────────────────────────────────────────

class NotificationListView(APIView):
    """GET /api/notifications/ — List user's notifications (paginated)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = Notification.objects.filter(recipient=request.user)
        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_NOTIFICATION_PAGE_SIZE,
            max_limit=MAX_NOTIFICATION_PAGE_SIZE,
        )
        total_count = qs.count()
        unread_count = qs.filter(is_read=False).count()
        notifications = qs[offset:offset + limit]
        return Response({
            'notifications': NotificationSerializer(notifications, many=True).data,
            'unread_count': unread_count,
            'pagination': get_pagination_payload(total_count, limit, offset),
        })


class NotificationMarkReadView(APIView):
    """POST /api/notifications/read/ — Mark notification(s) as read."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        notification_id = request.data.get('notification_id')

        if notification_id == 'all':
            # Mark all unread notifications as read
            updated = Notification.objects.filter(
                recipient=request.user,
                is_read=False,
            ).update(is_read=True)
            return Response({'marked_read': updated})
        elif notification_id:
            # Mark a single notification as read
            notification = get_object_or_404(
                Notification, pk=notification_id, recipient=request.user,
            )
            if not notification.is_read:
                notification.is_read = True
                notification.save(update_fields=['is_read'])
            return Response({'marked_read': 1})
        else:
            return Response({'error': 'notification_id is required.'}, status=400)


class NotificationUnreadCountView(APIView):
    """GET /api/notifications/unread-count/ — Unread notification count."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(
            recipient=request.user,
            is_read=False,
        ).count()
        return Response({'unread_count': count})


class SellerDashboardView(APIView):
    """GET /api/seller/dashboard/ — Comprehensive seller analytics dashboard."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile = request.user.profile
        if not profile.is_seller:
            return Response({'error': 'Not a seller.'}, status=403)

        now = timezone.now()
        thirty_days_ago = now - timezone.timedelta(days=30)
        seven_days_ago = now - timezone.timedelta(days=7)

        # ── All-time order metrics ──
        all_orders = Order.objects.filter(seller=request.user)
        order_stats = all_orders.aggregate(
            total_orders=Count('id'),
            pending_count=Count('id', filter=Q(status='pending')),
            delivered_count=Count('id', filter=Q(status='delivered')),
            completed_count=Count('id', filter=Q(status='completed')),
            disputed_count=Count('id', filter=Q(status='disputed')),
            cancelled_count=Count('id', filter=Q(status='cancelled')),
            total_revenue=Sum('seller_amount', filter=Q(status='completed')),
            total_commission=Sum('commission_amount', filter=Q(status='completed')),
            total_gross=Sum('total_amount', filter=Q(status='completed')),
        )

        # ── 30-day revenue ──
        month_stats = all_orders.filter(
            created_at__gte=thirty_days_ago,
        ).aggregate(
            month_revenue=Sum('seller_amount', filter=Q(status='completed')),
            month_orders=Count('id', filter=Q(status='completed')),
        )

        # ── 7-day revenue ──
        week_stats = all_orders.filter(
            created_at__gte=seven_days_ago,
        ).aggregate(
            week_revenue=Sum('seller_amount', filter=Q(status='completed')),
            week_orders=Count('id', filter=Q(status='completed')),
        )

        # ── Daily revenue for last 30 days (for sparkline chart) ──
        from django.db.models.functions import TruncDate
        daily_revenue = list(
            all_orders.filter(
                created_at__gte=thirty_days_ago,
                status='completed',
            ).annotate(
                day=TruncDate('created_at')
            ).values('day').annotate(
                revenue=Sum('seller_amount'),
                count=Count('id'),
            ).order_by('day')
        )
        daily_revenue_data = [
            {
                'date': entry['day'].isoformat(),
                'revenue': str(entry['revenue']),
                'count': entry['count'],
            }
            for entry in daily_revenue
        ]

        # ── Listing stats ──
        listings = Listing.objects.filter(seller=request.user)
        listing_stats = listings.aggregate(
            total_listings=Count('id'),
            active_listings=Count('id', filter=Q(status='active')),
            inactive_listings=Count('id', filter=Q(status='inactive')),
            sold_listings=Count('id', filter=Q(status='sold')),
        )

        # ── Review stats ──
        reviews = Review.objects.filter(seller=request.user)
        review_stats = reviews.aggregate(
            total_reviews=Count('id'),
            avg_rating=Avg('rating'),
        )
        rating_dist = dict(
            reviews.values_list('rating').annotate(count=Count('id')).order_by('rating')
        )

        # ── Recent sales (last 5) ──
        recent_sales = all_orders.filter(
            status__in=['completed', 'delivered', 'pending'],
        ).select_related('buyer', 'listing').order_by('-created_at')[:5]
        recent_sales_data = [
            {
                'id': order.pk,
                'listing_title': order.listing_title,
                'buyer_name': order.buyer.username,
                'total_amount': str(order.total_amount),
                'seller_amount': str(order.seller_amount),
                'status': order.status,
                'status_display': order.get_status_display(),
                'created_at': order.created_at.isoformat(),
            }
            for order in recent_sales
        ]

        # ── Top selling categories ──
        top_categories = list(
            all_orders.filter(status='completed').values(
                'listing__game_category__game__name',
                'listing__game_category__category__name',
            ).annotate(
                sales_count=Count('id'),
                revenue=Sum('seller_amount'),
            ).order_by('-sales_count')[:5]
        )
        top_categories_data = [
            {
                'game': entry['listing__game_category__game__name'] or 'Unknown',
                'category': entry['listing__game_category__category__name'] or 'Unknown',
                'sales_count': entry['sales_count'],
                'revenue': str(entry['revenue']),
            }
            for entry in top_categories
        ]

        # ── Wallet balance ──
        try:
            wallet_balance = str(request.user.wallet.balance)
        except Wallet.DoesNotExist:
            wallet_balance = '0.00'

        return Response({
            'orders': {
                'total': order_stats['total_orders'],
                'pending': order_stats['pending_count'],
                'delivered': order_stats['delivered_count'],
                'completed': order_stats['completed_count'],
                'disputed': order_stats['disputed_count'],
                'cancelled': order_stats['cancelled_count'],
            },
            'revenue': {
                'total': str(order_stats['total_revenue'] or '0.00'),
                'total_gross': str(order_stats['total_gross'] or '0.00'),
                'total_commission': str(order_stats['total_commission'] or '0.00'),
                'month': str(month_stats['month_revenue'] or '0.00'),
                'month_orders': month_stats['month_orders'],
                'week': str(week_stats['week_revenue'] or '0.00'),
                'week_orders': week_stats['week_orders'],
            },
            'daily_revenue': daily_revenue_data,
            'listings': listing_stats,
            'reviews': {
                'total': review_stats['total_reviews'],
                'avg_rating': round(review_stats['avg_rating'] or 0, 1),
                'distribution': {str(i): rating_dist.get(i, 0) for i in range(1, 6)},
            },
            'recent_sales': recent_sales_data,
            'top_categories': top_categories_data,
            'wallet_balance': wallet_balance,
        })
