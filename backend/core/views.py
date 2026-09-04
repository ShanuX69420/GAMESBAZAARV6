from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import logging
import re
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
from django.db.models.functions import Coalesce, Length, Trim
from django.db import IntegrityError, transaction as db_transaction
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.utils.dateparse import parse_date
from django.utils.text import Truncator, slugify
from django.views import View
from .throttling import AttemptScopedRateThrottle, SuccessScopedRateThrottle
from .models import (
    Game, GameCategory, CategoryOption, Filter, UserProfile, Listing, Conversation, Message,
    Wallet, WalletTransaction, TopUpRequest, WithdrawRequest, Order,
    JazzCashPayment, SellerCommissionOverride, WhatsAppCheckout,
    Review, ReviewImage, Notification, Report, SupportTicket, SocialAccount, ItemRequest,
    RetiredListing,
)
from . import listing_lifecycle
from .filter_options import stocked_filter_values, trim_filters_to_stock
from .region_pages import (
    active_region_listings, all_region_pages_payload, region_filter_for,
    region_option_labels, region_pages_payload,
)

# Fastest delivery first; shared by the browse ordering and by the per-option
# "best listing" pick in offer mode so the two always agree.
DELIVERY_SPEED_RANK = Case(
    When(delivery_time='Instant', then=Value(0)),
    When(delivery_time='2-3 Minutes', then=Value(1)),
    When(delivery_time='5 Minutes', then=Value(2)),
    When(delivery_time='10-15 Minutes', then=Value(3)),
    When(delivery_time='15-30 Minutes', then=Value(4)),
    When(delivery_time='30-60 Minutes', then=Value(5)),
    When(delivery_time='1-2 Hours', then=Value(6)),
    When(delivery_time='2-6 Hours', then=Value(7)),
    When(delivery_time='6-12 Hours', then=Value(8)),
    When(delivery_time='12-24 Hours', then=Value(9)),
    When(delivery_time='1-3 Days', then=Value(10)),
    default=Value(11),
    output_field=IntegerField(),
)
# Best offer for an option = what the buy box shows first: cheapest, then
# fastest delivery, then newest.
BEST_OFFER_ORDERING = ('price', 'delivery_speed_rank', '-created_at')

GAME_LIST_CACHE_KEY = 'game-list:v3'
GAME_LIST_CACHE_SECONDS = 60
# The category sections: each one has a "View All" page, and most also get a
# "Popular" panel on the home page, in this order.
# A section is omitted from the home response while its categories have no games.
# category_slugs lists every slug the section accepts — the Top Ups category
# kept its original "subscription" slug in production after a rename.
# facets = the View All page's filter dropdowns, OPT-IN per section. Only keys
# gets them (Shayan 2026-08-08): top-ups/gift-cards/accounts pages also carry
# Region filters, so detecting facets from the data alone put unwanted
# dropdowns on their View All pages.
# home=False keeps a section's View All page but drops its home-page panel
# (no section uses it since Offline Activation was removed outright, 2026-08-23).
HOME_POPULAR_SECTIONS = [
    {'slug': 'accounts', 'title': 'Popular Accounts',
     'category_slugs': ('accounts',)},
    # Direct game top-ups were retired 2026-09-02 (unreliable supplier, no
    # second source, ~10% margin). The two code-delivered pages that lived
    # under Top Ups — PlayStation Plus and Xbox Game Pass — moved to the
    # Subscriptions category; the old 'top-ups' category keeps its
    # deactivated listings and is no longer a section.
    # Two games only (PlayStation, Xbox) — too thin for a home panel
    # (Shayan 2026-09-02); the View All page stays, linked from the footer.
    {'slug': 'subscriptions', 'title': 'Popular Subscriptions',
     'category_slugs': ('subscriptions',), 'home': False},
    {'slug': 'keys', 'title': 'Popular Keys',
     'category_slugs': ('keys',), 'facets': ('method', 'region'),
     'sortable': True},
    {'slug': 'gift-cards', 'title': 'Popular Gift Cards',
     'category_slugs': ('gift-cards',)},
    {'slug': 'rentals', 'title': 'Popular Rentals',
     'category_slugs': ('rentals',)},
]
# The subset the home page actually renders panels for.
HOME_PANEL_SECTIONS = [
    section for section in HOME_POPULAR_SECTIONS if section.get('home', True)
]
HOME_POPULAR_GAMES_PER_SECTION = 8
HOME_POPULAR_CACHE_KEY = 'home-popular:v5'
HOME_POPULAR_CACHE_SECONDS = 60
# "View All" pages behind the popular panels reuse the same section registry.
CATEGORY_SECTION_BY_SLUG = {
    section['slug']: section for section in HOME_POPULAR_SECTIONS
}


_FIRST_NUMBER = re.compile(r'\d[\d,]*(?:\.\d+)?')


def option_display_key(option):
    """Sort key for offer-mode tiles: admin order first, then the first
    number in the name (5 USD < 10 USD, 1 Month < 12 Months), then A-Z."""
    match = _FIRST_NUMBER.search(option.name)
    number = float(match.group().replace(',', '')) if match else float('inf')
    return (option.order, number, option.name.lower())
# Section listings with no Method value count as this method. The Steam Keys
# page deliberately has no Method filter (2026-07-13 — everything on it IS a
# digital key), so /keys must not drop Steam when "Digital Key" is picked.
SECTION_METHOD_FALLBACKS = {'keys': 'digital-key'}
# Sort options on a sortable section's View All page. The empty default is
# name A-Z, which is what the page renders anyway (it groups games under
# letter dividers); picking any other sort switches it to a flat list.
SECTION_SORTS = [
    {'value': '', 'label': 'Name (A-Z)'},
    {'value': 'price_asc', 'label': 'Price: Low to High'},
    {'value': 'price_desc', 'label': 'Price: High to Low'},
    {'value': 'listings', 'label': 'Most Listings'},
]
SECTION_SORT_VALUES = {sort['value'] for sort in SECTION_SORTS}
CATEGORY_SECTION_CACHE_KEY = 'category-section-games:v5'
BROWSE_CACHE_SECONDS = 30
# Shared-cache TTL for the public browse endpoints nginx caches (games/,
# home/popular/, categories/). Browsers keep the short max-age values; s-maxage
# lets nginx serve the same response for 5 minutes, so cold-cache bursts
# (homepage SSR fan-out, crawlers) refill each URL once per window instead of
# once a minute — the 2026-07-18 sitewide lag bursts.
BROWSE_SHARED_CACHE_SECONDS = 300


def public_cache_header(browser_seconds):
    return (
        f'public, max-age={browser_seconds}, '
        f's-maxage={BROWSE_SHARED_CACHE_SECONDS}'
    )


# Sitemap listing feed: crawlers hit this rarely, so cache hard and cap the page
# size at Google's per-sitemap URL limit.
SITEMAP_LISTINGS_CACHE_KEY = 'sitemap-listings:v1'
SITEMAP_LISTINGS_CACHE_SECONDS = 900
SITEMAP_LISTINGS_MAX_LIMIT = 50000
SELLER_PROFILE_CACHE_SECONDS = 30
UNREAD_COUNT_CACHE_SECONDS = 5
from .serializers import (
    GameListSerializer, GameDetailSerializer, GameCategoryDetailSerializer,
    RegisterSerializer, EmailTokenObtainPairSerializer, UserSerializer,
    UpdateProfileSerializer, ChangePasswordSerializer, CompleteProfileSerializer,
    build_listing_filter_display_map, get_auto_delivery_inventory_lines,
    ListingSerializer, CreateListingSerializer,
    AutoDeliveryRestockSerializer, MAX_AUTO_DELIVERY_LINES, MAX_AUTO_DELIVERY_LINE_LENGTH,
    MAX_PURCHASE_QUANTITY, MAX_PURCHASE_QUANTITY_ERROR,
    ConversationListSerializer, ConversationDetailSerializer, MessageSerializer,
    WalletSerializer, WalletTransactionSerializer,
    TopUpRequestSerializer, CreateTopUpRequestSerializer,
    JazzCashTopUpInitiateSerializer, JazzCashBuyInitiateSerializer,
    JazzCashGuestBuyInitiateSerializer, JazzCashPaymentSerializer,
    WithdrawRequestSerializer, CreateWithdrawRequestSerializer,
    OrderSerializer, BuyListingSerializer, DeliverOrderSerializer,
    ReviewSerializer, CreateReviewSerializer, UpdateReviewSerializer, ReplyToReviewSerializer,
    NotificationSerializer,
    CreateReportSerializer, ReportSerializer,
    CreateSupportTicketSerializer, SupportTicketSerializer,
    CreateItemRequestSerializer,
)
from .services import (
    CHAT_MESSAGE_EMPTY_ERROR,
    broadcast_chat_message_after_commit,
    chat_unread_cache_key,
    notification_unread_cache_key,
    create_notification as create_user_notification,
    decode_private_media_ticket,
    apply_wallet_delta_once,
    complete_order_now,
    get_or_create_locked_wallet,
    order_seller_payout_has_been_released,
    record_platform_ledger_once,
    revoke_user_refresh_tokens,
    ALLOWED_IMAGE_CONTENT_TYPES,
    decrypt_sensitive_text,
    encrypt_sensitive_text,
    get_or_create_private_conversation,
    issue_guard_code,
    maybe_answer_guard_command,
    post_order_chat_message,
    validate_chat_listing_reference,
    validate_chat_message_content,
    validate_uploaded_image,
    optimize_uploaded_image,
    resolve_whatsapp_review_seller,
    seller_profile_cache_key,
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
    send_guest_account_email,
    send_topup_request_received_email,
    send_withdraw_request_received_email,
    generate_email_verification_code,
    create_email_verification_token,
    verify_email_verification_token,
    consume_email_verification_token,
    send_email_verification_code,
    notify_staff_about_item_request,
)
from . import attribution, fazer, fulfillment, jazzcash, meta_capi
from .payments import (
    apply_gateway_result,
    find_reusable_pending_payment,
    maybe_refresh_payment_status,
    start_jazzcash_payment,
)
from .storage_backends import (
    AVATAR_MEDIA_KIND,
    CLOUDFLARE_R2_NAME_PREFIX,
    GAME_ICON_CACHE_SECONDS,
    PUBLIC_MEDIA_REDIRECT_CACHE_SECONDS,
    PUBLIC_MEDIA_SIGNED_URL_MEMO_SECONDS,
    PUBLIC_MEDIA_SIGNED_URL_SECONDS,
    R2_SIGNED_URL_CACHE_SAFETY_SECONDS,
    R2_SIGNED_URL_MAX_SECONDS,
    cached_media_url,
    is_cloudflare_r2_name,
    is_public_media_storage,
    media_content_type,
    public_avatar_url,
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
MAX_REVIEW_IMAGES = 3
# Sitewide review strip (the marquee above the footer). It renders on every
# page, so it is cached hard and kept small. Only 4-5 star reviews with a real
# sentence in them qualify — a bare "." or a one-word rating is not a
# testimonial. MAX_COMMENT_LENGTH keeps every card the same rough size.
SITE_REVIEWS_CACHE_KEY = 'site-reviews:v1'
SITE_REVIEWS_CACHE_SECONDS = 300
SITE_REVIEWS_LIMIT = 20
SITE_REVIEWS_MIN_RATING = 4
SITE_REVIEWS_MIN_COMMENT_LENGTH = 12
SITE_REVIEWS_MAX_COMMENT_LENGTH = 200
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


class SuccessCountedThrottleMixin(ScopedPostThrottleMixin):
    """
    Charge `throttle_scope` only for requests the view accepted.

    Views using this must call `record_throttled_success()` at the point the
    request is known to have succeeded; rejected forms then cost nothing.
    `attempt_throttle_scope` still caps total attempts, so the endpoint is
    protected from scripted floods.
    """
    throttle_classes = [SuccessScopedRateThrottle, AttemptScopedRateThrottle]

    def get_throttles(self):
        throttles = super().get_throttles()
        # check_throttles() calls this once and primes each instance with the
        # cache key and history, so keep them to write back to on success.
        self._deferred_throttles = throttles
        return throttles

    def record_throttled_success(self):
        for throttle in getattr(self, '_deferred_throttles', ()):
            record = getattr(throttle, 'record', None)
            if record is not None:
                record()


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
        When(delivery_time='Instant', then=Value(12)),  # platform auto-fulfilled
        When(delivery_time__in=[
            '2-3 Minutes', '5 Minutes', '10-15 Minutes',
            '15-30 Minutes', '30-60 Minutes',
        ], then=Value(8)),
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
    """Serialize a REST-created message and refresh unread badges.

    Serialize with the request so image URLs stay absolute; the after-commit
    hook invalidates the other participants' unread caches for polling.
    """
    message_data = dict(MessageSerializer(message, context={'request': request}).data)
    broadcast_chat_message_after_commit(message)
    return message_data


# Public media that must load from server-rendered HTML long after it was
# rendered: the payload carries a stable /api/media/<kind>/<name> address and
# this endpoint turns it into a short-lived signed R2 URL on demand.
# Only files referenced by a live row of the mapped model resolve, so the
# endpoint cannot be used to sign arbitrary bucket objects (chat images,
# payment proofs and the like stay behind their permission checks).
PUBLIC_MEDIA_KINDS = {
    AVATAR_MEDIA_KIND: (UserProfile, 'avatar'),
}


def public_media_signed_url(file_field):
    """Signed R2 URL for a public media object, memoised briefly so repeat
    visitors keep hitting the same URL (and their browser cache)."""
    name = file_field.name
    content_type = media_content_type(name)
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise Http404
    memo_key = 'public-media-url:v1:' + hashlib.sha256(name.encode('utf-8')).hexdigest()
    url = cache.get(memo_key)
    if url is None:
        url = file_field.storage.url(
            name,
            parameters={
                'ResponseCacheControl': f'public, max-age={PUBLIC_MEDIA_SIGNED_URL_SECONDS}',
                'ResponseContentType': content_type,
            },
            expire=PUBLIC_MEDIA_SIGNED_URL_SECONDS,
        )
        cache.set(memo_key, url, PUBLIC_MEDIA_SIGNED_URL_MEMO_SECONDS)
    return url


def public_media_redirect(request, file_field):
    if not file_field:
        raise Http404
    if is_public_media_storage(file_field.storage):
        # Already on the public host: this endpoint only serves links that
        # older cached pages still carry. Send them to the permanent address
        # and let them keep it for a day.
        if media_content_type(file_field.name) not in ALLOWED_IMAGE_CONTENT_TYPES:
            raise Http404
        response = HttpResponseRedirect(cached_media_url(file_field, request=request))
        response['Cache-Control'] = 'public, max-age=86400'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
    if is_cloudflare_r2_name(file_field.name):
        target = public_media_signed_url(file_field)
    else:
        if media_content_type(file_field.name) not in ALLOWED_IMAGE_CONTENT_TYPES:
            raise Http404
        target = request.build_absolute_uri(file_field.url)
    response = HttpResponseRedirect(target)
    response['Cache-Control'] = f'public, max-age={PUBLIC_MEDIA_REDIRECT_CACHE_SECONDS}'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


class PublicMediaView(View):
    """GET /api/media/<kind>/<name> — stable address for a public media file.

    302s to a freshly signed R2 URL (or the plain /media/ path for legacy
    local files). The redirect is cacheable for a few minutes; the signed URL
    it points at lives much longer, so a cached redirect never dereferences
    to an expired link.
    """
    http_method_names = ['get', 'head']

    def get(self, request, kind, name):
        try:
            model, field_name = PUBLIC_MEDIA_KINDS[kind]
        except KeyError:
            raise Http404
        candidates = [f'{CLOUDFLARE_R2_NAME_PREFIX}{kind}/{name}', f'{kind}/{name}']
        row = model.objects.filter(**{f'{field_name}__in': candidates}).only(field_name).first()
        if row is None:
            raise Http404
        return public_media_redirect(request, getattr(row, field_name))


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
                ),
                min_active_price=Min(
                    'game_categories__listings__price',
                    filter=Q(game_categories__listings__status='active'),
                ),
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
        response['Cache-Control'] = public_cache_header(GAME_LIST_CACHE_SECONDS)
        return response


class HomePopularView(APIView):
    """GET /api/home/popular/ — Curated "Popular" panels for the home page.

    One section per HOME_PANEL_SECTIONS category, each listing the top games
    in that category: featured (admin-pinned) first, then by active listing
    count, then the game's manual order. Categories without games are omitted
    so the home page never shows an empty panel.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        cache_key = f'{HOME_POPULAR_CACHE_KEY}:{request_origin_cache_scope(request)}'
        data = cache.get(cache_key)
        if data is None:
            data = self.build_sections(request)
            cache.set(cache_key, data, HOME_POPULAR_CACHE_SECONDS)
        response = Response(data)
        response['Cache-Control'] = public_cache_header(HOME_POPULAR_CACHE_SECONDS)
        return response

    def build_sections(self, request):
        section_by_category_slug = {
            category_slug: section['slug']
            for section in HOME_PANEL_SECTIONS
            for category_slug in section['category_slugs']
        }
        rows = (
            GameCategory.objects
            .filter(
                category__slug__in=section_by_category_slug,
                game__is_active=True,
            )
            .select_related('game', 'category')
            .annotate(
                active_listing_count=Count(
                    'listings', filter=Q(listings__status='active'),
                ),
                min_active_price=Min(
                    'listings__price', filter=Q(listings__status='active'),
                ),
            )
            .order_by('-featured', '-active_listing_count', 'game__order', 'game__name')
        )

        games_by_section = {}
        for row in rows:
            bucket = games_by_section.setdefault(
                section_by_category_slug[row.category.slug], [])
            if len(bucket) >= HOME_POPULAR_GAMES_PER_SECTION:
                continue
            icon_url = None
            if row.game.icon:
                icon_url = cached_media_url(
                    row.game.icon,
                    request=request,
                    cache_seconds=GAME_ICON_CACHE_SECONDS,
                    cache_scope='public',
                )
            bucket.append({
                'game_name': row.game.name,
                'game_slug': row.game.slug,
                'category_slug': row.effective_slug,
                'icon_url': icon_url,
                'listing_count': row.active_listing_count,
                'min_price': (
                    str(row.min_active_price)
                    if row.min_active_price is not None else None
                ),
            })

        return {
            'sections': [
                {
                    'slug': section['slug'],
                    'title': section['title'],
                    'items': games_by_section[section['slug']],
                }
                for section in HOME_PANEL_SECTIONS
                if games_by_section.get(section['slug'])
            ],
        }


class CategorySectionGamesView(APIView):
    """GET /api/categories/{slug}/games/ — every game with active listings in
    one home "Popular" section (keys, accounts, subscriptions, gift-cards),
    for that section's View All page. Same item shape as
    HomePopularView, uncapped; unlike the panels, stockless games are omitted.

    Sections whose pages carry Method/Region filters (keys) also accept
    ?method= and ?region= (option values): games, counts and from-prices then
    reflect only matching listings, and the response lists the available
    choices for both dropdowns, each narrowed by the other selection.
    Sortable sections additionally accept ?sort= (see SECTION_SORTS).
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, slug):
        section = CATEGORY_SECTION_BY_SLUG.get(slug)
        if section is None:
            raise Http404
        method = slugify(request.query_params.get('method', ''))[:50]
        region = slugify(request.query_params.get('region', ''))[:50]
        sort = request.query_params.get('sort', '').strip()[:20]
        if not section.get('sortable') or sort not in SECTION_SORT_VALUES:
            sort = ''
        cache_key = (
            f'{CATEGORY_SECTION_CACHE_KEY}:{slug}:{method}:{region}:{sort}:'
            f'{request_origin_cache_scope(request)}'
        )
        data = cache.get(cache_key)
        if data is None:
            data = self.build_payload(request, section, method, region, sort)
            cache.set(cache_key, data, HOME_POPULAR_CACHE_SECONDS)
        response = Response(data)
        response['Cache-Control'] = public_cache_header(HOME_POPULAR_CACHE_SECONDS)
        return response

    @staticmethod
    def sort_items(items, sort):
        """Reorder the built items in place-ish. The default ('') keeps the
        queryset's most-stocked-first order; the page groups those A-Z itself."""
        if sort == 'listings':
            return sorted(items, key=lambda item: (-item['listing_count'],
                                                   item['game_name'].lower()))
        if sort in ('price_asc', 'price_desc'):
            # A game with no from-price can only happen if it lost its stock
            # between the two aggregates — sort it last either way.
            def price_key(item):
                raw = item['min_price']
                return Decimal(raw) if raw is not None else None
            priced = [item for item in items if price_key(item) is not None]
            unpriced = [item for item in items if price_key(item) is None]
            # Negate rather than reverse= so equal prices stay A-Z both ways.
            direction = -1 if sort == 'price_desc' else 1
            priced.sort(key=lambda item: (direction * price_key(item),
                                          item['game_name'].lower()))
            return priced + unpriced
        return items

    def facet_filters(self, section, name_fragment):
        """Filters of one kind assigned to this section's pages, found by
        name. Keys pages carry one shared Method filter and three Region
        dropdowns (the shared Key Region + gift/login pair and Steam's
        page-local one) — all named alike, distinguished only by admin_label.

        Sections that did not opt into this facet get no dropdown at all."""
        if name_fragment not in section.get('facets', ()):
            return []
        return list(
            Filter.objects
            .filter(
                name__icontains=name_fragment,
                game_category_assignments__game_category__category__slug__in=(
                    section['category_slugs']),
            )
            .distinct()
            .prefetch_related('options')
        )

    @staticmethod
    def option_labels_and_positions(facet_filters):
        labels, positions = {}, {}
        for filter_index, facet_filter in enumerate(facet_filters):
            for option in facet_filter.options.all():
                labels.setdefault(option.value, option.label)
                positions.setdefault(option.value, (filter_index, option.order))
        return labels, positions

    def facet_data(self, section, method_filters, region_filters,
                   method, region):
        """Validate the requested selections and build both dropdowns in one
        pass over the section's active listings, so neither dropdown ever
        offers a dead value. Each list is narrowed by the OTHER selection —
        pick "As a Gift" and Region only shows regions with gift stock,
        mirroring the dependent filters on the real pages."""
        method_ids = [str(f.pk) for f in method_filters]
        region_ids = [str(f.pk) for f in region_filters]
        if not method_ids and not region_ids:
            return '', '', [], []
        fallback_method = (
            SECTION_METHOD_FALLBACKS.get(section['slug'])
            if method_ids else None
        )
        pairs = []
        stocked_values = (
            Listing.objects
            .filter(
                status='active',
                game_category__category__slug__in=section['category_slugs'],
                game_category__game__is_active=True,
            )
            .values_list('filter_values', flat=True)
        )
        for filter_values in stocked_values.iterator():
            filter_values = filter_values or {}
            listing_method = next(
                (str(filter_values[filter_id]) for filter_id in method_ids
                 if filter_values.get(filter_id)),
                fallback_method)
            listing_region = next(
                (str(filter_values[filter_id]) for filter_id in region_ids
                 if filter_values.get(filter_id)),
                None)
            pairs.append((listing_method, listing_region))

        if method not in {m for m, _ in pairs if m}:
            method = ''
        if region not in {r for _, r in pairs if r}:
            region = ''

        method_values = {m for m, r in pairs
                         if m and (not region or r == region)}
        region_values = {r for m, r in pairs
                         if r and (not method or m == method)}
        # The active selection stays pickable even when the cross-narrowed
        # list would drop it (a combination with no stock renders the empty
        # state, not a blanked dropdown).
        if method:
            method_values.add(method)
        if region:
            region_values.add(region)

        labels, positions = self.option_labels_and_positions(method_filters)
        methods = [
            {'value': value,
             'label': labels.get(value, value.replace('-', ' ').title())}
            for value in method_values
        ]
        methods.sort(key=lambda choice: (
            *positions.get(choice['value'], (len(method_filters), 0)),
            choice['label'].lower()))

        labels, _ = self.option_labels_and_positions(region_filters)
        regions = [
            {'value': value,
             'label': labels.get(value, value.replace('-', ' ').title())}
            for value in region_values
        ]
        regions.sort(key=lambda choice: (choice['value'] != 'global',
                                         choice['label'].lower()))
        return method, region, methods, regions

    def build_payload(self, request, section, method='', region='', sort=''):
        method_filters = self.facet_filters(section, 'method')
        region_filters = self.facet_filters(section, 'region')
        method, region, methods, regions = self.facet_data(
            section, method_filters, region_filters, method, region)

        active_q = Q(listings__status='active')
        if method:
            method_q = Q()
            for method_filter in method_filters:
                method_q |= Q(listings__filter_values__contains={
                    str(method_filter.pk): method})
            if method == SECTION_METHOD_FALLBACKS.get(section['slug']):
                # Listings with no Method value at all count as the fallback:
                # the Steam Keys page has no Method filter by design
                # (everything on it IS a digital key).
                method_q |= ~Q(listings__filter_values__has_any_keys=[
                    str(f.pk) for f in method_filters])
            active_q &= method_q
        if region:
            region_q = Q()
            for region_filter in region_filters:
                region_q |= Q(listings__filter_values__contains={
                    str(region_filter.pk): region})
            active_q &= region_q

        rows = (
            GameCategory.objects
            .filter(
                category__slug__in=section['category_slugs'],
                game__is_active=True,
            )
            .select_related('game', 'category')
            .annotate(
                active_listing_count=Count('listings', filter=active_q),
                min_active_price=Min('listings__price', filter=active_q),
            )
            .filter(active_listing_count__gt=0)
            .order_by('-active_listing_count', 'game__order', 'game__name')
        )

        items = []
        seen_game_ids = set()
        for row in rows:
            # A game can hold two spellings of the same category (the Top Ups
            # rename kept both slugs in play) — keep its best-stocked row only.
            if row.game_id in seen_game_ids:
                continue
            seen_game_ids.add(row.game_id)
            icon_url = None
            if row.game.icon:
                icon_url = cached_media_url(
                    row.game.icon,
                    request=request,
                    cache_seconds=GAME_ICON_CACHE_SECONDS,
                    cache_scope='public',
                )
            items.append({
                'game_name': row.game.name,
                'game_slug': row.game.slug,
                'category_slug': row.effective_slug,
                'icon_url': icon_url,
                'listing_count': row.active_listing_count,
                'min_price': (
                    str(row.min_active_price)
                    if row.min_active_price is not None else None
                ),
            })

        return {
            'slug': section['slug'],
            'title': section['title'],
            'method': method,
            'methods': methods,
            'region': region,
            'regions': regions,
            'sort': sort,
            'sorts': SECTION_SORTS if section.get('sortable') else [],
            'items': self.sort_items(items, sort),
        }


class GameDetailView(generics.RetrieveAPIView):
    """GET /api/games/{slug}/ — Game detail with its categories."""
    serializer_class = GameDetailSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = 'slug'
    queryset = Game.objects.filter(is_active=True).prefetch_related(
        Prefetch(
            'game_categories',
            queryset=GameCategory.objects.select_related('category').annotate(
                active_listing_count=Count(
                    'listings', filter=Q(listings__status='active'),
                )
            ),
        )
    )

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        response['Cache-Control'] = public_cache_header(120)
        return response


# Hand-written seo_titles may carry a "from PKR {from_price}" phrase; the token
# is filled with the page's cheapest active listing price (exact) at response time
# (Search Console pilot 2026-08-29: "<game> price in pakistan" queries ranked
# top-10 with ~0% CTR because the titles showed no price).
SEO_FROM_PRICE_TOKEN = '{from_price}'


# Keys and accounts pages without hand-written copy get a generated title that
# carries the same price token. The 2026-08-29 pilot (12 hand-titled pages) was
# rolled out sitewide on 2026-09-03 at Shayan's call: "<game> price in pakistan"
# is the query pattern these pages already rank for, and a title without a
# price was drawing ~0% CTR. Other categories keep the frontend's generic
# fallback until they get real copy.
DEFAULT_PRICE_TITLE_CATEGORIES = ('keys', 'accounts')


def default_seo_title(game_category):
    if game_category.category.slug not in DEFAULT_PRICE_TITLE_CATEGORIES:
        return ''
    return (
        f'{game_category.game.name} {game_category.effective_name} in Pakistan '
        f'from PKR {SEO_FROM_PRICE_TOKEN}'
    )


def fill_from_price(title, listings_qs):
    """Fill the from-price token in a title with the cheapest active price in
    `listings_qs`, exactly as the tile shows it. (The pilot floored it to two
    significant digits against sync jitter; Shayan dropped that on 2026-09-03
    when "from PKR 11,000" sat above a PKR 11,900 tile — the syncs already
    round every price up to the next 50 / 10, so titles only move when a
    price really moves.) With no active listings the whole "from PKR ..."
    phrase drops out, leaving the plain hand-written title."""
    if SEO_FROM_PRICE_TOKEN not in title:
        return title
    min_price = listings_qs.aggregate(min_price=Min('price'))['min_price']
    if min_price is None or min_price <= 0:
        title = re.sub(r'\s*\bfrom PKR \{from_price\}', '', title,
                       flags=re.IGNORECASE)
        title = title.replace(SEO_FROM_PRICE_TOKEN, '')
        return ' '.join(title.split())
    return title.replace(SEO_FROM_PRICE_TOKEN, f'{int(min_price):,}')


def seo_title_with_from_price(game_category):
    title = game_category.seo_title or default_seo_title(game_category)
    return fill_from_price(
        title, Listing.objects.filter(game_category=game_category, status='active'))


def default_region_seo_title(region_page, label):
    """A region page without hand-written copy still gets a priced title:
    "PlayStation Gift Cards USA in Pakistan from PKR 300"."""
    game_category = region_page.game_category
    return (
        f'{game_category.game.name} {game_category.effective_name} {label} '
        f'in Pakistan from PKR {SEO_FROM_PRICE_TOKEN}'
    )


def region_seo_title_with_from_price(region_page, label, region_filter):
    """The region page's title, priced from the cheapest active listing IN
    THAT REGION (the brand page's cheapest may be another region's card)."""
    title = region_page.seo_title or default_region_seo_title(region_page, label)
    return fill_from_price(
        title,
        active_region_listings(region_page.game_category, region_filter.id,
                               region_page.region),
    )


class GameCategoryDetailView(APIView):
    """GET /api/games/{game_slug}/{category_slug}/ — Category with filters + listings."""

    permission_classes = [permissions.AllowAny]

    def get(self, request, game_slug, category_slug):
        return self.browse(request, game_slug, category_slug)

    def browse(self, request, game_slug, category_slug, region_slug=None):
        """The page payload. With `region_slug` (an allow-listed region page,
        /games/<game>/<category>/<region>) the page's Region filter is pinned
        to that value: every listing, option tile and the from-price in the
        title belong to that region, and no query param can unpin it."""
        # Only anonymous responses are cached: authenticated payloads can
        # include owner-only fields (e.g., a seller's delivery instructions).
        browse_cache_key = None
        if not request.user.is_authenticated:
            param_signature = '&'.join(
                f'{key}={value}'
                for key, value in sorted(request.query_params.items())
            )
            browse_cache_key = 'browse:v6:' + hashlib.sha256(
                f'{request_origin_cache_scope(request)}:{game_slug}:'
                f'{category_slug}:{region_slug or ""}:{param_signature}'.encode('utf-8')
            ).hexdigest()
            cached = cache.get(browse_cache_key)
            if cached is not None:
                response = Response(cached)
                response['Cache-Control'] = public_cache_header(BROWSE_CACHE_SECONDS)
                return response

        game_category = GameCategory.resolve_for_slug(
            game_slug,
            category_slug,
            queryset=GameCategory.objects.select_related('game', 'category').prefetch_related(
                'assigned_filters__filter__options',
                'assigned_filters__visible_when_options',
                'region_pages',
            ),
        )
        if game_category is None:
            raise Http404('No game category matches the given query.')

        # Region pages: allow-listed rows whose region is still an option on
        # the page's Region filter. Anything else is a plain 404 — the
        # frontend never links to a region it cannot fix.
        region_filter = region_filter_for(game_category)
        region_labels = region_option_labels(region_filter)
        region_page = None
        if region_slug is not None:
            region_page = next(
                (row for row in game_category.region_pages.all()
                 if row.region == region_slug and region_slug in region_labels),
                None,
            )
            if region_page is None:
                raise Http404('No region page matches the given query.')

        # Build category detail (filters)
        from .serializers import GameCategoryDetailSerializer
        cat_data = GameCategoryDetailSerializer(game_category).data
        if region_page is not None:
            region_label = region_labels[region_page.region]
            cat_data['seo_title'] = region_seo_title_with_from_price(
                region_page, region_label, region_filter)
            cat_data['seo_description'] = region_page.seo_description
            cat_data['seo_body'] = region_page.seo_body
        else:
            cat_data['seo_title'] = seo_title_with_from_price(game_category)

        # Ad-landing semantic filters: /keys game links carry ?method= and
        # ?region= (option VALUES, not filter ids) — map them onto this page's
        # own filters so the page arrives pre-filtered. Method maps first so a
        # dependent Region (visible_when Method=...) can accept the region;
        # explicit ?filter_<id>= params always win over semantic ones. The
        # response echoes the mapping in applied_filters so the client seeds
        # its filter UI to match. On a region page the Region filter is pinned
        # instead: ?region= is ignored and an explicit value for it dropped.
        explicit_values = {
            key.replace('filter_', ''): value
            for key, value in request.query_params.items()
            if key.startswith('filter_') and value
        }
        if region_page is not None:
            explicit_values.pop(str(region_filter.id), None)

        # Buyers only see the options with stock on this page (a dead choice
        # can only answer "nothing in stock" — see filter_options.py); the
        # sell form asks for everything with all_options=1. A value the buyer
        # already picked stays listed so the dropdown shows their choice over
        # the empty state. Trimmed before ?region= maps below, so an ad
        # landing on a dead region arrives unfiltered rather than empty.
        if request.query_params.get('all_options') != '1':
            keep = dict(explicit_values)
            if region_page is not None:
                keep[str(region_filter.id)] = region_page.region
            cat_data['filters'] = trim_filters_to_stock(
                cat_data['filters'], stocked_filter_values(game_category), keep)

        applied_filters = {}
        current_values = dict(explicit_values)
        semantic_params = ('method',) if region_page is not None else ('method', 'region')
        for param in semantic_params:
            wanted = slugify(request.query_params.get(param, ''))[:50]
            if not wanted:
                continue
            for filter_payload in cat_data['filters']:
                if param not in filter_payload['name'].lower():
                    continue
                if str(filter_payload['id']) in explicit_values:
                    continue
                if wanted not in {opt['value']
                                  for opt in filter_payload['options']}:
                    continue
                conditions = filter_payload.get('visible_when') or []
                if conditions and not any(
                        current_values.get(str(c['filter_id'])) == c['option_value']
                        for c in conditions):
                    continue
                applied_filters[str(filter_payload['id'])] = wanted
                current_values[str(filter_payload['id'])] = wanted
                break
        if region_page is not None:
            applied_filters[str(region_filter.id)] = region_page.region
            current_values[str(region_filter.id)] = region_page.region
        cat_data['applied_filters'] = applied_filters

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
            offer_filter_pairs = list(explicit_values.items())
            offer_filter_pairs.extend(applied_filters.items())
            offer_stats_q = Q(listings__status='active')
            best_offer_q = Q(status='active')
            for filter_id, value in offer_filter_pairs:
                offer_stats_q &= Q(listings__filter_values__contains={filter_id: value})
                best_offer_q &= Q(filter_values__contains={filter_id: value})

            # Each option tile links to the listing page of its best offer
            # (the one the buy box would show). Without a real <a href> in
            # the server-rendered HTML those listing pages are orphans,
            # reachable only through the sitemap (Ahrefs 2026-09-02: 1,859).
            best_offer_subquery = (
                Listing.objects.filter(best_offer_q, option=OuterRef('pk'))
                .annotate(delivery_speed_rank=DELIVERY_SPEED_RANK)
                .order_by(*BEST_OFFER_ORDERING)
                .values('id')[:1]
            )

            # annotate() drops CategoryOption.Meta.ordering (Django strips
            # default ordering on aggregation) — re-apply it explicitly so
            # denominations render low -> high.
            options = list(
                game_category.options.annotate(
                    min_price=Min('listings__price', filter=offer_stats_q),
                    offer_count=Count('listings', filter=offer_stats_q),
                    best_listing_id=Subquery(best_offer_subquery),
                ).order_by('order', 'name')
            )
            # Tiles that share an `order` (a card seeded later lands on the
            # same slot number as its neighbour) must still read low -> high:
            # break the tie on the number in the name, not alphabetically,
            # or "10 USD" sorts ahead of "5 USD".
            options.sort(key=option_display_key)
            # Buyers only see buyable options: a tile whose every offer is
            # switched off (supplier out of stock, discontinued pack) is just
            # noise, and it reappears by itself the moment an offer comes back.
            # The sell form passes all_options=1 — a seller may create an offer
            # under a currently-dead option.
            if request.query_params.get('all_options') != '1':
                options = [opt for opt in options if opt.offer_count]

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
                    'best_listing_id': opt.best_listing_id,
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
        for filter_id, value in explicit_values.items():
            # Use __contains for proper dict key matching (numeric-looking keys
            # are misinterpreted as array indices by Django's __ path lookup)
            listings_qs = listings_qs.filter(
                filter_values__contains={filter_id: value}
            )
        for filter_id, value in applied_filters.items():
            listings_qs = listings_qs.filter(
                filter_values__contains={filter_id: value}
            )

        # Instant delivery filter: pre-stocked auto-delivery listings plus
        # platform auto-fulfilled ones (delivery_time flipped to 'Instant').
        if request.query_params.get('instant_delivery') == 'true':
            listings_qs = listings_qs.filter(
                Q(is_auto_delivery=True) | Q(delivery_time='Instant')
            )

        # Search filter: filter by title
        search_q = request.query_params.get('search', '').strip()
        if search_q:
            listings_qs = listings_qs.filter(title__icontains=search_q)

        # Seller filter: only show listings from a specific seller
        seller_username = request.query_params.get('seller', '').strip()
        if seller_username:
            listings_qs = listings_qs.filter(seller__username=seller_username)

        # Sorting / Ordering
        delivery_speed_rank = DELIVERY_SPEED_RANK
        ALLOWED_ORDERINGS = {
            'price_asc': (F('price').asc(), F('created_at').desc()),
            'price_desc': (F('price').desc(), F('created_at').desc()),
            'newest': (F('created_at').desc(),),
            'rating': (F('seller_avg_rating').desc(nulls_last=True), F('created_at').desc()),
            'delivery': (F('delivery_speed_rank').asc(), F('price').asc()),
            # Currency mode: buyers with small budgets sort by entry price
            'min_qty': (F('min_quantity').asc(), F('price').asc(), F('created_at').desc()),
        }
        ordering_param = request.query_params.get('ordering', '').strip()
        if ordering_param in ALLOWED_ORDERINGS:
            listings_qs = listings_qs.annotate(delivery_speed_rank=delivery_speed_rank)
            listings_qs = listings_qs.order_by(*ALLOWED_ORDERINGS[ordering_param])
        elif game_category.listing_mode == 'offer':
            # Best offer first: cheapest, fastest delivery as tiebreaker
            listings_qs = listings_qs.annotate(delivery_speed_rank=delivery_speed_rank)
            listings_qs = listings_qs.order_by(*BEST_OFFER_ORDERING)
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
                'slug': gc.effective_slug,
                'name': gc.effective_name,
                'icon': gc.category.icon,
                'listing_count': gc.listing_count,
                'allow_auto_delivery': gc.allow_auto_delivery,
            }
            for gc in sibling_gcs
        ]

        # "Shop by region" row: the page's allow-listed region pages with live
        # stock counts (the client hides empty ones, like empty sibling tabs).
        # A region page also says which region it is, so the client can pin
        # the filter and draw the Brand › Region breadcrumb, and how much
        # stock the region has — the signal behind its noindex.
        cat_data['region_pages'] = region_pages_payload(game_category, region_filter)
        if region_page is not None:
            cat_data['region_page'] = {
                'region': region_page.region,
                'label': region_label,
                'filter_id': region_filter.id,
                'path': region_page.path,
                'brand_path': f'/games/{game_category.game.slug}/{game_category.effective_slug}',
            }
            cat_data['region_listing_count'] = active_region_listings(
                game_category, region_filter.id, region_page.region).count()

        response = Response(cat_data)
        if browse_cache_key is not None:
            cache.set(browse_cache_key, cat_data, BROWSE_CACHE_SECONDS)
            response['Cache-Control'] = public_cache_header(BROWSE_CACHE_SECONDS)
        else:
            response['Cache-Control'] = 'private'
        return response


class GameCategoryRegionView(GameCategoryDetailView):
    """GET /api/games/{game_slug}/{category_slug}/{region_slug}/ — an
    allow-listed region page: the category payload with the Region filter
    pinned to `region_slug`, its own SEO fields and the region's stock count.
    404 unless a CategoryRegionPage row exists for that region."""

    def get(self, request, game_slug, category_slug, region_slug):
        return self.browse(request, game_slug, category_slug, region_slug=region_slug)


REGION_PAGE_LIST_CACHE_KEY = 'region-pages:v1'
REGION_PAGE_LIST_CACHE_SECONDS = 300


class RegionPageListView(APIView):
    """GET /api/region-pages/ — every allow-listed region page with its stock
    count, for the sitemap (which lists only stocked ones, like empty
    category pages) and the IndexNow catch-up push."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        payload = cache.get(REGION_PAGE_LIST_CACHE_KEY)
        if payload is None:
            payload = all_region_pages_payload()
            cache.set(REGION_PAGE_LIST_CACHE_KEY, payload, REGION_PAGE_LIST_CACHE_SECONDS)
        response = Response(payload)
        response['Cache-Control'] = public_cache_header(REGION_PAGE_LIST_CACHE_SECONDS)
        return response


class SitemapListingsView(APIView):
    """GET /api/sitemap/listings/ — active listing ids + lastmod for sitemap.xml.

    Paginated with limit/offset so the frontend can split listings across as many
    sitemap files as it needs (Google caps a single sitemap at 50,000 URLs).
    Ordered by pk so a listing keeps its page as the catalogue grows — without a
    stable order, one insert would reshuffle every page and churn the sitemaps.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        try:
            limit = int(request.query_params.get('limit', SITEMAP_LISTINGS_MAX_LIMIT))
            offset = int(request.query_params.get('offset', 0))
        except (TypeError, ValueError):
            return Response(
                {'detail': 'limit and offset must be integers.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        limit = max(1, min(limit, SITEMAP_LISTINGS_MAX_LIMIT))
        offset = max(0, offset)

        cache_key = f'{SITEMAP_LISTINGS_CACHE_KEY}:{limit}:{offset}'
        data = cache.get(cache_key)
        if data is None:
            listings = Listing.objects.filter(
                status='active',
                game_category__game__is_active=True,
            ).order_by('pk')

            rows = listings.values('pk', 'updated_at')[offset:offset + limit]
            data = {
                'count': listings.count(),
                'results': [
                    {'id': row['pk'], 'updated_at': row['updated_at'].isoformat()}
                    for row in rows
                ],
            }
            cache.set(cache_key, data, SITEMAP_LISTINGS_CACHE_SECONDS)

        response = Response(data)
        response['Cache-Control'] = f'public, max-age={SITEMAP_LISTINGS_CACHE_SECONDS}'
        return response


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
    """POST /api/auth/logout/ - Blacklist the refresh token and clear auth cookies."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        enforce_trusted_origin(request)
        refresh = request.COOKIES.get(settings.JWT_AUTH_COOKIE_REFRESH)
        if not refresh and isinstance(request.data, dict):
            refresh = request.data.get('refresh')
        if refresh:
            from rest_framework_simplejwt.tokens import RefreshToken
            try:
                RefreshToken(str(refresh)).blacklist()
            except TokenError:
                pass  # already expired or invalid — nothing left to revoke
        response = Response({'message': 'Logged out.'})
        clear_jwt_auth_cookies(response)
        return response


class RegisterView(SuccessCountedThrottleMixin, generics.CreateAPIView):
    """POST /api/auth/register/ — Register a new user (inactive until email verified)."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer
    throttle_scope = 'auth_register'
    attempt_throttle_scope = 'auth_register_attempts'

    def create(self, request, *args, **kwargs):
        enforce_trusted_origin(request)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        self.record_throttled_success()
        attribution.apply_first_touch(user, request.data.get('attribution'))

        # Server-side Meta CompleteRegistration (the pixel doesn't send one).
        meta_capi.queue_registration_event(
            user, method='email',
            tracking=meta_capi.tracking_from_request(request),
        )

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
            user, user_created = self._get_or_create_google_user(
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
            user_created = False

        if user_created:
            attribution.apply_first_touch(user, request.data.get('attribution'))
            # Server-side Meta CompleteRegistration (the pixel doesn't send
            # one). Only for genuinely new users — linking Google to an
            # existing account is a login, not a registration.
            meta_capi.queue_registration_event(
                user, method='google',
                tracking=meta_capi.tracking_from_request(request),
            )

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
                return cls._claim_pending_google_registration(social_account.user), False

            matching_users = list(
                User.objects.select_for_update()
                .filter(email__iexact=google_email)
                .order_by('id')[:2]
            )
            if len(matching_users) > 1:
                raise GoogleAuthLinkError(
                    'More than one account uses this email. Please sign in with your password or contact support.'
                )

            user_created = not matching_users
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
            return user, user_created

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


class CompleteProfileView(SuccessCountedThrottleMixin, APIView):
    """POST /api/auth/complete-profile/ — Set username and accept terms (Google sign-up)."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'complete_profile'
    attempt_throttle_scope = 'complete_profile_attempts'

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

        self.record_throttled_success()

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
                    'game_category__display_name',
                    'game_category__display_slug',
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
                    'slug': row['game_category__display_slug'] or row['game_category__category__slug'],
                    'name': row['game_category__display_name'] or row['game_category__category__name'],
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
            listings_qs = listings_qs.filter(
                Q(game_category__display_slug=category_filter) |
                Q(game_category__category__slug=category_filter,
                  game_category__display_slug='')
            )

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

    GET follows the listing lifecycle (core/listing_lifecycle.py). Every
    response carries a ``lifecycle`` object:

    * active  — the full listing plus ``{"state": "active"}``.
    * paused  — the full listing (status inactive/sold) plus state ``paused``,
      the sibling ``alternatives`` and a ``browse_path``; the frontend renders
      it as out of stock, no buy button.
    * gone / unindexed — ``{"id", "status": "retired", "lifecycle": {...}}``
      with ``redirect_to`` (gone) or nothing (unindexed → 404 on the site).
      Also what a DELETED listing answers, from its RetiredListing record.

    Those last two are HTTP 200 on purpose: the frontend caches this fetch,
    and Next never replaces a cached 200 with a 404, so a non-200 would keep
    the dead listing's page alive indefinitely. Only an id the site has never
    seen is a 404. Owners and staff always get the full listing.
    """
    throttle_methods = {'PUT', 'DELETE'}
    throttle_scope = 'listing_mutation'

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [HasCompletedProfile()]

    def get(self, request, pk):
        listing = Listing.objects.select_related(
            'seller', 'seller__profile', 'option',
            'game_category__game', 'game_category__category'
        ).annotate(
            # Seller rating shown on the detail page's seller card (category
            # pages annotate the same fields for listing cards).
            seller_avg_rating=Subquery(
                Review.objects.filter(seller=OuterRef('seller'))
                .values('seller').annotate(avg=Avg('rating')).values('avg')[:1]
            ),
            seller_review_count=Subquery(
                Review.objects.filter(seller=OuterRef('seller'))
                .values('seller').annotate(cnt=Count('id')).values('cnt')[:1]
            ),
        ).filter(pk=pk).first()

        if listing is None:
            record = RetiredListing.objects.filter(pk=pk).first()
            if record is None:
                raise Http404
            return Response(listing_lifecycle.gone_payload(
                record.listing_id, listing_lifecycle.lifecycle_for_retired(record),
            ))

        is_insider = request.user.is_authenticated and (
            request.user.is_staff or listing.seller_id == request.user.id
        )
        lifecycle = {'state': 'active'}
        if listing.status != 'active':
            if listing.unavailable_since is None:
                # Switched off by a bulk update that skipped save(): the
                # out-of-stock clock starts at first sight.
                listing_lifecycle.stamp_unavailable(listing)
            lifecycle = listing_lifecycle.lifecycle_for_listing(listing)
            if lifecycle['state'] != 'paused' and not is_insider:
                return Response(listing_lifecycle.gone_payload(listing.pk, lifecycle))
        elif listing.unavailable_since is not None or listing.retire_reason:
            listing_lifecycle.clear_stale_stamp(listing)

        data = ListingSerializer(
            listing,
            context={
                'request': request,
                'filter_option_display_map': build_listing_filter_display_map([listing]),
                # Detail page only: expose required checkout inputs for
                # auto-fulfilled top-ups (avoids N+1 on category pages).
                'include_checkout_fields': True,
                # Detail page only: per-listing reviews for Product JSON-LD.
                'include_listing_reviews': True,
            },
        ).data
        if lifecycle['state'] == 'paused':
            lifecycle['alternatives'] = listing_lifecycle.alternatives(listing)
        data['lifecycle'] = lifecycle
        return Response(data)

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
            latest_message_type=Subquery(latest_message.values('message_type')[:1]),
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
        updated = conversation.messages.filter(is_read=False).exclude(
            sender=request.user
        ).update(is_read=True)
        if updated:
            cache.delete(chat_unread_cache_key(request.user.pk))

        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_MESSAGE_PAGE_SIZE,
            max_limit=MAX_MESSAGE_PAGE_SIZE,
        )
        messages_qs = conversation.messages.select_related(
            'sender', 'referenced_listing', 'order__buyer', 'order__seller'
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
        maybe_answer_guard_command(message)
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
        cache_key = chat_unread_cache_key(request.user.pk)
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
        return Response({
            'balance': str(wallet.balance),
            'jazzcash_enabled': settings.JAZZCASH_ENABLED,
            'checkout_service_fee': str(settings.CHECKOUT_SERVICE_FEE_PKR),
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
                account_title=encrypt_sensitive_text(data.get('account_title', '')),
                account_details=encrypt_sensitive_text(data.get('account_details', '')),
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

        # Duplicate-charge guard: a top-up they started moments ago is still
        # waiting for their MPIN — resume it instead of pushing a second
        # prompt they might also approve. Same payload as a fresh initiation,
        # so the frontend just polls the existing payment.
        existing = find_reusable_pending_payment(user=request.user, purpose='topup')
        if existing is not None:
            return Response(JazzCashPaymentSerializer(existing).data)

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


def validate_jazzcash_purchase(listing, qty, *, wallet_balance, checkout_fields):
    """Fail fast on obviously invalid JazzCash direct-buy initiations — shared
    by the logged-in and guest checkout views. The authoritative checks run
    again (with locks) when the confirmed payment executes the purchase.

    Returns ``(charge, checkout_info, None)`` on success or
    ``(None, None, error_message)``.
    """
    if listing.status != 'active':
        return None, None, 'This listing is no longer available.'
    is_currency = listing.game_category.listing_mode == 'currency'
    unit = listing.game_category.unit_name.strip() if is_currency else ''
    unit_suffix = f' {unit}' if unit else ''
    if is_currency:
        if qty < listing.min_quantity:
            return None, None, f'Minimum purchase is {listing.min_quantity}{unit_suffix}.'
    elif qty > MAX_PURCHASE_QUANTITY:
        return None, None, MAX_PURCHASE_QUANTITY_ERROR
    if listing.quantity is not None and qty > listing.quantity:
        return None, None, f'Only {listing.quantity}{unit_suffix} available.'

    total = listing.price * qty
    if total <= 0:
        return None, None, 'Invalid listing price.'
    if total > Decimal('99999999.99'):
        return None, None, 'Order total is too large — please buy a smaller amount.'
    # The purchase that executes once the payment confirms charges the
    # wallet the fee-inclusive amount, so the shortfall must cover it too.
    buyer_charge = total + settings.CHECKOUT_SERVICE_FEE_PKR

    if wallet_balance >= buyer_charge:
        return None, None, 'You have enough wallet balance for this order — pay with your wallet.'
    charge = max(buyer_charge - wallet_balance, settings.JAZZCASH_MIN_PAYMENT_PKR)
    if charge > settings.JAZZCASH_MAX_PAYMENT_PKR:
        return None, None, (
            f'JazzCash payments are limited to PKR {settings.JAZZCASH_MAX_PAYMENT_PKR:,.0f} '
            'per transaction. Please contact support for larger orders.'
        )

    # Auto-fulfilled top-ups need the buyer's player/user ID up front — the
    # purchase executes later (IPN/reconcile), when we can no longer ask the
    # buyer for anything.
    checkout_info, checkout_error = prepare_fazer_checkout(listing, checkout_fields)
    if checkout_error:
        return None, None, checkout_error
    return charge, checkout_info, None


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

        # Duplicate-charge guard: a payment for this listing they started
        # moments ago is still waiting for their MPIN — resume it instead of
        # charging again (a retrying buyer approved two prompts and paid twice
        # for one item, 2026-07-18). Checked before revalidating: the
        # authoritative checks run when the confirmed payment executes anyway,
        # and this skips a needless repeat Fazer ID validation.
        existing = find_reusable_pending_payment(
            user=request.user, purpose='purchase', listing=listing,
        )
        if existing is not None:
            return Response(JazzCashPaymentSerializer(existing).data)

        if listing.seller == request.user:
            return Response({'error': 'You cannot buy your own listing.'}, status=400)

        wallet, _ = Wallet.objects.get_or_create(user=request.user)
        charge, checkout_info, error = validate_jazzcash_purchase(
            listing, qty,
            wallet_balance=wallet.balance,
            checkout_fields=data.get('checkout_fields'),
        )
        if error:
            return Response({'error': error}, status=400)

        try:
            payment = start_jazzcash_payment(
                user=request.user,
                purpose='purchase',
                amount=charge,
                mobile_number=data['mobile_number'],
                description='GamesBazaar order payment',
                listing=listing,
                listing_quantity=qty,
                checkout_payload=(
                    encrypt_sensitive_text(json.dumps(checkout_info, ensure_ascii=False))
                    if checkout_info else ''
                ),
                # The purchase may execute from IPN/reconcile long after the
                # buyer left — snapshot their attribution data now.
                meta_tracking=json.dumps(meta_capi.tracking_from_request(request)),
            )
        except jazzcash.JazzCashError:
            return _jazzcash_disabled_response()

        return Response(
            JazzCashPaymentSerializer(payment).data,
            status=status.HTTP_201_CREATED,
        )


def _create_guest_user(email):
    """Create the silent account behind a guest checkout.

    Active immediately (JWT auth refuses inactive users) with an unusable
    password — the buyer claims it later via Forgot Password. Terms count as
    accepted: the guest checkout UI states that placing the order accepts
    them. Username collision loop mirrors the Google sign-in one.
    """
    import re
    import secrets as _secrets

    base_username = re.sub(r'[^a-zA-Z0-9_]', '', email.split('@')[0])[:20] or 'buyer'
    for _ in range(10):
        username = base_username
        while User.objects.filter(username__iexact=username).exists():
            username = f'{base_username}_{_secrets.token_hex(3)}'
        try:
            with db_transaction.atomic():
                user = User.objects.create_user(
                    username=username, email=email, password=None,
                )
            break
        except IntegrityError:
            continue
    else:
        raise IntegrityError('Could not create a unique username for guest checkout.')

    profile = user.profile
    profile.has_accepted_terms = True
    profile.save(update_fields=['has_accepted_terms'])
    return user


class GuestJazzCashBuyView(SuccessCountedThrottleMixin, APIView):
    """POST /api/payments/jazzcash/guest-buy/ — Guest checkout.

    A buyer with no account pays at the Buy button: validate the purchase,
    silently create an active account for their email (unusable password —
    claimed later via Forgot Password), sign them in with the normal JWT
    cookies, and start the same JazzCash direct-buy flow the logged-in
    checkout uses. From the cookies onward this IS a normal logged-in
    session — payment polling, the order page and any retry all take the
    authenticated paths, which is also why a retry never hits this endpoint
    again (the email now exists and would be refused).

    Success is charged to the throttle only when an account was actually
    created; rejected forms cost nothing (attempts still capped).
    """
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'guest_checkout'
    attempt_throttle_scope = 'guest_checkout_attempts'

    def post(self, request):
        enforce_trusted_origin(request)
        if request.user.is_authenticated:
            return Response(
                {'error': 'You are already signed in — use the normal checkout.'},
                status=400,
            )
        if not settings.JAZZCASH_ENABLED:
            return _jazzcash_disabled_response()

        serializer = JazzCashGuestBuyInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        email = data['email'].strip().lower()
        qty = data.get('quantity', 1)

        try:
            listing = (
                Listing.objects.select_related('seller', 'game_category__category')
                .get(id=data['listing_id'])
            )
        except Listing.DoesNotExist:
            return Response({'error': 'This listing is no longer available.'}, status=400)

        # No claiming someone else's account by typing their email — the
        # buyer must log in to prove it's theirs (Forgot Password if needed).
        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {'error': 'This email already has a GamesBazaar account — log in to finish your order.',
                 'code': 'account_exists'},
                status=409,
            )

        charge, checkout_info, error = validate_jazzcash_purchase(
            listing, qty,
            wallet_balance=Decimal('0.00'),
            checkout_fields=data.get('checkout_fields'),
        )
        if error:
            return Response({'error': error}, status=400)

        # Everything checks out — only now does the account exist.
        user = _create_guest_user(email)
        attribution.apply_first_touch(user, request.data.get('attribution'))
        self.record_throttled_success()
        tracking = meta_capi.tracking_from_request(request)
        meta_capi.queue_registration_event(user, method='guest_checkout', tracking=tracking)
        send_guest_account_email(user)

        payment = None
        try:
            payment = start_jazzcash_payment(
                user=user,
                purpose='purchase',
                amount=charge,
                mobile_number=data['mobile_number'],
                description='GamesBazaar order payment',
                listing=listing,
                listing_quantity=qty,
                checkout_payload=(
                    encrypt_sensitive_text(json.dumps(checkout_info, ensure_ascii=False))
                    if checkout_info else ''
                ),
                # The purchase may execute from IPN/reconcile long after the
                # buyer left — snapshot their attribution data now.
                meta_tracking=json.dumps(tracking),
            )
        except jazzcash.JazzCashError:
            pass

        # The account exists either way — sign the buyer in so retries and
        # polling use the authenticated paths (a retry here would 409).
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = add_profile_setup_token_claim(RefreshToken.for_user(user), user)
        if payment is not None:
            response = Response(
                {'payment': JazzCashPaymentSerializer(payment).data},
                status=status.HTTP_201_CREATED,
            )
        else:
            response = Response(
                {'error': JAZZCASH_UNAVAILABLE_ERROR, 'account_created': True},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        set_jwt_auth_cookies(
            response,
            access=str(refresh.access_token),
            refresh=str(refresh),
        )
        return response


class CheckoutConfigView(APIView):
    """GET /api/checkout/config/ — public checkout facts for guests.

    The logged-in flow reads the same two fields from /api/wallet/; guests
    have no wallet, and without these the guest UI could neither show the
    service fee nor know whether JazzCash is up.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({
            'jazzcash_enabled': settings.JAZZCASH_ENABLED,
            'checkout_service_fee': str(settings.CHECKOUT_SERVICE_FEE_PKR),
        })


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

        # Gateway audits ask for the complete IPN exchange, so keep the full
        # notification and our acknowledgement in the logs.
        logger.info('JazzCash IPN request: %s',
                    json.dumps(data, sort_keys=True, default=str))

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
                gateway_amount=data.get('pp_Amount'),
            )

        ack = self._ack('000', 'IPN received successfully')
        logger.info('JazzCash IPN response: %s', json.dumps(ack, sort_keys=True))
        return Response(ack)


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


def execute_listing_purchase(*, buyer, listing_id, quantity, checkout_info=None,
                             meta_tracking=None):
    """Run the full purchase flow for a listing, paying from the buyer's wallet.

    Shared by BuyListingView and the JazzCash direct-buy flow (which credits
    the wallet first, then purchases). Returns ``(order, None)`` on success or
    ``(None, error_message)`` when the purchase cannot proceed; error paths
    never mutate state.

    ``checkout_info`` carries buyer-supplied checkout data (e.g. the player
    ID for auto-fulfilled top-ups) — stored encrypted on the order and used
    by the Fazer fulfillment engine after commit.

    ``meta_tracking`` carries browser attribution data for the server-side
    Meta Purchase event (queued here, delivered after commit) — every
    completed sale flows through this function, so this is the one place
    Meta learns about all of them.
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

        # Currency listings are bought in units (e.g., Millions of coins) and
        # honour the seller's minimum; other modes keep the per-order cap.
        is_currency = listing.game_category.listing_mode == 'currency'
        unit = listing.game_category.unit_name.strip() if is_currency else ''
        unit_suffix = f' {unit}' if unit else ''
        if is_currency:
            if qty < listing.min_quantity:
                return None, f'Minimum purchase is {listing.min_quantity}{unit_suffix}.'
        elif qty > MAX_PURCHASE_QUANTITY:
            return None, MAX_PURCHASE_QUANTITY_ERROR

        if listing.quantity is not None and qty > listing.quantity:
            return None, f'Only {listing.quantity}{unit_suffix} available.'

        total = listing.price * qty
        if total <= 0:
            return None, 'Invalid listing price.'
        # Order money fields hold 10 digits (max 99,999,999.99 PKR).
        if total > Decimal('99999999.99'):
            return None, 'Order total is too large — please buy a smaller amount.'
        # Flat checkout service fee — charged on top of the item total on
        # every payment method, refunded with the total if the order is
        # cancelled. Snapshotted on the order so a later fee change never
        # alters what an old order refunds.
        service_fee = settings.CHECKOUT_SERVICE_FEE_PKR
        buyer_charge = total + service_fee

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

        # Offline activation: the listing's shared Steam account is handed
        # over instantly on every purchase (evergreen — nothing consumed);
        # the buyer can then request Steam Guard codes on demand.
        offline_account = None
        if not is_auto and listing.offline_account_id:
            account = listing.offline_account
            if account.enabled:
                offline_account = account
                delivery_note = encrypt_sensitive_text(account.delivery_text())
                initial_status = 'delivered'
                delivered_at = timezone.now()
        delivered_instantly = is_auto or offline_account is not None

        # Fazer auto-fulfillment: linked listing + global toggle on. The
        # link is fetched with its own query — a nullable reverse OneToOne
        # cannot join into the select_for_update above. No HTTP happens
        # inside this transaction; the supplier call runs after commit.
        fazer_link = None
        if not delivered_instantly and fulfillment.autofulfill_enabled():
            fazer_link = fulfillment.get_active_link(listing)

        wallet = get_or_create_locked_wallet(buyer)

        if wallet.balance < buyer_charge:
            return None, 'Insufficient wallet balance.'

        category = listing.game_category.category
        rate = get_commission_rate(listing.seller, category)
        commission = (total * rate / Decimal('100')).quantize(Decimal('0.01'))
        seller_receives = total - commission

        # Deduct from buyer only after all purchase validations have passed.
        wallet.balance -= buyer_charge
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

        # Snapshot the buyer's first-touch source so the admin order list
        # answers "where did this sale come from?" without a profile join
        # (and keeps answering it even if the profile is ever edited).
        try:
            buyer_source = buyer.profile.acquisition_source
        except UserProfile.DoesNotExist:
            buyer_source = ''

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
            service_fee=service_fee,
            buyer_source=buyer_source,
            status=initial_status,
            was_auto_delivery=delivered_instantly,
            delivery_note=delivery_note,
            delivered_at=delivered_at,
            delivery_instructions_snapshot=listing.delivery_instructions.strip(),
        )

        # Log transaction
        fee_note = f' incl. PKR {service_fee} service fee' if service_fee > 0 else ''
        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type='purchase',
            amount=buyer_charge,
            balance_after=wallet.balance,
            description=f'Purchase: {listing.title} (x{qty}{unit_suffix}){fee_note}',
            reference_id=f'order_{order.pk}',
        )
        if service_fee > 0:
            record_platform_ledger_once(
                entry_type='service_fee_collected',
                amount=service_fee,
                description=f'Service fee: {listing.title} (x{qty}{unit_suffix})',
                reference_id=f'order_{order.pk}',
            )

        # Shop flow: a delivered order IS a complete order — no confirmation
        # step, no payout hold. Credit the house seller in the same
        # transaction so a crash can never strand a paid-but-uncredited sale.
        if delivered_instantly:
            complete_order_now(order)

        conversation, _ = get_or_create_private_conversation(buyer, listing.seller)

        order.conversation = conversation
        order.save(update_fields=['conversation'])

        # Server-side Meta Purchase event (sent after commit, deduplicated
        # against the browser pixel via the shared purchase-<id> event ID).
        meta_capi.queue_purchase_event(order, buyer=buyer, tracking=meta_tracking)

        # Queue automatic fulfillment (order stays 'pending'; the supplier
        # call happens after this transaction commits).
        fazer_task = None
        if fazer_link is not None:
            if checkout_info:
                order.checkout_payload = encrypt_sensitive_text(
                    json.dumps(checkout_info, ensure_ascii=False)
                )
                order.save(update_fields=['checkout_payload'])
            fazer_task = fulfillment.build_task_for_order(order, fazer_link)

        # Announce the purchase in the buyer↔seller chat
        qty_part = f' (x{qty}{unit_suffix})' if qty > 1 or is_currency else ''
        if delivered_instantly:
            paid_content = (
                f'{buyer.username} has paid for order #{order.order_number} — '
                f'{listing.title}{qty_part}. The order was delivered automatically — '
                f'{buyer.username}, please check the delivery details.'
            )
        elif fazer_task is not None:
            if fazer_task.kind == 'gift':
                arrival = ('the game will be sent to your Steam account as a '
                           'gift within a few minutes')
            elif fazer_task.kind == 'topup':
                arrival = 'your top-up will arrive in this chat within a few minutes'
            else:
                arrival = 'your code will arrive in this chat within a few minutes'
            paid_content = (
                f'{buyer.username} has paid for order #{order.order_number} — '
                f'{listing.title}{qty_part}. This order is delivered automatically — '
                f'{arrival}.'
            )
        else:
            paid_content = (
                f'{buyer.username} has paid for order #{order.order_number} — '
                f'{listing.title}{qty_part}. {listing.seller.username}, please deliver '
                f'the order. {buyer.username}, your delivery will arrive in this chat.'
            )
        post_order_chat_message(order, event='order_paid', content=paid_content, sender=buyer)

        # Record the buyer's player/user ID or invite link in chat so a
        # manual fallback (seller fulfilling by hand) has it in the usual place.
        if (fazer_task is not None and fazer_task.kind in ('topup', 'gift')
                and checkout_info):
            id_bits = ', '.join(
                str(v) for v in (checkout_info.get('fields') or {}).values()
                if str(v).strip()
            )
            if id_bits:
                player_name = str(checkout_info.get('player_name') or '')
                name_part = f' ({player_name})' if player_name else ''
                id_label = ('Steam friend invite link'
                            if fazer_task.kind == 'gift' else 'Player/User ID')
                post_order_chat_message(
                    order,
                    content=f'{id_label} provided at checkout: {id_bits}{name_part}',
                    sender=buyer,
                )

        # Hand over auto-delivery data. Seller instructions are NOT re-posted
        # into chat — the buyer already saw them on the listing/checkout and
        # the order page shows the snapshot.
        if delivered_instantly:
            post_order_chat_message(
                order,
                message_type='delivery',
                sender=listing.seller,
                content=delivery_note,  # already encrypted above
            )

        # Notify seller about new order
        create_notification(
            recipient=listing.seller,
            notification_type='new_order',
            title=f'New order from {buyer.username}',
            message=f'{buyer.username} purchased "{listing.title}" (x{qty}{unit_suffix}) for PKR {total}.',
            order=order,
        )

        # For auto-delivery, also notify buyer that it's delivered
        if delivered_instantly:
            create_notification(
                recipient=buyer,
                notification_type='order_delivered',
                title='Your order has been automatically delivered!',
                message=f'Your order "{listing.title}" has been automatically delivered. Check your order for the delivery details.',
                order=order,
            )

        # Kick off the supplier purchase once this transaction commits (the
        # 1-minute fulfillment timer is the safety net if the worker dies).
        if fazer_task is not None:
            fulfillment.schedule_fulfillment_after_commit(fazer_task.pk)

    return order, None


DEFAULT_TOPUP_CHECKOUT_FIELDS = [{'key': 'player_id', 'label': 'Player ID'}]


def prepare_fazer_checkout(listing, raw_fields):
    """For auto-fulfilled top-up and Steam-gift listings: require and verify
    the buyer's player ID / invite link BEFORE any money moves. Returns
    ``(checkout_info, error)`` — both ``None`` when the listing needs no
    checkout info. Runs outside any transaction (it calls the supplier);
    verification fails open so a supplier outage never blocks a purchase
    (fulfillment then falls back to manual).
    """
    if listing is None or not fulfillment.autofulfill_enabled():
        return None, None
    link = fulfillment.get_active_link(listing)
    if link is None or link.kind not in ('topup', 'gift'):
        return None, None

    if link.kind == 'gift':
        spec = link.checkout_fields or fulfillment.GIFT_CHECKOUT_FIELDS
    else:
        spec = link.checkout_fields or DEFAULT_TOPUP_CHECKOUT_FIELDS
    raw_fields = raw_fields or {}
    fields = {}
    for field in spec:
        key = str(field.get('key') or 'player_id')
        label = str(field.get('label') or 'Player ID')
        value = str(raw_fields.get(key, '')).strip()[:100]
        if not value:
            return None, f'{label} is required for this item.'
        # Dropdown fields (server/platform pickers) only accept the values the
        # supplier listed — anything else would fail at fulfillment.
        options = field.get('options') or []
        if options:
            allowed = {str(o.get('value', '')) for o in options
                       if isinstance(o, dict)}
            if value not in allowed:
                return None, f'Please pick a valid {label} from the list.'
        fields[key] = value

    if link.kind == 'gift':
        # Format-only check — catches profile URLs before money moves; a
        # dead/mistyped invite link still fails at fulfillment and falls
        # back to manual.
        if not fulfillment.GIFT_INVITE_URL_RE.search(fields.get('invite_url', '')):
            return None, (
                'Please paste your Steam friend INVITE link — open Steam → '
                'Friends → Add a Friend → copy your Invite Link (it looks '
                'like https://s.team/p/...). A profile link cannot receive '
                'a gift.'
            )
        return {'fields': fields}, None

    player_name = ''
    try:
        # Short (connect, read) timeout: this runs inside a checkout POST on
        # daphne's shared sync thread — a hung supplier must not stall the
        # site for the full FAZER_REQUEST_TIMEOUT_SECONDS budget.
        result = fazer.validate_topup_id(link.fazer_category_id, fields,
                                         timeout=(5, 10))
    except fazer.FazerError:
        # Unreachable OR "ID validation is not available for this
        # category_id" (most categories, verified live 2026-07-11) — never
        # block the purchase on the soft check; a truly wrong ID fails at
        # fulfillment and falls back to manual.
        result = None
    if result is not None:
        if result.get('valid') is False:
            return None, ('This ID was not found — please double-check it '
                          'and try again.')
        player_name = str(result.get('player_name') or '')[:100]

    return {'fields': fields, 'player_name': player_name}, None


class BuyListingView(APIView):
    """POST /api/orders/buy/ — Purchase a listing. Deducts from buyer wallet (escrow)."""
    permission_classes = [HasCompletedProfile]

    def post(self, request):
        serializer = BuyListingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        listing = Listing.objects.filter(id=data['listing_id']).first()
        checkout_info, checkout_error = prepare_fazer_checkout(
            listing, data.get('checkout_fields'),
        )
        if checkout_error:
            return Response({'error': checkout_error}, status=400)

        order, error = execute_listing_purchase(
            buyer=request.user,
            listing_id=data['listing_id'],
            quantity=data.get('quantity', 1),
            checkout_info=checkout_info,
            meta_tracking=meta_capi.tracking_from_request(request),
        )
        if error:
            return Response({'error': error}, status=400)

        return Response(OrderSerializer(order, context={'request': request}).data, status=201)


class WhatsAppCheckoutView(ScopedPostThrottleMixin, APIView):
    """POST /api/whatsapp/checkout/ — a Buy-on-WhatsApp (or float icon) click.

    Mints a reference code and snapshots the browser's Meta attribution data
    before the visitor leaves for WhatsApp — the last moment the pixel
    cookies are within reach. Open to guests: WhatsApp buyers usually have no
    account. If the chat turns into a sale, the admin completes the row
    (WhatsAppCheckoutAdmin), which is when the Meta Purchase event fires.
    """
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'whatsapp_checkout'

    def post(self, request):
        enforce_trusted_origin(request)

        listing = None
        listing_id = request.data.get('listing_id')
        if listing_id is not None:
            try:
                listing = Listing.objects.get(pk=int(listing_id))
            except (TypeError, ValueError, Listing.DoesNotExist):
                return Response({'error': 'This listing is no longer available.'}, status=404)

        try:
            quantity = max(1, int(request.data.get('quantity', 1)))
        except (TypeError, ValueError):
            quantity = 1
        quantity = min(quantity, 100_000_000)

        amount = None
        if listing is not None:
            amount = listing.price * quantity
            if amount > Decimal('9999999999.99'):  # DecimalField(12, 2) cap
                amount = None

        # Meta wants a full event_source_url; trust only the path from the
        # client and rebuild the rest.
        page = str(request.data.get('page') or '')[:400]
        page_url = ''
        if page.startswith('/') and not page.startswith('//'):
            page_url = f'{settings.PUBLIC_SITE_URL}{page}'
        elif listing is not None:
            page_url = f'{settings.PUBLIC_SITE_URL}/listing/{listing.pk}'

        tracking = meta_capi.tracking_from_request(request)
        checkout = WhatsAppCheckout.objects.create(
            listing=listing,
            listing_title=listing.title if listing else '',
            quantity=quantity if listing else 1,
            amount=amount,
            page_url=page_url,
            user=request.user if request.user.is_authenticated else None,
            meta_tracking=json.dumps(tracking),
        )
        meta_capi.queue_whatsapp_contact_event(
            checkout, user=checkout.user, tracking=tracking,
        )
        return Response({'ref': checkout.ref}, status=201)


class ListingViewTrackView(ScopedPostThrottleMixin, APIView):
    """POST /api/track/listing-view/ — server-side half of the ViewContent pair.

    The browser pixel fires ViewContent with a client-minted event ID and
    reports the same ID here; we send the matching Conversions API event so
    Meta dedups the pair. Ad blockers stop Facebook's domains, not ours, so
    blocked browsers are counted through this path alone. Fire-and-forget:
    always 204, never an error the frontend would have to handle.
    """
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'listing_view_track'

    def post(self, request):
        enforce_trusted_origin(request)
        if not meta_capi.is_configured():
            return Response(status=204)

        event_id = str(request.data.get('event_id') or '')
        if not (
            event_id.startswith('vc-')
            and len(event_id) <= 64
            and all(ch.isalnum() or ch == '-' for ch in event_id)
        ):
            return Response(status=204)

        try:
            listing = Listing.objects.get(pk=int(request.data.get('listing_id')))
        except (TypeError, ValueError, Listing.DoesNotExist):
            return Response(status=204)

        meta_capi.queue_view_content_event(
            listing,
            event_id=event_id,
            user=request.user if request.user.is_authenticated else None,
            tracking=meta_capi.tracking_from_request(request),
        )
        return Response(status=204)


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
            'listing', 'buyer', 'seller', 'conversation',
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
        # Status counts (unfiltered) for tab badges
        status_counts = Order.objects.filter(buyer=request.user).values('status').annotate(
            count=Count('id')
        )
        counts = {item['status']: item['count'] for item in status_counts}

        return Response({
            'orders': OrderSerializer(
                orders,
                many=True,
                context={'request': request},
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
            'listing', 'buyer', 'seller', 'conversation',
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
                context={'request': request},
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
                'listing', 'listing__offline_account', 'buyer', 'seller',
                'conversation', 'review', 'review__reviewer',
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

        return Response(OrderSerializer(
            order,
            context={'request': request, 'include_guard_code': True},
        ).data)


class OrderGuardCodeView(ScopedPostThrottleMixin, APIView):
    """POST /api/orders/<id>/guard-code/ — Buyer requests the current Steam
    Guard code for an offline-activation order. The code is returned and
    also posted into the order chat."""
    permission_classes = [HasCompletedProfile]
    throttle_scope = 'guard_code'

    def post(self, request, order_ref):
        order = get_order_by_reference_or_404(
            Order.objects.select_related(
                'listing__offline_account', 'buyer', 'seller',
            ),
            order_ref,
            buyer=request.user,
        )
        payload, error = issue_guard_code(order)
        if error:
            return Response({'error': error}, status=400)
        return Response(payload)


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
            order.delivery_note = encrypt_sensitive_text(delivery_note)
            order.delivered_at = timezone.now()
            order.save(update_fields=['delivery_note', 'delivered_at', 'updated_at'])
            # Shop flow: delivered means done — complete and credit the
            # house seller immediately.
            complete_order_now(order)

            post_order_chat_message(
                order,
                event='order_delivered',
                sender=request.user,
                content=(
                    f'{request.user.username} has delivered order #{order.order_number}. '
                    f'{order.buyer.username}, please check the delivery details.'
                ),
            )
            if delivery_note:
                post_order_chat_message(
                    order,
                    message_type='delivery',
                    sender=request.user,
                    content=order.delivery_note,  # encrypted above
                )

            # Notify buyer that seller delivered
            create_notification(
                recipient=order.buyer,
                notification_type='order_delivered',
                title='Your order has been delivered',
                message=f'{request.user.username} marked order "{order.listing_title}" as delivered.',
                order=order,
            )

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

            was_completed = order.status == 'completed'

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

            # Refund buyer the full amount, service fee included.
            refund_total = order.total_amount + order.service_fee
            buyer_wallet = get_or_create_locked_wallet(order.buyer)
            buyer_wallet.balance += refund_total
            buyer_wallet.save(update_fields=['balance', 'updated_at'])

            WalletTransaction.objects.create(
                wallet=buyer_wallet,
                transaction_type='refund',
                amount=refund_total,
                balance_after=buyer_wallet.balance,
                description=f'Refund: {order.listing_title} (x{order.quantity})',
                reference_id=f'order_{order.pk}',
            )
            if order.service_fee > 0:
                record_platform_ledger_once(
                    entry_type='service_fee_reversed',
                    amount=-order.service_fee,
                    description=f'Service fee reversed: {order.listing_title} (x{order.quantity})',
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

            # A refunded sale no longer counts as sold — roll back the
            # "N sold" counter and the cached profile Sales stat.
            if was_completed:
                if order.listing_id:
                    Listing.objects.filter(
                        pk=order.listing_id, sales_count__gt=0,
                    ).update(sales_count=F('sales_count') - 1)
                db_transaction.on_commit(
                    lambda sid=order.seller_id: cache.delete(seller_profile_cache_key(sid))
                )

            post_order_chat_message(
                order,
                event='order_refunded',
                sender=request.user,
                content=(
                    f'{order.seller.username} has issued a refund to '
                    f'{order.buyer.username} on order #{order.order_number}. The full '
                    f'amount is back in {order.buyer.username}\'s wallet.'
                ),
            )

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

def validate_review_images(files, existing_count=0):
    """Validate uploaded review photos and return (optimized_list, error).

    ``existing_count`` is how many photos the review will already have after
    any removals, so the cap holds across edits too.
    """
    if existing_count + len(files) > MAX_REVIEW_IMAGES:
        return None, f'You can attach at most {MAX_REVIEW_IMAGES} photos.'
    for image in files:
        validation_error = validate_uploaded_image(image)
        if validation_error:
            return None, validation_error
    return [optimize_uploaded_image(image, preset='review') for image in files], None


class CreateReviewView(APIView):
    """POST /api/reviews/ — Submit a review for a completed order.

    Accepts multipart form data with up to MAX_REVIEW_IMAGES photos under
    ``images`` (plain JSON still works for photo-less reviews).
    """
    permission_classes = [HasCompletedProfile]

    def post(self, request):
        serializer = CreateReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        images, validation_error = validate_review_images(request.FILES.getlist('images'))
        if validation_error:
            return Response({'error': validation_error}, status=400)

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

                for image in images:
                    ReviewImage.objects.create(review=review, image=image)

                post_order_chat_message(
                    order,
                    event='review_posted',
                    sender=request.user,
                    content=(
                        f'{request.user.username} has left a {data["rating"]}-star '
                        f'review on order #{order.order_number}.'
                    ),
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

        # The sitewide strip shows the newest reviews — let it pick this one up
        # now instead of at the end of its 5-minute window.
        cache.delete(SITE_REVIEWS_CACHE_KEY)
        cache.delete(seller_profile_cache_key(review.seller_id))

        return Response(ReviewSerializer(review, context={'request': request}).data, status=201)


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

        # Photo changes: ``remove_image_ids`` drops existing photos,
        # ``images`` adds new ones. The cap applies to the final set.
        if hasattr(request.data, 'getlist'):
            remove_ids = request.data.getlist('remove_image_ids')
        else:
            remove_ids = request.data.get('remove_image_ids') or []
        remove_ids = {str(value) for value in remove_ids}
        existing_images = list(review.images.all())
        removed_images = [img for img in existing_images if str(img.id) in remove_ids]
        kept_count = len(existing_images) - len(removed_images)

        new_images, validation_error = validate_review_images(
            request.FILES.getlist('images'), existing_count=kept_count,
        )
        if validation_error:
            return Response({'error': validation_error}, status=400)

        review.rating = data['rating']
        review.comment = data.get('comment', '')
        review.updated_at = timezone.now()
        review.save(update_fields=['rating', 'comment', 'updated_at'])

        for removed in removed_images:
            removed.image.delete(save=False)
            removed.delete()
        for image in new_images:
            ReviewImage.objects.create(review=review, image=image)

        post_order_chat_message(
            review.order,
            event='review_updated',
            sender=request.user,
            content=(
                f'{request.user.username} has updated their review on order '
                f'#{review.order.order_number} — now rated {data["rating"]}/5.'
            ),
        )

        # Invalidate seller profile cache
        cache.delete(seller_profile_cache_key(review.seller_id))
        cache.delete(SITE_REVIEWS_CACHE_KEY)

        return Response(ReviewSerializer(review, context={'request': request}).data)


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
        cache.delete(seller_profile_cache_key(review.seller_id))

        return Response(ReviewSerializer(review, context={'request': request}).data)


class SellerReviewsView(APIView):
    """GET /api/reviews/seller/<username>/ — Get all reviews for a seller."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, username):
        seller = get_object_or_404(User, username=username)
        reviews_qs = Review.objects.filter(
            seller=seller
        ).select_related('reviewer', 'order', 'whatsapp_checkout').prefetch_related('images')
        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_REVIEW_PAGE_SIZE,
            max_limit=MAX_REVIEW_PAGE_SIZE,
        )
        total_count = reviews_qs.count()
        reviews = reviews_qs[offset:offset + limit]
        return Response({
            'reviews': ReviewSerializer(reviews, many=True, context={'request': request}).data,
            'pagination': get_pagination_payload(total_count, limit, offset),
        })


class AllReviewsView(APIView):
    """GET /api/reviews/all/ — every review on the site, newest first.

    Feeds the public /reviews page. Unlike the marquee strip (a positive-only
    showcase), this is the honest full list: every rating, order and WhatsApp
    reviews alike, with photos and seller replies.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        limit, offset = get_pagination_params(
            request,
            default_limit=DEFAULT_REVIEW_PAGE_SIZE,
            max_limit=MAX_REVIEW_PAGE_SIZE,
        )

        # One query yields the distribution, the total, and the average.
        rating_distribution = {str(i): 0 for i in range(1, 6)}
        total = 0
        weighted = 0
        for row in Review.objects.values('rating').annotate(count=Count('id')):
            rating_distribution[str(row['rating'])] = row['count']
            total += row['count']
            weighted += row['rating'] * row['count']

        reviews = (
            Review.objects
            .select_related('reviewer', 'order', 'whatsapp_checkout')
            .prefetch_related('images')[offset:offset + limit]
        )
        return Response({
            'summary': {
                'count': total,
                'average': round(weighted / total, 1) if total else None,
                'rating_distribution': rating_distribution,
            },
            'reviews': ReviewSerializer(reviews, many=True, context={'request': request}).data,
            'pagination': get_pagination_payload(total, limit, offset),
        })


class WhatsAppReviewView(ScopedPostThrottleMixin, APIView):
    """GET/POST /api/reviews/whatsapp/<token>/ — review a sale via its link.

    Serves two token namespaces with one page: WhatsAppCheckout tokens
    (minted when the admin marks the sale completed, pasted into the chat)
    and Order tokens (minted when the review-request email goes out).
    Possession of the link IS the authentication — no account or login
    involved. One review per sale.
    """
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'whatsapp_review'

    @staticmethod
    def get_review_target(token):
        """The completed sale this token belongs to — checkout or order."""
        checkout = WhatsAppCheckout.objects.select_related('listing__seller').filter(
            review_token=token, status='completed',
        ).first()
        if checkout is not None:
            return checkout, None
        order = Order.objects.select_related('buyer', 'seller').filter(
            review_token=token, status='completed',
        ).first()
        if order is not None:
            return None, order
        raise Http404

    def get(self, request, token):
        checkout, order = self.get_review_target(token)
        target = checkout if checkout is not None else order
        try:
            review = target.review
        except Review.DoesNotExist:
            review = None
        return Response({
            'listing_title': target.listing_title,
            'completed_at': target.completed_at,
            'reviewed': review is not None,
            'review': (
                ReviewSerializer(review, context={'request': request}).data
                if review else None
            ),
        })

    def post(self, request, token):
        checkout, order = self.get_review_target(token)
        serializer = UpdateReviewSerializer(data=request.data)  # rating + comment
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        images, validation_error = validate_review_images(request.FILES.getlist('images'))
        if validation_error:
            return Response({'error': validation_error}, status=400)

        if checkout is not None:
            seller = resolve_whatsapp_review_seller(checkout)
        else:
            seller = order.seller
        if seller is None:
            return Response(
                {'error': 'This sale cannot be reviewed right now.'}, status=400,
            )

        try:
            with db_transaction.atomic():
                if checkout is not None:
                    locked = WhatsAppCheckout.objects.select_for_update().get(pk=checkout.pk)
                    review_source = {'whatsapp_checkout': locked, 'reviewer': None}
                else:
                    locked = Order.objects.select_for_update().get(pk=order.pk)
                    # Email-link reviews still carry the buyer's name — the
                    # order knows who bought.
                    review_source = {'order': locked, 'reviewer': locked.buyer}
                if Review.objects.filter(
                    Q(whatsapp_checkout=locked) if checkout is not None else Q(order=locked)
                ).exists():
                    return Response(
                        {'error': 'This sale has already been reviewed.'}, status=400,
                    )

                review = Review.objects.create(
                    seller=seller,
                    rating=data['rating'],
                    comment=data.get('comment', ''),
                    **review_source,
                )

                for image in images:
                    ReviewImage.objects.create(review=review, image=image)

                reviewer_label = (
                    'A WhatsApp buyer' if checkout is not None
                    else locked.buyer.username
                )
                create_notification(
                    recipient=seller,
                    notification_type='new_review',
                    title=f'New {data["rating"]}-star review from {reviewer_label}',
                    message=(
                        f'{reviewer_label} left a {data["rating"]}-star review'
                        + (f' for "{locked.listing_title}".' if locked.listing_title else '.')
                        + (f' "{data.get("comment", "")}"' if data.get('comment') else '')
                    ),
                    review=review,
                )
        except IntegrityError:
            return Response({'error': 'This sale has already been reviewed.'}, status=400)

        cache.delete(SITE_REVIEWS_CACHE_KEY)
        cache.delete(seller_profile_cache_key(seller.id))

        return Response(ReviewSerializer(review, context={'request': request}).data, status=201)


class SiteReviewsView(APIView):
    """GET /api/reviews/site/ — recent buyer reviews for the sitewide strip.

    Feeds the marquee that sits above the footer on every page, so it is a
    showcase, not a full feed: only reviews that are positive AND actually say
    something make it in (a lone "." reads as filler). The summary counts are
    computed over EVERY review though — the average shown must be the real
    sitewide average, not the average of the cherry-picked cards.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        data = cache.get(SITE_REVIEWS_CACHE_KEY)
        if data is None:
            data = self.build_payload()
            cache.set(SITE_REVIEWS_CACHE_KEY, data, SITE_REVIEWS_CACHE_SECONDS)
        response = Response(data)
        response['Cache-Control'] = public_cache_header(SITE_REVIEWS_CACHE_SECONDS)
        return response

    @staticmethod
    def build_payload():
        summary = Review.objects.aggregate(count=Count('id'), average=Avg('rating'))
        reviews = (
            Review.objects
            # Trim first: "   .   " is 7 characters of nothing.
            .annotate(comment_length=Length(Trim('comment')))
            .filter(
                rating__gte=SITE_REVIEWS_MIN_RATING,
                comment_length__gte=SITE_REVIEWS_MIN_COMMENT_LENGTH,
            )
            .select_related('order', 'whatsapp_checkout')
            .order_by('-created_at')[:SITE_REVIEWS_LIMIT]
        )
        average = summary['average']
        return {
            'reviews': [
                {
                    # No reviewer name on purpose: every public review card on
                    # the site is attributed to an anonymous "Buyer" (seller
                    # profile, listing page), so this strip must not be the one
                    # place a buyer's username shows up next to what they bought.
                    'id': review.id,
                    'rating': review.rating,
                    'comment': Truncator(review.comment.strip()).chars(
                        SITE_REVIEWS_MAX_COMMENT_LENGTH
                    ),
                    'listing_title': review.source_listing_title,
                    'created_at': review.created_at,
                }
                for review in reviews
            ],
            'summary': {
                'count': summary['count'] or 0,
                'average': round(float(average), 1) if average is not None else None,
            },
        }


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
        cache_key = seller_profile_cache_key(seller.pk)
        cached = cache.get(cache_key)
        if cached is not None:
            # Online status and avatar must be fresh
            cached['is_online'] = profile.is_online
            cached['last_active'] = profile.last_active
            cached['avatar_url'] = public_avatar_url(profile.avatar, request=request)
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

        # Completed sales: on-site orders plus WhatsApp sales. General-chat
        # WhatsApp sales carry no listing link — those belong to the shop's
        # official store account.
        completed_sales = Order.objects.filter(
            seller=seller, status='completed'
        ).count()
        whatsapp_scope = Q(listing__seller=seller)
        if profile.is_official_store:
            whatsapp_scope |= Q(listing__isnull=True)
        completed_sales += WhatsAppCheckout.objects.filter(
            whatsapp_scope, status='completed',
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
                'game_category__display_name',
                'game_category__display_slug',
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
                'slug': row['game_category__display_slug'] or row['game_category__category__slug'],
                'name': row['game_category__display_name'] or row['game_category__category__name'],
                'icon': row['game_category__category__icon'],
                'count': row['listing_count'],
            })

        # Sort games by total offers descending
        games = sorted(games_map.values(), key=lambda g: g['total_offers'], reverse=True)

        avatar_url = public_avatar_url(profile.avatar, request=request)

        payload = {
            'username': seller.username,
            'user_id': seller.pk,
            'member_since': seller.date_joined,
            'is_official_store': profile.is_official_store,
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
            # Renamed categories only match their buyer-facing display name,
            # not the internal category name they borrow.
            Q(category__name__icontains=query, display_name='') |
            Q(display_name__icontains=query)
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
                'display_name': f'{gc.game.name} {gc.effective_name}',
                'game_name': gc.game.name,
                'game_slug': gc.game.slug,
                'game_icon_url': icon_url,
                'category_name': gc.effective_name,
                'category_slug': gc.effective_slug,
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
            if updated:
                cache.delete(notification_unread_cache_key(request.user.pk))
            return Response({'marked_read': updated})
        elif notification_id:
            try:
                notification_id = int(notification_id)
            except (TypeError, ValueError):
                return Response({'error': 'notification_id must be a valid id.'}, status=400)
            # Mark a single notification as read
            notification = get_object_or_404(
                Notification, pk=notification_id, recipient=request.user,
            )
            if not notification.is_read:
                notification.is_read = True
                notification.save(update_fields=['is_read'])
                cache.delete(notification_unread_cache_key(request.user.pk))
            return Response({'marked_read': 1})
        else:
            return Response({'error': 'notification_id is required.'}, status=400)


class NotificationUnreadCountView(APIView):
    """GET /api/notifications/unread-count/ — Unread notification count."""
    permission_classes = [HasCompletedProfile]

    def get(self, request):
        cache_key = notification_unread_cache_key(request.user.pk)
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
                'listing__game_category__display_name',
            ).annotate(
                sales_count=Count('id'),
                revenue=Sum('seller_amount'),
            ).order_by('-sales_count')[:5]
        )
        top_categories_data = [
            {
                'game': entry['listing__game_category__game__name'] or 'Unknown',
                'category': entry['listing__game_category__display_name']
                            or entry['listing__game_category__category__name']
                            or 'Unknown',
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


class CreateItemRequestView(ScopedPostThrottleMixin, APIView):
    """POST /api/item-requests/ — Buyer asks for an item in a category with no
    listings yet. Works for guests and logged-in users."""
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'create_item_request'

    def post(self, request):
        serializer = CreateItemRequestSerializer(
            data=request.data, context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        game_category = GameCategory.resolve_for_slug(
            data['game_slug'], data['category_slug'],
            queryset=GameCategory.objects.select_related('game', 'category'),
        )
        if game_category is None:
            return Response(
                {'error': 'Game or category not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        item_request = ItemRequest.objects.create(
            user=request.user if request.user.is_authenticated else None,
            guest_email=data.get('email', '') if not request.user.is_authenticated else '',
            game_category=game_category,
            message=data['message'],
        )
        notify_staff_about_item_request(item_request)

        return Response(
            {'message': "Request received! We'll get this stocked and let you know."},
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
