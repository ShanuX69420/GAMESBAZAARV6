from datetime import timedelta
from decimal import Decimal
import hashlib
import logging
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
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.db.models import (
    Avg, Case, Count, ExpressionWrapper, F, IntegerField, Min, OuterRef,
    Prefetch, Q, Subquery, Sum, Value, When,
)
from django.db.models.functions import Coalesce
from django.db import IntegrityError, transaction as db_transaction
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.utils.dateparse import parse_date
from .models import (
    Game, GameCategory, CategoryOption, UserProfile, Listing, Conversation, Message,
    Wallet, WalletTransaction, TopUpRequest, WithdrawRequest, Order,
    JazzCashPayment, SellerCommissionOverride,
    Review, Notification, Report, SupportTicket, SocialAccount,
)

GAME_LIST_CACHE_KEY = 'game-list:v1'
GAME_LIST_CACHE_SECONDS = 60
SELLER_PROFILE_CACHE_SECONDS = 30
UNREAD_COUNT_CACHE_SECONDS = 5
from .serializers import (
    GameListSerializer, GameDetailSerializer, GameCategoryDetailSerializer,
    RegisterSerializer, EmailTokenObtainPairSerializer, UserSerializer, SellerApplicationSerializer,
    UpdateProfileSerializer, ChangePasswordSerializer, CompleteProfileSerializer,
    build_listing_filter_display_map, get_auto_delivery_inventory_lines,
    ListingSerializer, CreateListingSerializer,
    AutoDeliveryRestockSerializer, MAX_AUTO_DELIVERY_LINES, MAX_AUTO_DELIVERY_LINE_LENGTH,
    ConversationListSerializer, ConversationDetailSerializer, MessageSerializer,
    WalletSerializer, WalletTransactionSerializer,
    TopUpRequestSerializer, CreateTopUpRequestSerializer,
    JazzCashTopUpInitiateSerializer, JazzCashBuyInitiateSerializer,
    JazzCashPaymentSerializer, MIN_TOPUP_AMOUNT,
    WithdrawRequestSerializer, CreateWithdrawRequestSerializer,
    OrderSerializer, BuyListingSerializer, DeliverOrderSerializer, DisputeOrderSerializer,
    ReviewSerializer, CreateReviewSerializer, UpdateReviewSerializer, ReplyToReviewSerializer,
    NotificationSerializer,
    CreateReportSerializer, ReportSerializer,
    CreateSupportTicketSerializer, SupportTicketSerializer,
)
from .services import (
    CHAT_MESSAGE_EMPTY_ERROR,
    CHAT_WS_TICKET_MAX_AGE_SECONDS,
    create_chat_ws_ticket,
    create_notification as create_user_notification,
    decode_private_media_ticket,
    apply_wallet_delta_once,
    complete_order_with_seller_payout,
    get_seller_held_payout_summary,
    get_or_create_locked_wallet,
    is_order_in_buyer_protection_dispute_window,
    order_seller_payout_has_been_released,
    record_platform_ledger_once,
    revoke_user_refresh_tokens,
    ALLOWED_IMAGE_CONTENT_TYPES,
    decrypt_sensitive_text,
    encrypt_sensitive_text,
    validate_chat_listing_reference,
    validate_chat_message_content,
    validate_uploaded_image,
    optimize_uploaded_image,
    generate_email_change_code,
    create_email_change_token,
    verify_email_change_token,
    consume_email_change_token,
    send_email_change_code,
    send_new_email_change_code,
    generate_password_reset_code,
    create_password_reset_token,
    verify_password_reset_token,
    consume_password_reset_token,
    send_password_reset_code,
    send_topup_request_received_email,
    send_withdraw_request_received_email,
    generate_email_verification_code,
    create_email_verification_token,
    verify_email_verification_token,
    consume_email_verification_token,
    send_email_verification_code,
)
from . import jazzcash
from .payments import (
    apply_gateway_result,
    maybe_refresh_payment_status,
    start_jazzcash_payment,
)
from .storage_backends import (
    AVATAR_CACHE_SECONDS,
    GAME_ICON_CACHE_SECONDS,
    R2_SIGNED_URL_CACHE_SAFETY_SECONDS,
    R2_SIGNED_URL_MAX_SECONDS,
    cached_media_url,
    is_cloudflare_r2_name,
    media_content_type,
)
from .authentication import enforce_trusted_origin
from .permissions import (
    HasCompletedProfile,
    add_profile_setup_token_claim,
    user_needs_profile_setup,
)


def request_origin_cache_scope(request):
    return f'{request.scheme}://{request.get_host()}'


def game_list_cache_key(request):
    return f'{GAME_LIST_CACHE_KEY}:{request_origin_cache_scope(request)}'


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
DEFAULT_WITHDRAW_REQUEST_PAGE_SIZE = 20
MAX_WITHDRAW_REQUEST_PAGE_SIZE = 100


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
    if not request.user.is_authenticated:
        return False
    if request.user.id != payload['viewer_user_id']:
        return False
    return (
        payload['kind'] == kind and
        payload['object_id'] == int(object_id) and
        payload['viewer_user_id'] > 0
    )


def private_file_response(file_field, cache_seconds=0, redirect_r2=True):
    """Serve a private media file.

    Args:
        file_field: Django FieldFile / ImageFieldFile to serve.
        cache_seconds: If >0, allow the browser (but not shared proxies) to
            cache the response for this many seconds.  Default ``0`` means
            ``no-store`` (e.g. for payment proofs).
        redirect_r2: If True, R2 objects are served through signed redirects.
            Set False for stable private URLs that need browser caching without
            exposing a long-lived object-storage URL.
    """
    if not file_field:
        raise Http404
    cache_header = (
        f'private, max-age={cache_seconds}'
        if cache_seconds > 0
        else 'private, no-store'
    )
    if redirect_r2 and is_cloudflare_r2_name(file_field.name):
        signed_url_expire = min(
            settings.CLOUDFLARE_R2_PRIVATE_URL_EXPIRATION_SECONDS,
            R2_SIGNED_URL_MAX_SECONDS,
        )
        redirect_cache_seconds = 0
        if cache_seconds > 0:
            redirect_cache_seconds = max(
                0,
                min(cache_seconds, signed_url_expire - R2_SIGNED_URL_CACHE_SAFETY_SECONDS),
            )
        redirect_cache_header = (
            f'private, max-age={redirect_cache_seconds}'
            if redirect_cache_seconds > 0
            else 'private, no-store'
        )
        response_parameters = {'ResponseCacheControl': cache_header}
        content_type = media_content_type(file_field.name)
        if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
            raise Http404
        if content_type:
            response_parameters['ResponseContentType'] = content_type
        redirect_url = file_field.storage.url(
            file_field.name,
            parameters=response_parameters,
            expire=signed_url_expire,
        )
        response = HttpResponseRedirect(redirect_url)
        response['Cache-Control'] = redirect_cache_header
        response['Referrer-Policy'] = 'no-referrer'
        response['X-Content-Type-Options'] = 'nosniff'
        if redirect_cache_seconds > 0:
            patch_vary_headers(response, ['Cookie', 'Authorization'])
        return response
    content_type = media_content_type(file_field.name) or 'application/octet-stream'
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise Http404

    try:
        opened_file = file_field.open('rb')
    except (FileNotFoundError, OSError):
        raise Http404

    if is_cloudflare_r2_name(file_field.name):
        try:
            response = HttpResponse(opened_file.read(), content_type=content_type)
        finally:
            opened_file.close()
    else:
        response = FileResponse(opened_file, content_type=content_type)
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = cache_header
    response['Referrer-Policy'] = 'no-referrer'
    if cache_seconds > 0:
        patch_vary_headers(response, ['Cookie', 'Authorization'])
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


def get_before_id(request):
    try:
        before_id = int(request.query_params.get('before_id', 0))
    except (TypeError, ValueError):
        return None
    return before_id if before_id > 0 else None


def get_cursor_page(queryset, limit, before_id=None):
    if before_id:
        queryset = queryset.filter(id__lt=before_id)
    page = list(queryset.order_by('-id')[:limit + 1])
    has_more = len(page) > limit
    page = page[:limit]
    return page, {
        'count': None,
        'limit': limit,
        'next_offset': None,
        'previous_offset': None,
        'next_before_id': page[-1].id if has_more and page else None,
        'has_more': has_more,
    }


def get_released_seller_payout_order_refs(orders):
    order_refs = []
    seller_ids = set()
    for order in orders:
        if (
            order.status == 'completed'
            and order.buyer_protection_enabled
            and not order.seller_payout_released_at
        ):
            order_refs.append(f'order_{order.pk}')
            seller_ids.add(order.seller_id)

    if not order_refs:
        return set()

    return set(
        WalletTransaction.objects.filter(
            wallet__user_id__in=seller_ids,
            transaction_type='sale',
            reference_id__in=order_refs,
        ).values_list('reference_id', flat=True)
    )


def parse_query_date(value):
    if not value:
        return None
    try:
        return parse_date(value)
    except (TypeError, ValueError):
        return None


def create_notification(*, recipient, notification_type, title, message='', order=None, review=None):
    """Create a notification for a user."""
    return create_user_notification(
        recipient=recipient,
        notification_type=notification_type,
        title=title,
        message=message,
        order=order,
        review=review,
    )


# ── Public Game / Category / Filter views ────────────────────────────────────

def apply_recommended_listing_ordering(listings_qs):
    """Rank active listings with cheap signals we already have."""
    completed_order_count_subquery = (
        Order.objects.filter(listing=OuterRef('pk'), status='completed')
        .values('listing')
        .annotate(cnt=Count('id'))
        .values('cnt')[:1]
    )
    pending_report_count_subquery = (
        Report.objects.filter(
            reported_listing=OuterRef('pk'),
            target_type='listing',
            status='pending',
        )
        .values('reported_listing')
        .annotate(cnt=Count('id'))
        .values('cnt')[:1]
    )

    now = timezone.now()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    quarter_ago = now - timedelta(days=90)

    seller_rating_score = Case(
        When(seller_avg_rating__gte=Decimal('4.8'), then=Value(30)),
        When(seller_avg_rating__gte=Decimal('4.5'), then=Value(24)),
        When(seller_avg_rating__gte=Decimal('4.0'), then=Value(18)),
        When(seller_avg_rating__gte=Decimal('3.5'), then=Value(10)),
        default=Value(0),
        output_field=IntegerField(),
    )
    seller_review_score = Case(
        When(seller_review_count__gte=20, then=Value(15)),
        When(seller_review_count__gte=5, then=Value(10)),
        When(seller_review_count__gte=1, then=Value(5)),
        default=Value(0),
        output_field=IntegerField(),
    )
    completed_order_score = Case(
        When(completed_order_count__gte=20, then=Value(25)),
        When(completed_order_count__gte=5, then=Value(18)),
        When(completed_order_count__gte=1, then=Value(10)),
        default=Value(0),
        output_field=IntegerField(),
    )
    seller_status_score = Case(
        When(seller__profile__seller_status='approved', then=Value(10)),
        default=Value(0),
        output_field=IntegerField(),
    )
    fulfillment_score = Case(
        When(is_auto_delivery=True, then=Value(12)),
        When(delivery_time__in=['1-2 Hours', '1-2 hours'], then=Value(5)),
        default=Value(0),
        output_field=IntegerField(),
    )
    stock_score = Case(
        When(quantity__isnull=True, then=Value(8)),
        When(quantity__gte=5, then=Value(8)),
        When(quantity__gte=1, then=Value(5)),
        default=Value(0),
        output_field=IntegerField(),
    )
    completeness_score = Case(
        When(description='', then=Value(0)),
        default=Value(10),
        output_field=IntegerField(),
    )
    freshness_score = Case(
        When(created_at__gte=week_ago, then=Value(12)),
        When(created_at__gte=month_ago, then=Value(8)),
        When(created_at__gte=quarter_ago, then=Value(4)),
        default=Value(0),
        output_field=IntegerField(),
    )
    report_penalty = Case(
        When(pending_report_count__gt=0, then=Value(-50)),
        default=Value(0),
        output_field=IntegerField(),
    )

    recommended_score = ExpressionWrapper(
        seller_rating_score +
        seller_review_score +
        completed_order_score +
        seller_status_score +
        fulfillment_score +
        stock_score +
        completeness_score +
        freshness_score +
        report_penalty,
        output_field=IntegerField(),
    )

    return (
        listings_qs
        .annotate(
            completed_order_count=Coalesce(
                Subquery(completed_order_count_subquery),
                Value(0),
                output_field=IntegerField(),
            ),
            pending_report_count=Coalesce(
                Subquery(pending_report_count_subquery),
                Value(0),
                output_field=IntegerField(),
            ),
        )
        .annotate(recommended_score=recommended_score)
        .order_by(
            '-recommended_score',
            '-completed_order_count',
            F('seller_avg_rating').desc(nulls_last=True),
            F('seller_review_count').desc(nulls_last=True),
            '-created_at',
            '-pk',
        )
    )


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
    """GET /api/games/ — List all active games, sorted by popularity (active listing count)."""
    serializer_class = GameListSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return (
            Game.objects.filter(is_active=True)
            .prefetch_related('game_categories')
            .annotate(
                active_listing_count=Count(
                    'game_categories__listings',
                    filter=Q(game_categories__listings__status='active'),
                )
            )
            .order_by('-active_listing_count', 'order', 'name')
        )

    def list(self, request, *args, **kwargs):
        cache_key = game_list_cache_key(request)
        cached = cache.get(cache_key)
        if cached is not None:
            response = Response(cached)
        else:
            response = super().list(request, *args, **kwargs)
            cache.set(cache_key, response.data, GAME_LIST_CACHE_SECONDS)
        response['Cache-Control'] = 'public, max-age=60'
        return response


class GameDetailView(generics.RetrieveAPIView):
    """GET /api/games/{slug}/ — Game detail with its categories."""
    serializer_class = GameDetailSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = 'slug'
    queryset = Game.objects.filter(is_active=True).prefetch_related(
        'game_categories__category'
    )

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        response['Cache-Control'] = 'public, max-age=120'
        return response


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
        ).select_related('seller', 'seller__profile', 'option',
                         'game_category__game', 'game_category__category')

        # Offers mode: expose admin-defined options and scope listings to one of them
        selected_option_id = None
        if game_category.listing_mode == 'offer':
            # Per-option aggregates respect the active filter params (e.g., Region)
            # so "from" prices reflect what the buyer will actually see.
            offer_stats_q = Q(listings__status='active')
            for key, value in request.query_params.items():
                if key.startswith('filter_') and value:
                    filter_id = key.replace('filter_', '')
                    offer_stats_q &= Q(listings__filter_values__contains={filter_id: value})

            options = list(
                game_category.options.annotate(
                    min_price=Min('listings__price', filter=offer_stats_q),
                    offer_count=Count('listings', filter=offer_stats_q),
                )
            )

            requested_option = request.query_params.get('option', '').strip()
            option_ids = {opt.id for opt in options}
            try:
                requested_option_id = int(requested_option)
            except (TypeError, ValueError):
                requested_option_id = None
            if requested_option_id in option_ids:
                selected_option_id = requested_option_id
            else:
                default_option = next(
                    (opt for opt in options if opt.is_popular),
                    options[0] if options else None,
                )
                selected_option_id = default_option.id if default_option else None

            cat_data['options'] = [
                {
                    'id': opt.id,
                    'name': opt.name,
                    'order': opt.order,
                    'is_popular': opt.is_popular,
                    'icon_url': cached_media_url(
                        opt.icon,
                        request=request,
                        cache_seconds=GAME_ICON_CACHE_SECONDS,
                        cache_scope='public',
                    ) if opt.icon else None,
                    'min_price': str(opt.min_price) if opt.min_price is not None else None,
                    'offer_count': opt.offer_count,
                }
                for opt in options
            ]
            cat_data['selected_option_id'] = selected_option_id

            if selected_option_id is not None:
                listings_qs = listings_qs.filter(option_id=selected_option_id)
            else:
                listings_qs = listings_qs.none()

        # Annotate with seller rating stats (for display on listing cards)
        seller_avg_rating_subquery = (
            Review.objects.filter(seller=OuterRef('seller'))
            .values('seller')
            .annotate(avg=Avg('rating'))
            .values('avg')[:1]
        )
        seller_review_count_subquery = (
            Review.objects.filter(seller=OuterRef('seller'))
            .values('seller')
            .annotate(cnt=Count('id'))
            .values('cnt')[:1]
        )
        listings_qs = listings_qs.annotate(
            seller_avg_rating=Subquery(seller_avg_rating_subquery),
            seller_review_count=Subquery(seller_review_count_subquery),
        )

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

        # Online seller filter: only show listings from sellers who are currently online
        if request.query_params.get('online_only') == 'true':
            online_threshold = timezone.now() - timedelta(seconds=120)
            listings_qs = listings_qs.filter(seller__profile__last_active__gte=online_threshold)

        # Search filter: filter by title
        search_q = request.query_params.get('search', '').strip()
        if search_q:
            listings_qs = listings_qs.filter(title__icontains=search_q)

        # Seller filter: only show listings from a specific seller
        seller_username = request.query_params.get('seller', '').strip()
        if seller_username:
            listings_qs = listings_qs.filter(seller__username=seller_username)

        # Sorting / Ordering
        delivery_speed_rank = Case(
            When(delivery_time='Instant', then=Value(0)),
            When(delivery_time='1-2 Hours', then=Value(1)),
            When(delivery_time='2-6 Hours', then=Value(2)),
            When(delivery_time='6-12 Hours', then=Value(3)),
            When(delivery_time='12-24 Hours', then=Value(4)),
            When(delivery_time='1-3 Days', then=Value(5)),
            default=Value(6),
            output_field=IntegerField(),
        )
        ALLOWED_ORDERINGS = {
            'price_asc': (F('price').asc(), F('created_at').desc()),
            'price_desc': (F('price').desc(), F('created_at').desc()),
            'newest': (F('created_at').desc(),),
            'rating': (F('seller_avg_rating').desc(nulls_last=True), F('created_at').desc()),
            'delivery': (F('delivery_speed_rank').asc(), F('price').asc()),
        }
        ordering_param = request.query_params.get('ordering', '').strip()
        if ordering_param in ALLOWED_ORDERINGS:
            listings_qs = listings_qs.annotate(delivery_speed_rank=delivery_speed_rank)
            listings_qs = listings_qs.order_by(*ALLOWED_ORDERINGS[ordering_param])
        elif game_category.listing_mode == 'offer':
            # Best offer first: cheapest, fastest delivery as tiebreaker
            listings_qs = listings_qs.annotate(delivery_speed_rank=delivery_speed_rank)
            listings_qs = listings_qs.order_by('price', 'delivery_speed_rank', '-created_at')
        else:
            listings_qs = apply_recommended_listing_ordering(listings_qs)

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



        listing_count_filter = Q(listings__status='active')
        if seller_username:
            listing_count_filter &= Q(listings__seller__username=seller_username)

        sibling_gcs = sibling_gcs.annotate(
            listing_count=Count(
                'listings',
                filter=listing_count_filter,
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
        try:
            response = super().post(request, *args, **kwargs)
        except Exception as exc:
            # Check if this is an inactive (unverified) user
            from rest_framework.exceptions import AuthenticationFailed
            if isinstance(exc, (AuthenticationFailed, InvalidToken)):
                email = request.data.get('email', '').strip()
                if email:
                    from django.contrib.auth.hashers import check_password
                    try:
                        user = User.objects.select_related('profile').get(email__iexact=email)
                        if (
                            not user.is_active and
                            user.profile.email_verification_pending and
                            user.has_usable_password() and
                            check_password(request.data.get('password', ''), user.password)
                        ):
                            return Response(
                                {'detail': 'Please verify your email address before signing in.',
                                 'email_unverified': True},
                                status=status.HTTP_403_FORBIDDEN,
                            )
                    except User.DoesNotExist:
                        pass
            raise

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
    """POST /api/auth/register/ — Register a new user (inactive until email verified)."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer
    throttle_scope = 'auth_register'

    def create(self, request, *args, **kwargs):
        enforce_trusted_origin(request)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Send verification email
        code = generate_email_verification_code()
        token = create_email_verification_token(user.pk, code)
        send_email_verification_code(user.email, user.username, code)

        return Response({
            'message': 'Account created. Please check your email for a verification code.',
            'verification_token': token,
        }, status=status.HTTP_201_CREATED)


class VerifyEmailView(ScopedPostThrottleMixin, APIView):
    """POST /api/auth/verify-email/ — Verify email with 6-digit code."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'email_verify'

    def post(self, request):
        enforce_trusted_origin(request)
        token = request.data.get('token', '').strip()
        code = request.data.get('code', '').strip()

        if not token or not code:
            return Response(
                {'error': 'Verification token and code are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = verify_email_verification_token(token, code)
        if not payload:
            return Response(
                {'error': 'Invalid or expired verification code. Please request a new one.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with db_transaction.atomic():
                user = User.objects.select_for_update().get(pk=payload['user_id'])
                profile = UserProfile.objects.select_for_update().get(user=user)

                if user.is_active:
                    if profile.email_verification_pending:
                        profile.email_verification_pending = False
                        profile.save(update_fields=['email_verification_pending'])
                    consume_email_verification_token(token)
                    return Response({'message': 'Email already verified. You can sign in.'})

                if not profile.email_verification_pending:
                    consume_email_verification_token(token)
                    return Response(
                        {'error': 'Invalid or expired verification code. Please request a new one.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                user.is_active = True
                user.save(update_fields=['is_active'])
                profile.email_verification_pending = False
                profile.save(update_fields=['email_verification_pending'])
        except (User.DoesNotExist, UserProfile.DoesNotExist):
            consume_email_verification_token(token)
            return Response({'error': 'Invalid token.'}, status=status.HTTP_400_BAD_REQUEST)

        consume_email_verification_token(token)

        return Response({'message': 'Email verified successfully! You can now sign in.'})


class ResendVerificationView(ScopedPostThrottleMixin, APIView):
    """POST /api/auth/resend-verification/ — Resend email verification code."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'email_resend'

    def post(self, request):
        enforce_trusted_origin(request)
        email = request.data.get('email', '').strip()
        if not email:
            return Response({'error': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Always return the same shape to prevent user enumeration.
        try:
            user = User.objects.get(
                email__iexact=email,
                is_active=False,
                profile__email_verification_pending=True,
            )
        except User.DoesNotExist:
            # Return a dummy token so the shape is identical
            import secrets as _secrets
            return Response({
                'message': 'If that email has a pending account, a new verification code has been sent.',
                'verification_token': _secrets.token_urlsafe(32),
            })

        code = generate_email_verification_code()
        token = create_email_verification_token(user.pk, code)
        send_email_verification_code(user.email, user.username, code)

        return Response({
            'message': 'If that email has a pending account, a new verification code has been sent.',
            'verification_token': token,
        })


class GoogleAuthLinkError(Exception):
    pass


class GoogleAuthView(ScopedPostThrottleMixin, APIView):
    """POST /api/auth/google/ — Authenticate via Google ID token.

    Accepts { "credential": "<google_id_token>" }.
    Verifies the token with Google, finds or creates the local user,
    and returns JWT cookies identical to the normal login flow.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'auth_login'

    def post(self, request):
        import re
        import secrets as _secrets
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests

        enforce_trusted_origin(request)

        credential = request.data.get('credential', '')
        if not isinstance(credential, str):
            return Response(
                {'error': 'Google credential must be a string.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        credential = credential.strip()
        if not credential:
            return Response(
                {'error': 'Google credential is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        client_id = settings.GOOGLE_OAUTH_CLIENT_ID
        if not client_id:
            return Response(
                {'error': 'Google authentication is not configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            idinfo = google_id_token.verify_oauth2_token(
                credential,
                google_requests.Request(),
                client_id,
                clock_skew_in_seconds=300,
            )
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning('Google token verification failed: %s', exc)
            error_detail = 'Invalid Google credential.'
            if settings.DEBUG:
                error_detail = f'Invalid Google credential: {exc}'
            return Response(
                {'error': error_detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

        google_email = idinfo.get('email', '').strip().lower()
        if not google_email or not idinfo.get('email_verified'):
            return Response(
                {'error': 'Google account email is not verified.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        google_sub = idinfo.get('sub', '')
        if not isinstance(google_sub, str) or not google_sub.strip():
            return Response(
                {'error': 'Google credential is missing an account identifier.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        google_sub = google_sub.strip()

        try:
            user = self._get_or_create_google_user(
                google_sub=google_sub,
                google_email=google_email,
                google_name=idinfo.get('name', '').strip(),
                re_module=re,
                secrets_module=_secrets,
            )
        except GoogleAuthLinkError as exc:
            return Response(
                {'error': str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        except IntegrityError:
            existing_account = SocialAccount.objects.select_related('user').filter(
                provider=SocialAccount.PROVIDER_GOOGLE,
                uid=google_sub,
            ).first()
            if existing_account is None:
                raise
            user = existing_account.user

        if not user.is_active:
            return Response(
                {'error': 'This account has been deactivated.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Issue JWT cookies
        from rest_framework_simplejwt.tokens import RefreshToken
        needs_setup = user_needs_profile_setup(user)
        refresh = add_profile_setup_token_claim(
            RefreshToken.for_user(user),
            user,
            needs_setup=needs_setup,
        )
        response_data = {'message': 'Logged in with Google.'}

        # Check if the user still needs to set up their profile
        if needs_setup:
            response_data['needs_setup'] = True

        response = Response(response_data)
        set_jwt_auth_cookies(
            response,
            access=str(refresh.access_token),
            refresh=str(refresh),
        )
        return response

    @classmethod
    def _get_or_create_google_user(
        cls,
        *,
        google_sub,
        google_email,
        google_name,
        re_module,
        secrets_module,
    ):
        with db_transaction.atomic():
            social_account = (
                SocialAccount.objects.select_for_update()
                .select_related('user')
                .filter(provider=SocialAccount.PROVIDER_GOOGLE, uid=google_sub)
                .first()
            )
            if social_account:
                if social_account.email != google_email:
                    social_account.email = google_email
                    social_account.save(update_fields=['email', 'updated_at'])
                return cls._claim_pending_google_registration(social_account.user)

            matching_users = list(
                User.objects.select_for_update()
                .filter(email__iexact=google_email)
                .order_by('id')[:2]
            )
            if len(matching_users) > 1:
                raise GoogleAuthLinkError(
                    'More than one account uses this email. Please sign in with your password or contact support.'
                )

            if matching_users:
                user = cls._claim_pending_google_registration(matching_users[0])
            else:
                user = cls._create_google_user(
                    google_email=google_email,
                    google_name=google_name,
                    re_module=re_module,
                    secrets_module=secrets_module,
                )

            SocialAccount.objects.create(
                user=user,
                provider=SocialAccount.PROVIDER_GOOGLE,
                uid=google_sub,
                email=google_email,
            )
            return user

    @staticmethod
    def _claim_pending_google_registration(user):
        """Safely reclaim an unverified email signup proven by Google ownership."""
        user = User.objects.select_for_update().get(pk=user.pk)
        if user.is_active:
            return user

        try:
            profile = UserProfile.objects.select_for_update().get(user=user)
        except UserProfile.DoesNotExist:
            return user
        if not profile.email_verification_pending:
            return user

        # The unverified password and consent may have been supplied by a third
        # party. Keep neither after Google proves control of the email address.
        user.set_unusable_password()
        user.is_active = True
        user.save(update_fields=['password', 'is_active'])
        profile.email_verification_pending = False
        profile.has_accepted_terms = False
        profile.save(update_fields=['email_verification_pending', 'has_accepted_terms'])
        return user

    @staticmethod
    def _create_google_user(*, google_email, google_name, re_module, secrets_module):
        base_name = google_name or google_email.split('@')[0]
        base_username = re_module.sub(r'[^a-zA-Z0-9_]', '', base_name.replace(' ', '_'))
        if not base_username:
            base_username = 'user'
        base_username = base_username[:20]

        for _ in range(10):
            username = base_username
            while User.objects.filter(username__iexact=username).exists():
                username = f'{base_username}_{secrets_module.token_hex(3)}'
            try:
                with db_transaction.atomic():
                    return User.objects.create_user(
                        username=username,
                        email=google_email,
                        password=None,
                    )
            except IntegrityError:
                continue

        raise IntegrityError('Could not create a unique username for Google sign-in.')


class CompleteProfileView(ScopedPostThrottleMixin, APIView):
    """POST /api/auth/complete-profile/ — Set username and accept terms (Google sign-up)."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'complete_profile'

    def post(self, request):
        if not request.user.social_accounts.filter(
            provider=SocialAccount.PROVIDER_GOOGLE,
        ).exists():
            return Response(
                {'error': 'Profile setup is only available for Google sign-ups.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            with db_transaction.atomic():
                profile = UserProfile.objects.select_for_update().get(user=request.user)
                if profile.has_accepted_terms:
                    return Response(
                        {'error': 'Profile setup already completed.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                serializer = CompleteProfileSerializer(
                    data=request.data,
                    context={'user': request.user, 'profile': profile},
                )
                serializer.is_valid(raise_exception=True)

                new_username = serializer.validated_data['username']
                update_fields = ['has_accepted_terms']
                if new_username != request.user.username:
                    request.user.username = new_username
                    request.user.save(update_fields=['username'])
                    profile.username_changed_at = timezone.now()
                    update_fields.append('username_changed_at')
                profile.has_accepted_terms = True
                profile.save(update_fields=update_fields)
        except IntegrityError:
            return Response(
                {'username': ['This username is already taken.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.select_related('profile').get(pk=request.user.pk)
        response = Response({
            'message': 'Profile setup completed.',
            'user': UserSerializer(user, context={'request': request}).data,
        })
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = add_profile_setup_token_claim(RefreshToken.for_user(user), user)
        set_jwt_auth_cookies(
            response,
            access=str(refresh.access_token),
            refresh=str(refresh),
        )
        return response


class RequestPasswordResetView(ScopedPostThrottleMixin, APIView):
    """POST /api/auth/password/reset-request/ — Send reset code to email."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'password_reset_request'

    def post(self, request):
        enforce_trusted_origin(request)
        email = request.data.get('email', '').strip()
        if not email:
            return Response({'error': 'Email is required.'}, status=400)

        # Always return the same shape to prevent user enumeration.
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            token = create_password_reset_token()
        else:
            code = generate_password_reset_code()
            token = create_password_reset_token(user.pk, code)
            send_password_reset_code(user, code)

        return Response({
            'message': 'If that email exists, a reset code has been sent.',
            'token': token,
        })


class ConfirmPasswordResetView(ScopedPostThrottleMixin, APIView):
    """POST /api/auth/password/reset-confirm/ — Verify code and set new password."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'password_reset_confirm'

    def post(self, request):
        enforce_trusted_origin(request)
        token = request.data.get('token', '')
        code = request.data.get('code', '')
        new_password = request.data.get('new_password', '')
        new_password2 = request.data.get('new_password2', '')

        if not all([token, code, new_password, new_password2]):
            return Response({'error': 'All fields are required.'}, status=400)

        if new_password != new_password2:
            return Response({'error': 'Passwords do not match.'}, status=400)

        payload = verify_password_reset_token(token, code)
        if not payload:
            return Response({'error': 'Reset code is invalid or expired. Please request a new one.'}, status=400)

        try:
            user = User.objects.get(pk=payload['user_id'])
        except User.DoesNotExist:
            consume_password_reset_token(token)
            return Response({'error': 'Invalid token.'}, status=400)

        if user.check_password(new_password):
            return Response(
                {'error': 'New password must be different from your current password.'},
                status=400,
            )

        # Validate password strength
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            return Response({'error': exc.messages[0]}, status=400)

        user.set_password(new_password)
        user.save()
        revoke_user_refresh_tokens(user)
        consume_password_reset_token(token)

        return Response({'message': 'Password reset successfully. You can now sign in.'})


class MeView(APIView):
    """GET /api/auth/me/ — Get current user info."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if not request.user.is_authenticated:
            if request.COOKIES.get(settings.JWT_AUTH_COOKIE_REFRESH):
                return Response(
                    {'detail': 'Authentication credentials were not provided.'},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(UserSerializer(request.user, context={'request': request}).data)


class UpdateProfileView(APIView):
    """PUT /api/auth/profile/ — Update username (90-day cooldown enforced)."""
    permission_classes = [HasCompletedProfile]

    def put(self, request):
        try:
            with db_transaction.atomic():
                user = request.user
                profile = UserProfile.objects.select_for_update().get(user=user)
                serializer = UpdateProfileSerializer(
                    data=request.data,
                    context={'user': user, 'profile': profile},
                )
                serializer.is_valid(raise_exception=True)

                new_username = serializer.validated_data['username']
                if new_username != user.username:
                    user.username = new_username
                    user.save(update_fields=['username'])
                    profile.username_changed_at = timezone.now()
                    profile.save(update_fields=['username_changed_at'])
        except IntegrityError:
            return Response(
                {'username': ['This username is already taken.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.select_related('profile').get(pk=request.user.pk)

        return Response({
            'message': 'Profile updated.',
            'user': UserSerializer(user, context={'request': request}).data,
        })


class RequestEmailChangeView(ScopedPostThrottleMixin, APIView):
    """POST /api/auth/email/request-change/ — Send verification codes to both emails."""
    permission_classes = [HasCompletedProfile]
    throttle_scope = 'email_change_request'

    def post(self, request):
        from .serializers import RequestEmailChangeSerializer
        serializer = RequestEmailChangeSerializer(
            data=request.data,
            context={'user': request.user},
        )
        serializer.is_valid(raise_exception=True)

        new_email = serializer.validated_data['new_email']
        current_code = generate_email_change_code()
        new_code = generate_email_change_code()
        while new_code == current_code:
            new_code = generate_email_change_code()
        token = create_email_change_token(request.user.pk, current_code, new_email, new_code)

        send_email_change_code(request.user, current_code)
        send_new_email_change_code(request.user, new_email, new_code)

        return Response({
            'message': 'Verification codes sent to your current and new email addresses.',
            'token': token,
        })


class ConfirmEmailChangeView(ScopedPostThrottleMixin, APIView):
    """POST /api/auth/email/confirm-change/ — Verify code and update email."""
    permission_classes = [HasCompletedProfile]
    throttle_scope = 'email_change_confirm'

    def post(self, request):
        from .serializers import ConfirmEmailChangeSerializer
        serializer = ConfirmEmailChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data['token']
        current_code = serializer.validated_data['current_code']
        new_code = serializer.validated_data['new_code']

        payload = verify_email_change_token(token, current_code, new_code)
        if not payload:
            return Response(
                {'error': 'Verification codes are invalid or expired. Please request new ones.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if payload['user_id'] != request.user.pk:
            return Response({'error': 'Invalid token.'}, status=400)

        new_email = payload['new_email']

        # Double-check uniqueness at confirmation time
        if User.objects.filter(email__iexact=new_email).exclude(pk=request.user.pk).exists():
            return Response(
                {'error': 'This email is already taken by another user.'},
                status=400,
            )

        request.user.email = new_email
        try:
            with db_transaction.atomic():
                request.user.save(update_fields=['email'])
        except IntegrityError:
            return Response(
                {'error': 'This email is already taken by another user.'},
                status=400,
            )
        consume_email_change_token(token)

        return Response({
            'message': 'Email updated successfully.',
            'user': UserSerializer(request.user, context={'request': request}).data,
        })


class ChangePasswordView(ScopedPostThrottleMixin, APIView):
    """POST /api/auth/password/ — Change password."""
    permission_classes = [HasCompletedProfile]
    throttle_scope = 'password_change'

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'user': request.user},
        )
        serializer.is_valid(raise_exception=True)

        user = request.user
        if not user.check_password(serializer.validated_data['current_password']):
            return Response(
                {'error': 'Current password is incorrect.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if user.check_password(serializer.validated_data['new_password']):
            return Response(
                {'error': 'New password must be different from your current password.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(serializer.validated_data['new_password'])
        user.save()
        revoke_user_refresh_tokens(user)

        # Re-issue JWT cookies so the session stays valid
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = add_profile_setup_token_claim(RefreshToken.for_user(user), user)
        response = Response({'message': 'Password changed successfully.'})
        set_jwt_auth_cookies(
            response,
            access=str(refresh.access_token),
            refresh=str(refresh),
        )
        return response


class AvatarUploadView(ScopedPostThrottleMixin, APIView):
    """POST /api/auth/avatar/ — Upload profile picture.
       DELETE /api/auth/avatar/ — Remove profile picture.
    """
    permission_classes = [HasCompletedProfile]
    throttle_scope = 'avatar_upload'

    def post(self, request):
        image = request.FILES.get('avatar')
        if not image:
            return Response({'error': 'No image provided.'}, status=400)

        error = validate_uploaded_image(image)
        if error:
            return Response({'error': error}, status=400)

        image = optimize_uploaded_image(image, preset='avatar')

        profile = request.user.profile
        # Delete old avatar file if exists
        if profile.avatar:
            profile.avatar.delete(save=False)
        profile.avatar = image
        profile.save(update_fields=['avatar'])

        return Response({
            'message': 'Avatar updated.',
            'user': UserSerializer(request.user, context={'request': request}).data,
        })

    def delete(self, request):
        profile = request.user.profile
        if profile.avatar:
            profile.avatar.delete(save=False)
            profile.avatar = None
            profile.save(update_fields=['avatar'])
        return Response({'message': 'Avatar removed.', 'user': UserSerializer(request.user, context={'request': request}).data})


# ── Seller views ─────────────────────────────────────────────────────────────

class SellerApplyView(ScopedPostThrottleMixin, APIView):
    """POST /api/seller/apply/ — Submit a seller application."""
    permission_classes = [HasCompletedProfile]
    throttle_scope = 'seller_apply'

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
    permission_classes = [HasCompletedProfile]

    def get(self, request):
        profile = request.user.profile
        return Response({
            'seller_status': profile.seller_status,
            'is_seller': profile.is_seller,
            'application_note': profile.seller_application_note,
        })


# ── Listing views ────────────────────────────────────────────────────────────

class ListingCreateView(ScopedPostThrottleMixin, generics.CreateAPIView):
    """POST /api/listings/ — Create a listing (sellers only)."""
    serializer_class = CreateListingSerializer
    permission_classes = [HasCompletedProfile]
    throttle_scope = 'listing_create'

    def perform_create(self, serializer):
        if not self.request.user.profile.is_seller:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You must be an approved seller to create listings.')
        serializer.save()


class MyListingsView(generics.ListAPIView):
    """GET /api/listings/mine/ — Get current user's listings."""
    serializer_class = ListingSerializer
    permission_classes = [HasCompletedProfile]

    def get_queryset(self):
        return Listing.objects.filter(
            seller=self.request.user
        ).select_related('seller', 'seller__profile', 'option',
                         'game_category__game', 'game_category__category')

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


class ListingDetailView(ScopedPostThrottleMixin, APIView):
    """GET /api/listings/{id}/ — Get listing detail.
    PUT /api/listings/{id}/ — Edit listing (owner only).
    DELETE /api/listings/{id}/ — Delete listing (owner only).
    """
    throttle_methods = {'PUT', 'DELETE'}
    throttle_scope = 'listing_mutation'

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [HasCompletedProfile()]

    def get(self, request, pk):
        listings_qs = Listing.objects.select_related(
            'seller', 'seller__profile', 'option',
            'game_category__game', 'game_category__category'
        )
        if request.user.is_authenticated:
            if not request.user.is_staff:
                listings_qs = listings_qs.filter(
                    Q(status='active') | Q(seller=request.user)
                )
        else:
            listings_qs = listings_qs.filter(status='active')

        listing = get_object_or_404(
            listings_qs,
            pk=pk,
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


class AutoDeliveryRestockView(ScopedPostThrottleMixin, APIView):
    """POST /api/listings/{id}/restock/ - Append automated delivery stock."""
    permission_classes = [HasCompletedProfile]
    throttle_scope = 'listing_restock'

    def post(self, request, pk):
        serializer = AutoDeliveryRestockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with db_transaction.atomic():
            listing = get_object_or_404(
                Listing.objects.select_for_update().select_related(
                    'seller', 'game_category__game', 'game_category__category'
                ),
                pk=pk,
                seller=request.user,
            )
            if not listing.is_auto_delivery:
                return Response(
                    {'error': 'Only automated delivery listings can be restocked here.'},
                    status=400,
                )

            existing_lines = get_auto_delivery_inventory_lines(
                decrypt_sensitive_text(listing.auto_delivery_data)
            )
            new_lines = serializer.validated_data['auto_delivery_data']
            combined_lines = existing_lines + new_lines
            if len(combined_lines) > MAX_AUTO_DELIVERY_LINES:
                return Response({
                    'auto_delivery_data': (
                        f'Automated delivery inventory cannot exceed {MAX_AUTO_DELIVERY_LINES} items.'
                    ),
                }, status=400)

            listing.auto_delivery_data = encrypt_sensitive_text('\n'.join(combined_lines))
            listing.quantity = len(combined_lines)
            listing.delivery_time = 'Instant'
            update_fields = ['auto_delivery_data', 'quantity', 'delivery_time', 'updated_at']
            if serializer.validated_data['activate']:
                if (
                    listing.option_id and listing.status != 'active' and
                    Listing.objects.filter(
                        seller=request.user,
                        option_id=listing.option_id,
                        status='active',
                    ).exclude(pk=listing.pk).exists()
                ):
                    return Response({
                        'error': 'You already have an active offer for this option. '
                                 'Deactivate it first or edit it instead.',
                    }, status=400)
                listing.status = 'active'
                update_fields.append('status')
            listing.save(update_fields=update_fields)

        return Response(ListingSerializer(
            listing,
            context={
                'request': request,
                'filter_option_display_map': build_listing_filter_display_map([listing]),
            },
        ).data)


class AutoDeliveryStockView(ScopedPostThrottleMixin, APIView):
    """GET  /api/listings/{id}/stock/ — View current auto delivery stock items.
    PUT   /api/listings/{id}/stock/ — Update specific items by index.
    DELETE /api/listings/{id}/stock/ — Remove items by index.
    """
    permission_classes = [HasCompletedProfile]
    throttle_methods = {'PUT', 'DELETE'}
    throttle_scope = 'listing_restock'

    def _get_listing(self, request, pk, *, lock=False):
        qs = Listing.objects.select_related(
            'seller', 'game_category__game', 'game_category__category'
        )
        if lock:
            qs = qs.select_for_update()
        listing = get_object_or_404(qs, pk=pk, seller=request.user)
        if not listing.is_auto_delivery:
            return None, Response(
                {'error': 'This is not an automated delivery listing.'},
                status=400,
            )
        return listing, None

    @staticmethod
    def _mask_item(item):
        """Mask an item for display, showing first/last characters for identification."""
        text = item.strip()
        length = len(text)
        if length <= 4:
            return '*' * length
        if length <= 8:
            return text[0] + '*' * (length - 2) + text[-1]
        # Show first 3 and last 2 characters
        return text[:3] + '*' * min(length - 5, 10) + text[-2:]

    def get(self, request, pk):
        listing, error_response = self._get_listing(request, pk)
        if error_response:
            return error_response

        items = get_auto_delivery_inventory_lines(
            decrypt_sensitive_text(listing.auto_delivery_data)
        )

        # If ?view=<index> is provided, return the full content of that item
        view_index = request.query_params.get('view')
        if view_index is not None:
            try:
                idx = int(view_index)
            except (TypeError, ValueError):
                return Response({'error': 'Invalid item index.'}, status=400)
            if idx < 0 or idx >= len(items):
                return Response(
                    {'error': f'Invalid item index: {idx}. Must be 0-{len(items) - 1}.'},
                    status=400,
                )
            return Response({
                'index': idx,
                'content': items[idx],
                'length': len(items[idx]),
            })

        stock_items = [
            {
                'index': i,
                'preview': self._mask_item(item),
                'length': len(item),
            }
            for i, item in enumerate(items)
        ]
        return Response({
            'listing_id': listing.id,
            'listing_title': listing.title,
            'total_items': len(items),
            'items': stock_items,
        })

    def put(self, request, pk):
        """Update specific items by index.
        Body: { "updates": [{"index": 0, "content": "new-code-here"}, ...] }
        """
        updates = request.data.get('updates')
        if not isinstance(updates, list) or not updates:
            return Response(
                {'error': 'Provide a list of updates with index and content.'},
                status=400,
            )
        if len(updates) > 100:
            return Response(
                {'error': 'Cannot update more than 100 items at once.'},
                status=400,
            )

        with db_transaction.atomic():
            listing, error_response = self._get_listing(request, pk, lock=True)
            if error_response:
                return error_response

            items = get_auto_delivery_inventory_lines(
                decrypt_sensitive_text(listing.auto_delivery_data)
            )
            total = len(items)

            for update in updates:
                if not isinstance(update, dict):
                    return Response(
                        {'error': 'Each update must be an object with index and content.'},
                        status=400,
                    )
                idx = update.get('index')
                raw_content = update.get('content', '')
                if not isinstance(idx, int) or idx < 0 or idx >= total:
                    return Response(
                        {'error': f'Invalid item index: {idx}. Must be 0-{total - 1}.'},
                        status=400,
                    )
                content = '' if raw_content is None else str(raw_content)
                if not content.strip():
                    return Response(
                        {'error': f'Item content at index {idx} cannot be empty. Use the delete endpoint to remove items.'},
                        status=400,
                    )
                if len(content) > MAX_AUTO_DELIVERY_LINE_LENGTH:
                    return Response(
                        {'error': f'Item content too long at index {idx}.'},
                        status=400,
                    )
                items[idx] = content

            listing.auto_delivery_data = encrypt_sensitive_text('\n'.join(items))
            listing.quantity = len(items)
            listing.save(update_fields=['auto_delivery_data', 'quantity', 'updated_at'])

        return Response({
            'message': f'Updated {len(updates)} item(s).',
            'total_items': len(items),
            'listing': ListingSerializer(
                listing,
                context={
                    'request': request,
                    'filter_option_display_map': build_listing_filter_display_map([listing]),
                },
            ).data,
        })

    def delete(self, request, pk):
        """Remove items by index.
        Body: { "indices": [0, 3, 5] }
        """
        indices = request.data.get('indices')
        if not isinstance(indices, list) or not indices:
            return Response(
                {'error': 'Provide a list of item indices to remove.'},
                status=400,
            )

        with db_transaction.atomic():
            listing, error_response = self._get_listing(request, pk, lock=True)
            if error_response:
                return error_response

            items = get_auto_delivery_inventory_lines(
                decrypt_sensitive_text(listing.auto_delivery_data)
            )
            total = len(items)

            # Validate all indices first
            seen = set()
            for idx in indices:
                if not isinstance(idx, int) or idx < 0 or idx >= total:
                    return Response(
                        {'error': f'Invalid item index: {idx}. Must be 0-{total - 1}.'},
                        status=400,
                    )
                if idx in seen:
                    return Response(
                        {'error': f'Duplicate index: {idx}.'},
                        status=400,
                    )
                seen.add(idx)

            if len(seen) >= total:
                return Response(
                    {'error': 'Cannot remove all items. Delete the listing instead, or leave at least one item.'},
                    status=400,
                )

            # Remove items (highest indices first so earlier indices stay valid)
            remaining_items = [item for i, item in enumerate(items) if i not in seen]

            listing.auto_delivery_data = encrypt_sensitive_text('\n'.join(remaining_items))
            listing.quantity = len(remaining_items)
            update_fields = ['auto_delivery_data', 'quantity', 'updated_at']
            if listing.quantity == 0 and listing.status == 'active':
                listing.status = 'sold'
                update_fields.append('status')
            listing.save(update_fields=update_fields)

        return Response({
            'message': f'Removed {len(seen)} item(s). {len(remaining_items)} remaining.',
            'total_items': len(remaining_items),
            'listing': ListingSerializer(
                listing,
                context={
                    'request': request,
                    'filter_option_display_map': build_listing_filter_display_map([listing]),
                },
            ).data,
        })


class ConversationListView(APIView):
    """GET /api/chat/ — List all conversations for current user."""
    permission_classes = [HasCompletedProfile]

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


class StartConversationView(ScopedPostThrottleMixin, APIView):
    """POST /api/chat/start/ — Find or create a conversation with a user.
    Body: {"user_id": 5, "message": "Hi, is this still available?"}
    """
    permission_classes = [HasCompletedProfile]
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
        referenced_listing, listing_error = validate_chat_listing_reference(
            request.data.get('listing_id'),
            seller_id=other_user.id,
        )
        if listing_error:
            return Response({'error': listing_error}, status=400)

        conversation, _ = get_or_create_private_conversation(request.user, other_user)

        # Send initial message if provided
        if initial_message:
            message = Message.objects.create(
                conversation=conversation,
                sender=request.user,
                content=initial_message,
                referenced_listing=referenced_listing,
                referenced_listing_title=referenced_listing.title if referenced_listing else '',
                referenced_listing_price=referenced_listing.price if referenced_listing else None,
            )
            conversation.save()  # Update updated_at
            broadcast_chat_message(message, request)

        data = ConversationDetailSerializer(conversation, context={'request': request}).data
        return Response(data, status=201)


class ConversationDetailView(APIView):
    """GET /api/chat/{id}/ — Get conversation with messages."""
    permission_classes = [HasCompletedProfile]

    def get(self, request, pk):
        conversation = get_object_or_404(
            Conversation.objects.prefetch_related(
                Prefetch('participants', queryset=User.objects.select_related('profile')),
            ),
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
        messages_qs = conversation.messages.select_related(
            'sender', 'referenced_listing'
        ).order_by('-pk')
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
    permission_classes = [HasCompletedProfile]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'chat_ws_ticket'

    def post(self, request, pk):
        conversation = get_object_or_404(Conversation, pk=pk, participants=request.user)
        return Response({
            'ticket': create_chat_ws_ticket(request.user, conversation.pk),
            'expires_in': CHAT_WS_TICKET_MAX_AGE_SECONDS,
        })


class SendMessageView(ScopedPostThrottleMixin, APIView):
    """POST /api/chat/{id}/send/ — Send a message in a conversation."""
    permission_classes = [HasCompletedProfile]
    throttle_scope = 'chat_message'

    def post(self, request, pk):
        conversation = get_object_or_404(
            Conversation, pk=pk, participants=request.user
        )

        content, validation_error = validate_chat_message_content(request.data.get('content', ''))
        if validation_error:
            return Response({'error': validation_error}, status=400)
        referenced_listing, listing_error = validate_chat_listing_reference(
            request.data.get('listing_id'),
            conversation_id=conversation.id,
        )
        if listing_error:
            return Response({'error': listing_error}, status=400)

        message = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            content=content,
            referenced_listing=referenced_listing,
            referenced_listing_title=referenced_listing.title if referenced_listing else '',
            referenced_listing_price=referenced_listing.price if referenced_listing else None,
        )
        conversation.save()  # Update updated_at

        data = broadcast_chat_message(message, request)
        return Response(data, status=201)


class SendImageView(ScopedPostThrottleMixin, APIView):
    """POST /api/chat/{id}/send-image/ — Send an image message."""
    permission_classes = [HasCompletedProfile]
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
        image = optimize_uploaded_image(image, preset='chat')

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
        return private_file_response(message.image, cache_seconds=86400, redirect_r2=False)


class UnreadCountView(APIView):
    """GET /api/chat/unread/ — Count of conversations with unread messages."""
    permission_classes = [HasCompletedProfile]

    def get(self, request):
        cache_key = f'chat-unread:v1:{request.user.pk}'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response({'unread_count': cached})
        count = Message.objects.filter(
            conversation__participants=request.user,
            is_read=False,
        ).exclude(sender=request.user).values(
            'conversation'
        ).distinct().count()
        cache.set(cache_key, count, UNREAD_COUNT_CACHE_SECONDS)
        return Response({'unread_count': count})


class HeartbeatView(ScopedPostThrottleMixin, APIView):
    """POST /api/heartbeat/ — Update user's last_active timestamp."""
    permission_classes = [HasCompletedProfile]
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
    permission_classes = [HasCompletedProfile]

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
        held_summary = get_seller_held_payout_summary(request.user)
        return Response({
            'balance': str(wallet.balance),
            'held_balance': str(held_summary['held_balance']),
            'held_order_count': held_summary['held_order_count'],
            'next_payout_release_at': held_summary['next_release_at'],
            'jazzcash_enabled': settings.JAZZCASH_ENABLED,
            'transactions': WalletTransactionSerializer(transactions, many=True).data,
            'transaction_pagination': get_pagination_payload(total_count, limit, offset),
        })


class WalletTransactionsView(APIView):
    """GET /api/wallet/transactions/ — Full transaction history."""
    permission_classes = [HasCompletedProfile]

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


class HeldOrdersView(APIView):
    """GET /api/wallet/held-orders/ — List orders with buyer protection holds."""
    permission_classes = [HasCompletedProfile]

    def get(self, request):
        held_orders_qs = Order.objects.filter(
            seller=request.user,
            status='completed',
            buyer_protection_enabled=True,
            seller_payout_released_at__isnull=True,
        ).select_related('buyer').order_by('-created_at')

        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_ORDER_PAGE_SIZE,
            max_limit=MAX_ORDER_PAGE_SIZE,
        )
        total_count = held_orders_qs.count()
        held_orders = held_orders_qs[offset:offset + limit]

        now = timezone.now()
        orders_data = []
        total_held = Decimal('0.00')
        for order in held_orders:
            days_until_release = None
            if order.seller_payout_available_at:
                delta = order.seller_payout_available_at - now
                days_until_release = max(0, delta.days + (1 if delta.seconds > 0 else 0))

            total_held += order.seller_amount or Decimal('0.00')
            orders_data.append({
                'id': order.id,
                'order_number': order.order_number,
                'listing_title': order.listing_title,
                'buyer_name': order.buyer.username,
                'quantity': order.quantity,
                'total_amount': str(order.total_amount),
                'seller_amount': str(order.seller_amount),
                'commission_amount': str(order.commission_amount),
                'seller_payout_available_at': order.seller_payout_available_at,
                'days_until_release': days_until_release,
                'created_at': order.created_at,
            })

        held_summary = get_seller_held_payout_summary(request.user)
        return Response({
            'held_balance': str(held_summary['held_balance']),
            'held_order_count': held_summary['held_order_count'],
            'next_release_at': held_summary['next_release_at'],
            'orders': orders_data,
            'pagination': get_pagination_payload(total_count, limit, offset),
        })


class TopUpRequestView(ScopedPostThrottleMixin, APIView):
    """POST /api/wallet/top-up/ — Create a top-up request.
    GET /api/wallet/top-up/ — List my top-up requests.
    """
    permission_classes = [HasCompletedProfile]
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

        payment_proof = optimize_uploaded_image(payment_proof, preset='proof')

        try:
            with db_transaction.atomic():
                topup = TopUpRequest.objects.create(
                    user=request.user,
                    amount=data['amount'],
                    payment_method=data.get('payment_method', ''),
                    transaction_id=data.get('transaction_id', ''),
                    payment_proof=payment_proof,
                )
        except IntegrityError:
            return Response(
                {'transaction_id': ['This transaction reference has already been submitted.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        send_topup_request_received_email(topup)

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


class WithdrawReceiptView(APIView):
    """GET /api/wallet/withdraw/{id}/receipt/ — Serve a protected payment receipt."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        withdraw = get_object_or_404(WithdrawRequest, pk=pk)
        if not withdraw.payment_receipt:
            raise Http404
        has_ticket = has_valid_private_media_ticket(
            request,
            kind='withdraw_receipt',
            object_id=withdraw.pk,
        )
        can_view = (
            request.user.is_authenticated and
            (
                withdraw.user_id == request.user.id or
                (
                    request.user.is_staff and
                    request.user.has_perm('core.view_withdrawrequest')
                )
            )
        )
        if not (has_ticket or can_view):
            raise Http404
        return private_file_response(withdraw.payment_receipt)


class WithdrawRequestView(ScopedPostThrottleMixin, APIView):
    """POST /api/wallet/withdraw/ — Create a withdrawal request.
    GET /api/wallet/withdraw/ — List my withdrawal requests.
    """
    permission_classes = [HasCompletedProfile]
    throttle_scope = 'withdraw_request'

    def get(self, request):
        requests_qs = WithdrawRequest.objects.filter(user=request.user)
        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_WITHDRAW_REQUEST_PAGE_SIZE,
            max_limit=MAX_WITHDRAW_REQUEST_PAGE_SIZE,
        )
        total_count = requests_qs.count()
        withdraw_requests = requests_qs[offset:offset + limit]
        return Response({
            'withdraw_requests': WithdrawRequestSerializer(
                withdraw_requests, many=True,
                context={'request': request},
            ).data,
            'pagination': get_pagination_payload(total_count, limit, offset),
        })

    def post(self, request):
        serializer = CreateWithdrawRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        amount = data['amount']

        with db_transaction.atomic():
            wallet = get_or_create_locked_wallet(request.user)

            if wallet.balance < amount:
                return Response(
                    {'error': 'Insufficient wallet balance.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Deduct balance immediately (held until admin approves/rejects)
            wallet.balance -= amount
            wallet.save(update_fields=['balance', 'updated_at'])

            withdraw = WithdrawRequest.objects.create(
                user=request.user,
                amount=amount,
                payment_method=data.get('payment_method', ''),
                account_title=data.get('account_title', ''),
                account_details=data.get('account_details', ''),
                bank_name=data.get('bank_name', ''),
            )

            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type='withdraw_request',
                amount=amount,
                balance_after=wallet.balance,
                description=f'Withdrawal request: PKR {amount} via {data.get("payment_method", "N/A")}',
                reference_id=f'withdraw_{withdraw.pk}',
            )

        send_withdraw_request_received_email(withdraw)

        return Response(
            WithdrawRequestSerializer(withdraw, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


# ── JazzCash gateway views ───────────────────────────────────────────────────

JAZZCASH_UNAVAILABLE_ERROR = 'JazzCash payments are currently unavailable.'


def _jazzcash_disabled_response():
    return Response(
        {'error': JAZZCASH_UNAVAILABLE_ERROR},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


class JazzCashTopUpView(ScopedPostThrottleMixin, APIView):
    """POST /api/payments/jazzcash/top-up/ — Start an instant wallet top-up.

    Sends an MWallet payment request to the customer's JazzCash account; the
    wallet is credited as soon as JazzCash confirms (immediately, via IPN, or
    via status inquiry).
    """
    permission_classes = [HasCompletedProfile]
    throttle_scope = 'jazzcash_initiate'

    def post(self, request):
        if not settings.JAZZCASH_ENABLED:
            return _jazzcash_disabled_response()

        serializer = JazzCashTopUpInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            payment = start_jazzcash_payment(
                user=request.user,
                purpose='topup',
                amount=data['amount'],
                mobile_number=data['mobile_number'],
                description='GamesBazaar wallet top up',
            )
        except jazzcash.JazzCashError:
            return _jazzcash_disabled_response()

        return Response(
            JazzCashPaymentSerializer(payment).data,
            status=status.HTTP_201_CREATED,
        )


class JazzCashBuyView(ScopedPostThrottleMixin, APIView):
    """POST /api/payments/jazzcash/buy/ — Cover a wallet shortfall with JazzCash.

    Only available when the buyer's wallet cannot cover the order. Charges
    the shortfall (at least the minimum top-up) to the customer's JazzCash
    wallet. Once the payment is confirmed, the site wallet is credited and
    the purchase pays the full total from the wallet, so anything above the
    shortfall stays as balance; if the listing sold out in the meantime the
    whole payment stays in the wallet.
    """
    permission_classes = [HasCompletedProfile]
    throttle_scope = 'jazzcash_initiate'

    def post(self, request):
        if not settings.JAZZCASH_ENABLED:
            return _jazzcash_disabled_response()

        serializer = JazzCashBuyInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        qty = data.get('quantity', 1)

        try:
            listing = (
                Listing.objects.select_related('seller', 'game_category__category')
                .get(id=data['listing_id'])
            )
        except Listing.DoesNotExist:
            return Response({'error': 'This listing is no longer available.'}, status=400)

        # Fail fast on obviously invalid purchases. The authoritative checks
        # run again (with locks) when the confirmed payment executes the
        # purchase.
        if listing.status != 'active':
            return Response({'error': 'This listing is no longer available.'}, status=400)
        if listing.seller == request.user:
            return Response({'error': 'You cannot buy your own listing.'}, status=400)
        if listing.quantity is not None and qty > listing.quantity:
            return Response({'error': f'Only {listing.quantity} available.'}, status=400)

        total = listing.price * qty
        if total <= 0:
            return Response({'error': 'Invalid listing price.'}, status=400)

        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        if wallet.balance >= total:
            return Response(
                {'error': 'You have enough wallet balance for this order — pay with your wallet.'},
                status=400,
            )
        charge = max(total - wallet.balance, MIN_TOPUP_AMOUNT)

        try:
            payment = start_jazzcash_payment(
                user=request.user,
                purpose='purchase',
                amount=charge,
                mobile_number=data['mobile_number'],
                description='GamesBazaar order payment',
                listing=listing,
                listing_quantity=qty,
            )
        except jazzcash.JazzCashError:
            return _jazzcash_disabled_response()

        return Response(
            JazzCashPaymentSerializer(payment).data,
            status=status.HTTP_201_CREATED,
        )


class JazzCashPaymentDetailView(APIView):
    """GET /api/payments/jazzcash/{id}/ — Poll the status of my payment."""
    permission_classes = [HasCompletedProfile]

    def get(self, request, pk):
        payment = get_object_or_404(JazzCashPayment, pk=pk, user=request.user)
        payment = maybe_refresh_payment_status(payment)
        return Response(JazzCashPaymentSerializer(payment).data)


class JazzCashIPNView(APIView):
    """POST /api/payments/jazzcash/ipn/ — JazzCash Instant Payment Notification.

    Public endpoint registered with JazzCash. The secure hash is the only
    authentication, so unverifiable notifications are rejected. JazzCash
    retries twice when it doesn't get a success acknowledgement within 60s.
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    @staticmethod
    def _ack(code, message):
        ack = {'pp_ResponseCode': code, 'pp_ResponseMessage': message}
        try:
            ack['pp_SecureHash'] = jazzcash.generate_secure_hash(ack)
        except jazzcash.JazzCashError:
            ack['pp_SecureHash'] = ''
        return ack

    def post(self, request):
        logger = logging.getLogger(__name__)
        if not settings.JAZZCASH_ENABLED:
            return Response(
                self._ack('199', 'JazzCash is not configured.'),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        data = request.data
        if not isinstance(data, dict):
            return Response(
                self._ack('199', 'Invalid IPN payload.'),
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not jazzcash.verify_secure_hash(data):
            logger.warning('JazzCash IPN rejected: secure hash verification failed')
            return Response(
                self._ack('199', 'Secure hash verification failed.'),
                status=status.HTTP_400_BAD_REQUEST,
            )

        txn_ref_no = str(data.get('pp_TxnRefNo') or '').strip()
        payment = JazzCashPayment.objects.filter(txn_ref_no=txn_ref_no).first()
        if payment is None:
            logger.warning('JazzCash IPN for unknown transaction %s', txn_ref_no)
        else:
            apply_gateway_result(
                payment,
                response_code=data.get('pp_ResponseCode'),
                response_message=data.get('pp_ResponseMessage'),
                retrieval_reference_no=(
                    data.get('pp_RetreivalReferenceNo')  # gateway spells it this way
                    or data.get('pp_RetrievalReferenceNo')
                ),
                hash_verified=True,
                source='ipn',
            )

        return Response(self._ack('000', 'IPN received successfully'))


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


def order_reference_filter(order_ref):
    order_ref = str(order_ref).strip()
    lookup = Q(order_number__iexact=order_ref)
    if order_ref.isdigit() and len(order_ref) <= 19:
        pk_value = int(order_ref)
        if pk_value <= 9223372036854775807:
            lookup |= Q(pk=pk_value)
    return lookup


def get_order_by_reference_or_404(queryset, order_ref, **filters):
    return get_object_or_404(queryset.filter(order_reference_filter(order_ref), **filters))


def execute_listing_purchase(*, buyer, listing_id, quantity):
    """Run the full purchase flow for a listing, paying from the buyer's wallet.

    Shared by BuyListingView and the JazzCash direct-buy flow (which credits
    the wallet first, then purchases). Returns ``(order, None)`` on success or
    ``(None, error_message)`` when the purchase cannot proceed; error paths
    never mutate state.
    """
    qty = quantity

    with db_transaction.atomic():
        try:
            listing = (
                Listing.objects.select_for_update()
                .select_related('seller', 'game_category__category')
                .get(id=listing_id)
            )
        except Listing.DoesNotExist:
            return None, 'This listing is no longer available.'

        # Run validations after locking the listing so stock/status cannot
        # change between the check and the stock decrement.
        if listing.status != 'active':
            return None, 'This listing is no longer available.'

        if listing.seller == buyer:
            return None, 'You cannot buy your own listing.'

        if listing.quantity is not None and qty > listing.quantity:
            return None, f'Only {listing.quantity} available.'

        total = listing.price * qty
        if total <= 0:
            return None, 'Invalid listing price.'

        is_auto = listing.is_auto_delivery
        if is_auto:
            auto_delivery_data = decrypt_sensitive_text(listing.auto_delivery_data)
            all_lines = get_auto_delivery_inventory_lines(auto_delivery_data)
            if len(all_lines) < qty:
                item_label = 'item' if len(all_lines) == 1 else 'items'
                return None, f'Only {len(all_lines)} {item_label} remaining for auto-delivery.'
            delivered_lines = all_lines[:qty]
            remaining_lines = all_lines[qty:]
            delivery_note = '\n'.join(delivered_lines)
            delivery_note = encrypt_sensitive_text(delivery_note)
            initial_status = 'delivered'
            delivered_at = timezone.now()
        else:
            initial_status = 'pending'
            delivered_at = None
            delivery_note = ''

        wallet = get_or_create_locked_wallet(buyer)

        if wallet.balance < total:
            return None, 'Insufficient wallet balance.'

        category = listing.game_category.category
        rate = get_commission_rate(listing.seller, category)
        commission = (total * rate / Decimal('100')).quantize(Decimal('0.01'))
        seller_receives = total - commission

        # Deduct from buyer only after all purchase validations have passed.
        wallet.balance -= total
        wallet.save(update_fields=['balance', 'updated_at'])

        if is_auto:
            # Update the listing's remaining auto_delivery_data and quantity
            listing.auto_delivery_data = (
                encrypt_sensitive_text('\n'.join(remaining_lines))
                if remaining_lines else ''
            )
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
            buyer=buyer,
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
            was_auto_delivery=is_auto,
            delivery_note=delivery_note,
            delivered_at=delivered_at,
            buyer_protection_enabled=category.buyer_protection_enabled,
            delivery_instructions_snapshot=listing.delivery_instructions.strip(),
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

        conversation, _ = get_or_create_private_conversation(buyer, listing.seller)

        order.conversation = conversation
        order.save(update_fields=['conversation'])

        # Notify seller about new order
        create_notification(
            recipient=listing.seller,
            notification_type='new_order',
            title=f'New order from {buyer.username}',
            message=f'{buyer.username} purchased "{listing.title}" (x{qty}) for PKR {total}.',
            order=order,
        )

        # For auto-delivery, also notify buyer that it's delivered
        if is_auto:
            create_notification(
                recipient=buyer,
                notification_type='order_delivered',
                title='Your order has been automatically delivered!',
                message=f'Your order "{listing.title}" has been automatically delivered. Check your order for the delivery details.',
                order=order,
            )

    return order, None


class BuyListingView(APIView):
    """POST /api/orders/buy/ — Purchase a listing. Deducts from buyer wallet (escrow)."""
    permission_classes = [HasCompletedProfile]

    def post(self, request):
        serializer = BuyListingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        order, error = execute_listing_purchase(
            buyer=request.user,
            listing_id=data['listing_id'],
            quantity=data.get('quantity', 1),
        )
        if error:
            return Response({'error': error}, status=400)

        return Response(OrderSerializer(order, context={'request': request}).data, status=201)


class MyOrdersView(APIView):
    """GET /api/orders/mine/ — Orders where I'm the buyer.
    Query params: status, search, date_from, date_to, limit, offset
    """
    permission_classes = [HasCompletedProfile]

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
        ).select_related(
            'listing', 'seller', 'conversation',
            'review', 'review__reviewer',
        ).annotate(
            _has_review_annotation=Q(review__isnull=False),
        )

        orders_qs = self._apply_filters(request, orders_qs)

        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_ORDER_PAGE_SIZE,
            max_limit=MAX_ORDER_PAGE_SIZE,
        )
        before_id = get_before_id(request)
        use_cursor = request.query_params.get('cursor') == '1' or before_id is not None
        if use_cursor:
            orders, pagination = get_cursor_page(orders_qs, limit, before_id)
        else:
            total_count = orders_qs.count()
            orders = list(orders_qs[offset:offset + limit])
            pagination = get_pagination_payload(total_count, limit, offset)
        released_payout_refs = get_released_seller_payout_order_refs(orders)
        # Status counts (unfiltered) for tab badges
        status_counts = Order.objects.filter(buyer=request.user).values('status').annotate(
            count=Count('id')
        )
        counts = {item['status']: item['count'] for item in status_counts}

        return Response({
            'orders': OrderSerializer(
                orders,
                many=True,
                context={
                    'request': request,
                    'released_seller_payout_order_refs': released_payout_refs,
                },
            ).data,
            'pagination': pagination,
            'status_counts': counts,
        })


class MySalesView(APIView):
    """GET /api/orders/sales/ — Orders where I'm the seller.
    Query params: status, search, date_from, date_to, limit, offset
    """
    permission_classes = [HasCompletedProfile]

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
        ).select_related(
            'listing', 'buyer', 'conversation',
            'review', 'review__reviewer',
        ).annotate(
            _has_review_annotation=Q(review__isnull=False),
        )

        orders_qs = self._apply_filters(request, orders_qs)

        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_ORDER_PAGE_SIZE,
            max_limit=MAX_ORDER_PAGE_SIZE,
        )
        before_id = get_before_id(request)
        use_cursor = request.query_params.get('cursor') == '1' or before_id is not None
        if use_cursor:
            orders, pagination = get_cursor_page(orders_qs, limit, before_id)
        else:
            total_count = orders_qs.count()
            orders = list(orders_qs[offset:offset + limit])
            pagination = get_pagination_payload(total_count, limit, offset)
        released_payout_refs = get_released_seller_payout_order_refs(orders)
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
        summary['total_revenue'] = format(summary['total_revenue'] or Decimal('0.00'), '.2f')

        return Response({
            'sales': OrderSerializer(
                orders,
                many=True,
                context={
                    'request': request,
                    'released_seller_payout_order_refs': released_payout_refs,
                },
            ).data,
            'pagination': pagination,
            'summary': summary,
            'status_counts': counts,
        })


class OrderDetailView(APIView):
    """GET /api/orders/<id>/ — Get order detail."""
    permission_classes = [HasCompletedProfile]

    def get(self, request, order_ref):
        order = get_order_by_reference_or_404(
            Order.objects.select_related(
                'listing', 'buyer', 'seller', 'conversation',
                'review', 'review__reviewer',
            ),
            order_ref,
        )
        # Only buyer or seller can view
        if request.user not in (order.buyer, order.seller):
            return Response({'error': 'Not authorized.'}, status=403)

        # Auto-link conversation if missing
        if not order.conversation:
            conversation, _ = get_or_create_private_conversation(order.buyer, order.seller)

            order.conversation = conversation
            order.save(update_fields=['conversation'])

        return Response(OrderSerializer(order, context={'request': request}).data)


class DeliverOrderView(APIView):
    """POST /api/orders/<id>/deliver/ — Seller marks order as delivered."""
    permission_classes = [HasCompletedProfile]

    def post(self, request, order_ref):
        serializer = DeliverOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with db_transaction.atomic():
            order = get_order_by_reference_or_404(
                Order.objects.select_for_update(),
                order_ref,
                seller=request.user,
            )

            if order.status != 'pending':
                return Response({'error': 'Order can only be delivered when pending.'}, status=400)

            delivery_note = serializer.validated_data.get('delivery_note', '')
            order.status = 'delivered'
            order.delivery_note = encrypt_sensitive_text(delivery_note)
            order.delivered_at = timezone.now()
            order.save(update_fields=['status', 'delivery_note', 'delivered_at', 'updated_at'])

            # Notify buyer that seller delivered
            create_notification(
                recipient=order.buyer,
                notification_type='order_delivered',
                title='Your order has been delivered',
                message=f'{request.user.username} marked order "{order.listing_title}" as delivered.',
                order=order,
            )

        return Response(OrderSerializer(order, context={'request': request}).data)


class ConfirmOrderView(APIView):
    """POST /api/orders/<id>/confirm/ — Buyer confirms delivery. Releases funds to seller."""
    permission_classes = [HasCompletedProfile]

    def post(self, request, order_ref):
        with db_transaction.atomic():
            order = get_order_by_reference_or_404(
                Order.objects.select_for_update().select_related('seller'),
                order_ref,
                buyer=request.user,
            )

            if order.status == 'completed':
                return Response(OrderSerializer(order, context={'request': request}).data)

            if order.status != 'delivered':
                return Response({'error': 'Order cannot be confirmed in current state.'}, status=400)

            complete_order_with_seller_payout(
                order,
                sale_description=f'Sale completed: {order.listing_title} (x{order.quantity})',
                commission_description=f'Commission ({order.commission_rate}%): {order.listing_title}',
                ledger_description=f'Commission collected: {order.listing_title} (x{order.quantity})',
            )

            # Notify seller that buyer confirmed
            create_notification(
                recipient=order.seller,
                notification_type='order_confirmed',
                title='Order confirmed',
                message=f'Order "{order.listing_title}" has been confirmed.',
                order=order,
            )

        return Response(OrderSerializer(order, context={'request': request}).data)


class DisputeOrderView(APIView):
    """POST /api/orders/<id>/dispute/ — Buyer opens a dispute."""
    permission_classes = [HasCompletedProfile]

    def post(self, request, order_ref):
        serializer = DisputeOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data['reason']

        with db_transaction.atomic():
            order = get_order_by_reference_or_404(
                Order.objects.select_for_update(),
                order_ref,
                buyer=request.user,
            )

            can_dispute_completed_hold = is_order_in_buyer_protection_dispute_window(order)
            if order.status not in ('pending', 'delivered') and not can_dispute_completed_hold:
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

        return Response(OrderSerializer(order, context={'request': request}).data)


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
                    message=f'Your dispute for "{order.listing_title}" has been resolved. The order has been refunded.',
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
                complete_order_with_seller_payout(
                    order,
                    sale_description=f'Dispute resolved (seller): {order.listing_title}',
                    commission_description=f'Commission ({order.commission_rate}%): {order.listing_title}',
                    ledger_description=f'Commission collected: {order.listing_title}',
                )
                seller_title = 'Dispute resolved - order completed'
                seller_message = (
                    f'The dispute for "{order.listing_title}" has been resolved in your favour. '
                    'The order is now marked as completed.'
                )

                # Notify both parties
                create_notification(
                    recipient=order.seller,
                    notification_type='order_confirmed',
                    title=seller_title,
                    message=seller_message,
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

        return Response(OrderSerializer(order, context={'request': request}).data)


class RefundOrderView(APIView):
    """POST /api/orders/<id>/refund/ — Seller voluntarily refunds the buyer."""
    permission_classes = [HasCompletedProfile]

    def post(self, request, order_ref):
        with db_transaction.atomic():
            order = get_order_by_reference_or_404(
                Order.objects.select_for_update().select_related('buyer', 'seller'),
                order_ref,
                seller=request.user,
            )

            if order.status == 'cancelled':
                return Response(OrderSerializer(order, context={'request': request}).data)

            listing = None
            if order.listing_id:
                listing = Listing.objects.select_for_update().filter(pk=order.listing_id).first()
                if listing and (listing.quantity is None or listing.is_auto_delivery):
                    listing = None

            # If order was completed, seller already received funds — deduct from seller
            if order.status == 'completed' and order_seller_payout_has_been_released(order):
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
                message=f'Your order "{order.listing_title}" has been refunded.',
                order=order,
            )

        return Response(OrderSerializer(order, context={'request': request}).data)


# ── Reviews ───────────────────────────────────────────────────────────────────────

class CreateReviewView(APIView):
    """POST /api/reviews/ — Submit a review for a completed order."""
    permission_classes = [HasCompletedProfile]

    def post(self, request):
        serializer = CreateReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            with db_transaction.atomic():
                order = get_object_or_404(
                    Order.objects.select_for_update().select_related('seller').filter(
                        order_reference_filter(data['order_id']),
                    ),
                    buyer=request.user,
                )

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
                    title=f'New {data["rating"]}-star review from {request.user.username}',
                    message=f'{request.user.username} left a {data["rating"]}-star review for "{order.listing_title}".' + (f' "{data.get("comment", "")}"' if data.get('comment') else ''),
                    order=order,
                    review=review,
                )
        except IntegrityError:
            return Response({'error': 'You have already reviewed this order.'}, status=400)

        return Response(ReviewSerializer(review).data, status=201)


class UpdateReviewView(APIView):
    """PUT /api/reviews/<id>/ — Buyer edits their own review."""
    permission_classes = [HasCompletedProfile]

    def put(self, request, pk):
        serializer = UpdateReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        review = get_object_or_404(
            Review.objects.select_related('order'),
            pk=pk,
            reviewer=request.user,
        )

        review.rating = data['rating']
        review.comment = data.get('comment', '')
        review.updated_at = timezone.now()
        review.save(update_fields=['rating', 'comment', 'updated_at'])

        # Invalidate seller profile cache
        cache.delete(f'seller-profile:v1:{review.seller_id}')

        return Response(ReviewSerializer(review).data)


class ReplyToReviewView(APIView):
    """POST /api/reviews/<id>/reply/ — Seller replies once to a review."""
    permission_classes = [HasCompletedProfile]

    def post(self, request, pk):
        serializer = ReplyToReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        review = get_object_or_404(
            Review,
            pk=pk,
            seller=request.user,
        )

        if review.seller_reply:
            return Response({'error': 'You have already replied to this review.'}, status=400)

        review.seller_reply = serializer.validated_data['reply']
        review.seller_reply_at = timezone.now()
        review.save(update_fields=['seller_reply', 'seller_reply_at', 'updated_at'])

        # Invalidate seller profile cache
        cache.delete(f'seller-profile:v1:{review.seller_id}')

        return Response(ReviewSerializer(review).data)


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
    """GET /api/seller/profile/<username>/ — Public seller profile with stats + game services."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, username):
        seller = get_object_or_404(
            User.objects.select_related('profile'),
            username=username,
        )
        profile = seller.profile

        if profile.seller_status != 'approved':
            return Response({'error': 'Seller not found.'}, status=404)

        # Check cache for expensive aggregate queries
        cache_key = f'seller-profile:v1:{seller.pk}'
        cached = cache.get(cache_key)
        if cached is not None:
            # Online status and avatar must be fresh
            cached['is_online'] = profile.is_online
            cached['last_active'] = profile.last_active
            if profile.avatar:
                cached['avatar_url'] = cached_media_url(
                    profile.avatar,
                    request=request,
                    cache_seconds=AVATAR_CACHE_SECONDS,
                    cache_scope='private',
                )
            else:
                cached['avatar_url'] = None
            return Response(cached)

        # Single review query: get distribution and compute count+avg from it
        dist_qs = (
            Review.objects.filter(seller=seller)
            .values('rating')
            .annotate(count=Count('id'))
        )
        rating_distribution = {str(i): 0 for i in range(1, 6)}
        for row in dist_qs:
            rating_distribution[str(row['rating'])] = row['count']

        review_count = sum(rating_distribution.values())
        if review_count > 0:
            weighted_sum = sum(int(k) * v for k, v in rating_distribution.items())
            avg_rating = round(weighted_sum / review_count, 1)
        else:
            avg_rating = None

        # Positive rating percentage (4+ stars)
        positive_count = rating_distribution['4'] + rating_distribution['5']
        positive_pct = (
            round(positive_count / review_count * 100, 1) if review_count > 0 else None
        )

        # Get completed sales count
        completed_sales = Order.objects.filter(
            seller=seller, status='completed'
        ).count()

        # Build game services and get active listing count in a single query
        cat_stats = list(
            Listing.objects.filter(seller=seller, status='active')
            .values(
                'game_category__game__slug',
                'game_category__game__name',
                'game_category__category__slug',
                'game_category__category__name',
                'game_category__category__icon',
            )
            .annotate(listing_count=Count('id'))
            .order_by('game_category__game__name', '-listing_count')
        )

        # Derive active listing count from the same query
        active_listings_count = sum(row['listing_count'] for row in cat_stats)

        # Group by game
        games_map = {}
        for row in cat_stats:
            g_slug = row['game_category__game__slug']
            if g_slug not in games_map:
                games_map[g_slug] = {
                    'game_slug': g_slug,
                    'game_name': row['game_category__game__name'],
                    'total_offers': 0,
                    'categories': [],
                }
            games_map[g_slug]['total_offers'] += row['listing_count']
            games_map[g_slug]['categories'].append({
                'slug': row['game_category__category__slug'],
                'name': row['game_category__category__name'],
                'icon': row['game_category__category__icon'],
                'count': row['listing_count'],
            })

        # Sort games by total offers descending
        games = sorted(games_map.values(), key=lambda g: g['total_offers'], reverse=True)

        # Avatar URL
        avatar_url = None
        if profile.avatar:
            avatar_url = cached_media_url(
                profile.avatar,
                request=request,
                cache_seconds=AVATAR_CACHE_SECONDS,
                cache_scope='private',
            )

        payload = {
            'username': seller.username,
            'user_id': seller.pk,
            'member_since': seller.date_joined,
            'is_online': profile.is_online,
            'last_active': profile.last_active,
            'avg_rating': avg_rating,
            'positive_pct': positive_pct,
            'review_count': review_count,
            'rating_distribution': rating_distribution,
            'completed_sales': completed_sales,
            'active_listings': active_listings_count,
            'avatar_url': avatar_url,
            'games': games,
        }
        cache.set(cache_key, payload, SELLER_PROFILE_CACHE_SECONDS)
        return Response(payload)


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
            f'{request_origin_cache_scope(request)}:{normalized_query}'.encode('utf-8')
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
                icon_url = cached_media_url(
                    gc.game.icon,
                    request=request,
                    cache_seconds=GAME_ICON_CACHE_SECONDS,
                    cache_scope='public',
                )
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
    permission_classes = [HasCompletedProfile]

    def get(self, request):
        qs = Notification.objects.filter(recipient=request.user).select_related('order')
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
    permission_classes = [HasCompletedProfile]

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
    permission_classes = [HasCompletedProfile]

    def get(self, request):
        cache_key = f'notif-unread:v1:{request.user.pk}'
        cached = cache.get(cache_key)
        if cached is not None:
            return Response({'unread_count': cached})
        count = Notification.objects.filter(
            recipient=request.user,
            is_read=False,
        ).count()
        cache.set(cache_key, count, UNREAD_COUNT_CACHE_SECONDS)
        return Response({'unread_count': count})


class SellerDashboardView(APIView):
    """GET /api/seller/dashboard/ — Comprehensive seller analytics dashboard."""
    permission_classes = [HasCompletedProfile]

    def get(self, request):
        profile = request.user.profile
        if not profile.is_seller:
            return Response({'error': 'Not a seller.'}, status=403)

        cache_key = f'seller-dashboard:v1:{request.user.pk}'
        if not settings.DEBUG:
            cached_payload = cache.get(cache_key)
            if cached_payload is not None:
                return Response(cached_payload)

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
                'order_number': order.order_number,
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
        held_payout_summary = get_seller_held_payout_summary(request.user)

        payload = {
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
            'wallet_held_balance': str(held_payout_summary['held_balance']),
            'wallet_held_order_count': held_payout_summary['held_order_count'],
            'next_payout_release_at': held_payout_summary['next_release_at'],
        }
        if not settings.DEBUG:
            cache.set(cache_key, payload, timeout=60)
        return Response(payload)


# ── Report / Flag views ────────────────────────────────────────────────────────

class CreateReportView(ScopedPostThrottleMixin, APIView):
    """POST /api/reports/ — Submit a report/flag for a listing or user."""
    permission_classes = [HasCompletedProfile]
    throttle_scope = 'create_report'

    def post(self, request):
        serializer = CreateReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        target_type = data['target_type']
        reporter = request.user

        # Cannot report yourself
        if target_type == 'user' and data.get('user_id') == reporter.pk:
            return Response(
                {'error': 'You cannot report yourself.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Cannot report your own listing
        if target_type == 'listing':
            listing = Listing.objects.filter(pk=data['listing_id']).first()
            if listing and listing.seller_id == reporter.pk:
                return Response(
                    {'error': 'You cannot report your own listing.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        report_kwargs = {
            'reporter': reporter,
            'target_type': target_type,
            'reason': data['reason'],
            'description': data.get('description', ''),
        }

        if target_type == 'listing':
            report_kwargs['reported_listing_id'] = data['listing_id']
        elif target_type == 'user':
            report_kwargs['reported_user_id'] = data['user_id']

        try:
            with db_transaction.atomic():
                report = Report.objects.create(**report_kwargs)
        except IntegrityError:
            return Response(
                {'error': 'You have already submitted a report for this. It is currently under review.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                'message': 'Report submitted successfully. Our team will review it shortly.',
                'report': ReportSerializer(report).data,
            },
            status=status.HTTP_201_CREATED,
        )


class MyReportsView(APIView):
    """GET /api/reports/mine/ — List reports submitted by the current user."""
    permission_classes = [HasCompletedProfile]

    def get(self, request):
        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_ORDER_PAGE_SIZE,
            max_limit=MAX_ORDER_PAGE_SIZE,
        )
        qs = Report.objects.filter(reporter=request.user).select_related(
            'reported_listing', 'reported_user',
        )
        total = qs.count()
        reports = list(qs[offset:offset + limit])
        return Response({
            'reports': ReportSerializer(reports, many=True).data,
            'pagination': get_pagination_payload(total, limit, offset),
        })


# ── Support Tickets ──────────────────────────────────────────────────────────

class CreateSupportTicketView(ScopedPostThrottleMixin, APIView):
    """POST /api/support/ — Submit a support ticket. Works for guests and logged-in users."""
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'create_support_ticket'

    def post(self, request):
        serializer = CreateSupportTicketSerializer(
            data=request.data, context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        ticket = SupportTicket.objects.create(
            user=request.user if request.user.is_authenticated else None,
            guest_email=data.get('email', '') if not request.user.is_authenticated else '',
            name=data.get('name', ''),
            category=data['category'],
            subject=data['subject'],
            message=data['message'],
            order_id=data.get('order_id'),
        )

        return Response(
            {
                'message': 'Your support ticket has been submitted. We will get back to you soon!',
                'ticket': SupportTicketSerializer(ticket).data,
            },
            status=status.HTTP_201_CREATED,
        )


class MySupportTicketsView(APIView):
    """GET /api/support/mine/ — List support tickets submitted by the current user."""
    permission_classes = [HasCompletedProfile]

    def get(self, request):
        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_ORDER_PAGE_SIZE,
            max_limit=MAX_ORDER_PAGE_SIZE,
        )
        qs = SupportTicket.objects.filter(user=request.user)
        total = qs.count()
        tickets = list(qs[offset:offset + limit])
        return Response({
            'tickets': SupportTicketSerializer(tickets, many=True).data,
            'pagination': get_pagination_payload(total, limit, offset),
        })
