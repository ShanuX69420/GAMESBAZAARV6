from decimal import Decimal
from urllib.parse import urlencode
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.settings import api_settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User, update_last_login
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from .models import (
    Game, Category, GameCategory, CategoryOption, Filter, FilterOption,
    GameCategoryFilter, UserProfile, Listing,
    Conversation, Message,
    Wallet, WalletTransaction, TopUpRequest, WithdrawRequest, Order,
    JazzCashPayment, FazerProductLink,
    SellerCommissionOverride, Review, Notification,
    Report, SupportTicket, ItemRequest,
)
from .services import (
    get_order_auto_confirm_at,
    order_seller_payout_has_been_released,
    create_private_media_ticket,
    decrypt_sensitive_text,
    encrypt_sensitive_text,
)
from .storage_backends import (
    AVATAR_CACHE_SECONDS,
    GAME_ICON_CACHE_SECONDS,
    cached_media_url,
)
from .permissions import add_profile_setup_token_claim, user_needs_profile_setup


MAX_AUTO_DELIVERY_PAYLOAD_LENGTH = 100_000
MAX_AUTO_DELIVERY_LINES = 1_000
MAX_AUTO_DELIVERY_LINE_LENGTH = 2_000
MAX_DELIVERY_INSTRUCTIONS_LENGTH = 2_000
MAX_DELIVERY_NOTE_LENGTH = 5_000
MAX_DISPUTE_REASON_LENGTH = 3_000
DUMMY_PASSWORD_HASH = make_password('not-the-password')


def clean_auto_delivery_lines(value):
    raw_data = '' if value is None else str(value)
    if not raw_data:
        raise serializers.ValidationError({
            'auto_delivery_data': 'Delivery data is required for automated delivery listings.',
        })

    lines = get_auto_delivery_inventory_lines(raw_data)
    if not lines:
        raise serializers.ValidationError({
            'auto_delivery_data': 'Please enter at least one item.',
        })
    if len(lines) > MAX_AUTO_DELIVERY_LINES:
        raise serializers.ValidationError({
            'auto_delivery_data': f'Automated delivery inventory cannot exceed {MAX_AUTO_DELIVERY_LINES} items.',
        })
    if any(len(line) > MAX_AUTO_DELIVERY_LINE_LENGTH for line in lines):
        raise serializers.ValidationError({
            'auto_delivery_data': f'Each automated delivery item must be {MAX_AUTO_DELIVERY_LINE_LENGTH} characters or fewer.',
        })
    return lines


def get_auto_delivery_inventory_lines(value):
    raw_data = '' if value is None else str(value)
    return [line for line in raw_data.splitlines() if line.strip()]


def build_listing_filter_display_map(listings):
    pairs = set()
    for listing in listings:
        for filter_id_str, option_value in (listing.filter_values or {}).items():
            try:
                pairs.add((int(filter_id_str), option_value))
            except (TypeError, ValueError):
                continue

    if not pairs:
        return {}

    filter_ids = {filter_id for filter_id, _ in pairs}
    option_values = {option_value for _, option_value in pairs}
    options = FilterOption.objects.select_related('filter').filter(
        filter_id__in=filter_ids,
        value__in=option_values,
    )
    return {
        (str(option.filter_id), option.value): (option.filter.name, option.label)
        for option in options
    }


def build_private_media_url(request, view_name, object_id, kind):
    viewer_user_id = None
    if request and request.user.is_authenticated:
        viewer_user_id = request.user.pk
    ticket = create_private_media_ticket(kind, object_id, viewer_user_id=viewer_user_id)
    path = f"{reverse(view_name, args=[object_id])}?{urlencode({'ticket': ticket})}"
    if request:
        return request.build_absolute_uri(path)
    return path


# ── Game / Category / Filter Serializers (from Phase 1) ──────────────────────

class FilterOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FilterOption
        fields = ['id', 'label', 'value', 'order']


class FilterSerializer(serializers.ModelSerializer):
    options = FilterOptionSerializer(many=True, read_only=True)

    class Meta:
        model = Filter
        fields = ['id', 'name', 'filter_type', 'options']


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'icon', 'buyer_protection_enabled']


class GameCategorySerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    listing_count = serializers.SerializerMethodField()

    class Meta:
        model = GameCategory
        fields = ['id', 'category', 'order', 'listing_count']

    def get_listing_count(self, obj):
        # Annotated by GameDetailView's prefetch; 0 when used without it.
        return getattr(obj, 'active_listing_count', 0)

    def to_representation(self, instance):
        # Buyers (and sellers picking a category) see the per-game display
        # override, not the internal category name.
        data = super().to_representation(instance)
        if instance.display_name:
            data['category'] = dict(
                data['category'],
                name=instance.effective_name,
                slug=instance.effective_slug,
            )
        return data


class GameListSerializer(serializers.ModelSerializer):
    category_count = serializers.SerializerMethodField()
    listing_count = serializers.SerializerMethodField()
    icon_url = serializers.SerializerMethodField()

    class Meta:
        model = Game
        fields = ['id', 'name', 'slug', 'description', 'icon_url', 'category_count', 'listing_count']

    def get_category_count(self, obj):
        # Use len() to leverage the prefetched cache instead of .count()
        # which always fires a separate COUNT query.
        return len(obj.game_categories.all())

    def get_listing_count(self, obj):
        # Annotated by GameListView's queryset; 0 when used without it.
        return getattr(obj, 'active_listing_count', 0)

    def get_icon_url(self, obj):
        if obj.icon:
            request = self.context.get('request')
            return cached_media_url(
                obj.icon,
                request=request,
                cache_seconds=GAME_ICON_CACHE_SECONDS,
                cache_scope='public',
            )
        return None


class GameDetailSerializer(serializers.ModelSerializer):
    categories = serializers.SerializerMethodField()
    icon_url = serializers.SerializerMethodField()

    class Meta:
        model = Game
        fields = ['id', 'name', 'slug', 'description', 'icon_url', 'categories']

    def get_categories(self, obj):
        # Use .all() to leverage the prefetched cache from the view
        # instead of re-querying with select_related.
        return GameCategorySerializer(obj.game_categories.all(), many=True).data

    def get_icon_url(self, obj):
        if obj.icon:
            request = self.context.get('request')
            return cached_media_url(
                obj.icon,
                request=request,
                cache_seconds=GAME_ICON_CACHE_SECONDS,
                cache_scope='public',
            )
        return None


class GameCategoryDetailSerializer(serializers.Serializer):
    game = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    filters = serializers.SerializerMethodField()
    allow_auto_delivery = serializers.BooleanField(read_only=True)
    listing_mode = serializers.CharField(read_only=True)
    unit_name = serializers.CharField(read_only=True)

    def get_game(self, obj):
        return {
            'id': obj.game.id,
            'name': obj.game.name,
            'slug': obj.game.slug,
        }

    def get_category(self, obj):
        data = CategorySerializer(obj.category).data
        if obj.display_name:
            data['name'] = obj.effective_name
            data['slug'] = obj.effective_slug
        return data

    def get_filters(self, obj):
        # Use .all() to leverage the prefetched cache from the view
        # instead of re-querying with select_related/prefetch_related.
        payload = []
        for gcf in obj.assigned_filters.all():
            data = FilterSerializer(gcf.filter).data
            data['require_selection'] = gcf.require_selection
            # List of trigger conditions — the filter shows when ANY matches.
            data['visible_when'] = [
                {'filter_id': opt.filter_id, 'option_value': opt.value}
                for opt in gcf.visible_when_options.all()
            ] or None
            payload.append(data)
        return payload


# ── Auth Serializers ─────────────────────────────────────────────────────────

class RegisterSerializer(serializers.ModelSerializer):
    username = serializers.CharField(max_length=150, required=True)
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, min_length=6)
    password2 = serializers.CharField(write_only=True, min_length=6)
    accepted_terms = serializers.BooleanField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password2', 'accepted_terms']

    def validate_accepted_terms(self, value):
        if not value:
            raise serializers.ValidationError('You must accept the Terms of Service and Privacy Policy.')
        return value

    def validate_email(self, value):
        value = User.objects.normalize_email(value.strip())
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate_username(self, value):
        value = User.normalize_username(value.strip())
        if not value:
            raise serializers.ValidationError('Username cannot be blank.')
        try:
            User._meta.get_field('username').run_validators(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('This username is already taken.')
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({'password2': 'Passwords do not match.'})
        user = User(username=attrs.get('username'), email=attrs.get('email'))
        try:
            validate_password(attrs['password'], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': list(exc.messages)})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        validated_data.pop('accepted_terms')
        try:
            with transaction.atomic():
                user = User.objects.create_user(is_active=False, **validated_data)
                user.profile.has_accepted_terms = True
                user.profile.email_verification_pending = True
                user.profile.save(update_fields=['has_accepted_terms', 'email_verification_pending'])
                return user
        except IntegrityError:
            errors = {}
            username = validated_data.get('username')
            email = validated_data.get('email')
            if username and User.objects.filter(username__iexact=username).exists():
                errors['username'] = 'This username is already taken.'
            if email and User.objects.filter(email__iexact=email).exists():
                errors['email'] = 'A user with this email already exists.'
            if not errors:
                errors['detail'] = 'Could not create account. Please try again.'
            raise serializers.ValidationError(errors)


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = 'email'

    @classmethod
    def get_token(cls, user):
        return add_profile_setup_token_claim(super().get_token(user), user)

    def validate(self, attrs):
        email = User.objects.normalize_email(attrs.get('email', '').strip())
        password = attrs.get('password')
        user = User.objects.filter(email__iexact=email).order_by('id').first()

        self.user = None
        if user is not None:
            authenticate_kwargs = {
                User.USERNAME_FIELD: user.get_username(),
                'password': password,
            }
            request = self.context.get('request')
            if request is not None:
                authenticate_kwargs['request'] = request
            self.user = authenticate(**authenticate_kwargs)
        else:
            check_password(password or '', DUMMY_PASSWORD_HASH)

        if not api_settings.USER_AUTHENTICATION_RULE(self.user):
            raise AuthenticationFailed(
                self.error_messages['no_active_account'],
                'no_active_account',
            )

        refresh = self.get_token(self.user)
        data = {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }

        if api_settings.UPDATE_LAST_LOGIN:
            update_last_login(None, self.user)

        return data


class UserSerializer(serializers.ModelSerializer):
    seller_status = serializers.CharField(source='profile.seller_status', read_only=True)
    is_seller = serializers.BooleanField(source='profile.is_seller', read_only=True)
    wallet_balance = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    username_changed_at = serializers.DateTimeField(source='profile.username_changed_at', read_only=True)
    needs_setup = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'seller_status', 'is_seller', 'wallet_balance',
                  'avatar_url', 'date_joined', 'username_changed_at', 'needs_setup']

    def get_needs_setup(self, obj):
        """True when a Google-linked user has not yet accepted terms / chosen a username."""
        return user_needs_profile_setup(obj)

    def get_wallet_balance(self, obj):
        wallet = getattr(obj, 'wallet', None)
        if wallet:
            return str(wallet.balance)
        return '0.00'

    def get_avatar_url(self, obj):
        profile = getattr(obj, 'profile', None)
        if profile and profile.avatar:
            request = self.context.get('request')
            return cached_media_url(
                profile.avatar,
                request=request,
                cache_seconds=AVATAR_CACHE_SECONDS,
                cache_scope='private',
            )
        return None


class UpdateProfileSerializer(serializers.Serializer):
    """Update username only. Email uses a separate verification flow."""
    username = serializers.CharField(max_length=150, required=True)

    def validate_username(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Username cannot be blank.')
        user = self.context.get('user')

        # If unchanged, skip the cooldown check
        if value == user.username:
            return value

        try:
            User._meta.get_field('username').run_validators(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))

        # 90-day cooldown
        from .services import USERNAME_CHANGE_COOLDOWN_DAYS
        profile = self.context.get('profile') or user.profile
        if profile.username_changed_at:
            from django.utils import timezone
            days_since = (timezone.now() - profile.username_changed_at).days
            if days_since < USERNAME_CHANGE_COOLDOWN_DAYS:
                remaining = USERNAME_CHANGE_COOLDOWN_DAYS - days_since
                raise serializers.ValidationError(
                    f'You can only change your username once every {USERNAME_CHANGE_COOLDOWN_DAYS} days. '
                    f'Try again in {remaining} day{"s" if remaining != 1 else ""}.'
                )

        if User.objects.filter(username__iexact=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError('This username is already taken.')
        return value


class RequestEmailChangeSerializer(serializers.Serializer):
    """Step 1: Request email change — sends codes to current and new email."""
    new_email = serializers.EmailField(required=True)

    def validate_new_email(self, value):
        value = User.objects.normalize_email(value.strip())
        user = self.context.get('user')
        if value.lower() == user.email.lower():
            raise serializers.ValidationError('This is already your current email.')
        if User.objects.filter(email__iexact=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value


class ConfirmEmailChangeSerializer(serializers.Serializer):
    """Step 2: Confirm email change with both verification codes."""
    current_code = serializers.CharField(required=True, max_length=6, min_length=6)
    new_code = serializers.CharField(required=True, max_length=6, min_length=6)
    token = serializers.CharField(required=True)


class ChangePasswordSerializer(serializers.Serializer):
    """Change the current user's password."""
    current_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=6)
    new_password2 = serializers.CharField(required=True, min_length=6)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password2']:
            raise serializers.ValidationError({'new_password2': 'Passwords do not match.'})
        user = self.context.get('user')
        try:
            validate_password(attrs['new_password'], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'new_password': list(exc.messages)})
        return attrs


class CompleteProfileSerializer(UpdateProfileSerializer):
    """Set username and accept terms for Google-linked accounts."""
    accepted_terms = serializers.BooleanField(required=True)

    def validate_accepted_terms(self, value):
        if not value:
            raise serializers.ValidationError('You must accept the Terms of Service and Privacy Policy.')
        return value


class SellerApplicationSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=1000, required=True)


# ── Listing Serializers ──────────────────────────────────────────────────────

class ListingSerializer(serializers.ModelSerializer):
    seller_id = serializers.IntegerField(source='seller.id', read_only=True)
    seller_name = serializers.CharField(source='seller.username', read_only=True)
    seller_is_online = serializers.SerializerMethodField()
    seller_last_active = serializers.SerializerMethodField()
    seller_avatar_url = serializers.SerializerMethodField()
    seller_avg_rating = serializers.SerializerMethodField()
    seller_review_count = serializers.SerializerMethodField()
    game_name = serializers.CharField(source='game_category.game.name', read_only=True)
    category_name = serializers.CharField(source='game_category.effective_name', read_only=True)
    listing_mode = serializers.CharField(source='game_category.listing_mode', read_only=True)
    unit_name = serializers.CharField(source='game_category.unit_name', read_only=True)
    buyer_protection_enabled = serializers.BooleanField(
        source='game_category.category.buyer_protection_enabled', read_only=True,
    )
    filter_display = serializers.SerializerMethodField()
    option_id = serializers.IntegerField(read_only=True)
    option_name = serializers.SerializerMethodField()
    delivery_instructions = serializers.SerializerMethodField()
    instant_delivery = serializers.SerializerMethodField()
    required_checkout_fields = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = [
            'id', 'title', 'description', 'price', 'quantity', 'min_quantity', 'status',
            'seller_id', 'seller_name', 'seller_is_online', 'seller_last_active',
            'seller_avatar_url', 'seller_avg_rating', 'seller_review_count',
            'game_name', 'category_name', 'listing_mode', 'unit_name',
            'buyer_protection_enabled',
            'option_id', 'option_name',
            'filter_values', 'filter_display', 'delivery_time',
            'delivery_instructions', 'is_auto_delivery', 'instant_delivery',
            'required_checkout_fields', 'created_at',
        ]

    def get_option_name(self, obj):
        return obj.option.name if obj.option_id else None

    def get_instant_delivery(self, obj):
        """Effective instant flag: pre-stocked auto-delivery OR a listing the
        platform fulfills automatically (delivery_time flipped to 'Instant'
        while Fazer auto-fulfillment is on)."""
        return obj.is_auto_delivery or obj.delivery_time == 'Instant'

    def get_required_checkout_fields(self, obj):
        """Checkout inputs the buyer must fill (auto-fulfilled top-ups only).
        Computed only where the view opts in — the listing detail page — to
        avoid an N+1 on category listings."""
        if not self.context.get('include_checkout_fields'):
            return []
        from .fulfillment import autofulfill_enabled, get_active_link
        if not autofulfill_enabled():
            return []
        link = get_active_link(obj)
        if link is None or link.kind != 'topup':
            return []
        return link.checkout_fields or [{'key': 'player_id', 'label': 'Player ID'}]

    def get_delivery_instructions(self, obj):
        """Offer and currency listings show instructions to buyers before
        purchase; standard listings only reveal them after ordering (via the
        order snapshot)."""
        if obj.option_id or obj.game_category.listing_mode == 'currency':
            return obj.delivery_instructions
        request = self.context.get('request')
        if request and request.user.is_authenticated and request.user.id == obj.seller_id:
            # Sellers still see their own instructions (e.g., in My Listings).
            return obj.delivery_instructions
        return ''

    def get_seller_is_online(self, obj):
        profile = getattr(obj.seller, 'profile', None)
        return profile.is_online if profile else False

    def get_seller_last_active(self, obj):
        profile = getattr(obj.seller, 'profile', None)
        if profile and profile.last_active:
            return profile.last_active.isoformat()
        return None

    def get_seller_avatar_url(self, obj):
        profile = getattr(obj.seller, 'profile', None)
        if profile and profile.avatar:
            request = self.context.get('request')
            return cached_media_url(
                profile.avatar,
                request=request,
                cache_seconds=AVATAR_CACHE_SECONDS,
                cache_scope='private',
            )
        return None

    def get_seller_avg_rating(self, obj):
        """Return seller avg rating from annotation, or None."""
        val = getattr(obj, 'seller_avg_rating', None)
        if val is not None:
            return round(float(val), 1)
        return None

    def get_seller_review_count(self, obj):
        """Return seller review count from annotation, or 0."""
        val = getattr(obj, 'seller_review_count', None)
        return val if val is not None else 0

    def get_filter_display(self, obj):
        """Convert filter_values {filter_id: option_value} to human-readable labels."""
        if not obj.filter_values:
            return {}
        display_map = self.context.get('filter_option_display_map') or {}
        result = {}
        for filter_id_str, option_value in obj.filter_values.items():
            mapped = display_map.get((filter_id_str, option_value))
            if mapped:
                filter_name, option_label = mapped
                result[filter_name] = option_label
            else:
                # Show raw values for unmapped pairs instead of firing
                # a per-item DB query. The batch map already covers all
                # valid filter option pairs.
                result[filter_id_str] = option_value
        return result


class CreateListingSerializer(serializers.ModelSerializer):
    game_slug = serializers.SlugField(write_only=True)
    category_slug = serializers.SlugField(write_only=True)
    title = serializers.CharField(max_length=300, required=False, allow_blank=True, default='')
    option_id = serializers.IntegerField(write_only=True, required=False, allow_null=True, default=None)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))
    quantity = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=1)
    min_quantity = serializers.IntegerField(required=False, default=1, min_value=1)
    is_auto_delivery = serializers.BooleanField(required=False, default=False)
    auto_delivery_data = serializers.CharField(
        required=False,
        default='',
        allow_blank=True,
        max_length=MAX_AUTO_DELIVERY_PAYLOAD_LENGTH,
        trim_whitespace=False,
    )
    delivery_instructions = serializers.CharField(
        required=False,
        default='',
        allow_blank=True,
        max_length=MAX_DELIVERY_INSTRUCTIONS_LENGTH,
    )

    class Meta:
        model = Listing
        fields = ['game_slug', 'category_slug', 'option_id', 'title', 'description', 'price',
                  'quantity', 'min_quantity', 'delivery_time', 'filter_values', 'is_auto_delivery',
                  'auto_delivery_data', 'delivery_instructions']

    def validate(self, attrs):
        game_slug = attrs.pop('game_slug')
        category_slug = attrs.pop('category_slug')
        gc = GameCategory.resolve_for_slug(game_slug, category_slug)
        if gc is None:
            raise serializers.ValidationError('Invalid game/category combination.')
        attrs['game_category'] = gc

        option_id = attrs.pop('option_id', None)
        if gc.listing_mode == 'offer':
            if not option_id:
                raise serializers.ValidationError({
                    'option_id': 'Please choose an option for this category.',
                })
            try:
                option = CategoryOption.objects.get(pk=option_id, game_category=gc)
            except CategoryOption.DoesNotExist:
                raise serializers.ValidationError({
                    'option_id': 'Invalid option for this game/category.',
                })
            seller = self.context['request'].user
            if Listing.objects.filter(seller=seller, option=option, status='active').exists():
                raise serializers.ValidationError({
                    'option_id': f'You already have an active offer for {option.name}. '
                                 'Edit your existing offer instead.',
                })
            if not (attrs.get('delivery_instructions') or '').strip():
                raise serializers.ValidationError({
                    'delivery_instructions': 'Delivery instructions are required for this '
                                             'category (e.g., what you need from the buyer '
                                             'and how delivery works).',
                })
            attrs['option'] = option
            attrs['title'] = option.name
        elif gc.listing_mode == 'currency':
            if option_id:
                raise serializers.ValidationError({
                    'option_id': 'Options are not available for this category.',
                })
            seller = self.context['request'].user
            if Listing.objects.filter(
                seller=seller, game_category=gc, status='active',
            ).exists():
                raise serializers.ValidationError(
                    'You already have an active offer in this category. '
                    'Edit your existing offer from My Listings instead.'
                )
            if attrs.get('is_auto_delivery'):
                raise serializers.ValidationError({
                    'is_auto_delivery': 'Automated delivery is not available for currency listings.',
                })
            if not (attrs.get('delivery_instructions') or '').strip():
                raise serializers.ValidationError({
                    'delivery_instructions': 'Delivery instructions are required for this '
                                             'category (e.g., what you need from the buyer '
                                             'and how delivery works).',
                })
            unit = gc.unit_name or 'units'
            if not attrs.get('quantity'):
                raise serializers.ValidationError({
                    'quantity': f'Enter how much stock you have (in {unit}).',
                })
            if attrs.get('min_quantity', 1) > attrs['quantity']:
                raise serializers.ValidationError({
                    'min_quantity': 'Minimum purchase cannot exceed your stock.',
                })
            # Sellers compete on price/stock, not titles — keep them uniform.
            attrs['title'] = f'{gc.game.name} {gc.effective_name}'
        else:
            if option_id:
                raise serializers.ValidationError({
                    'option_id': 'Options are not available for this category.',
                })
            if not (attrs.get('title') or '').strip():
                raise serializers.ValidationError({'title': 'Title is required.'})

        if gc.listing_mode != 'currency':
            attrs['min_quantity'] = 1

        # Validate auto-delivery
        is_auto = attrs.get('is_auto_delivery', False)
        if is_auto:
            if not gc.allow_auto_delivery:
                raise serializers.ValidationError({
                    'is_auto_delivery': 'Automated delivery is not allowed for this category.',
                })
            # Force instant delivery for auto-delivery listings
            attrs['delivery_time'] = 'Instant'
            # Quantity = number of non-empty lines (each line = 1 deliverable item)
            lines = clean_auto_delivery_lines(attrs.get('auto_delivery_data', ''))
            attrs['auto_delivery_data'] = encrypt_sensitive_text('\n'.join(lines))
            attrs['quantity'] = len(lines)
        else:
            # Manual listings cannot select Instant delivery
            delivery_time = attrs.get('delivery_time', '10-15 Minutes')
            if delivery_time == 'Instant':
                raise serializers.ValidationError({
                    'delivery_time': 'Instant delivery is only available for automated delivery listings.',
                })
            attrs['auto_delivery_data'] = ''

        raw_filter_values = attrs.get('filter_values', {})
        if raw_filter_values in (None, ''):
            raw_filter_values = {}

        if not isinstance(raw_filter_values, dict):
            raise serializers.ValidationError({
                'filter_values': 'Filter values must be an object.',
            })

        assigned_filters = list(
            GameCategoryFilter.objects.filter(game_category=gc)
            .select_related('filter')
            .prefetch_related('visible_when_options')
            .order_by('order', 'filter__name')
        )
        assigned_filter_ids = {gcf.filter_id for gcf in assigned_filters}
        cleaned_filter_values = {}
        requested_pairs = set()

        for raw_filter_id, raw_option_value in raw_filter_values.items():
            if raw_option_value in (None, ''):
                continue

            try:
                filter_id = int(raw_filter_id)
            except (TypeError, ValueError):
                raise serializers.ValidationError({
                    'filter_values': 'Filter ids must be numeric.',
                })

            if filter_id <= 0 or filter_id not in assigned_filter_ids:
                raise serializers.ValidationError({
                    'filter_values': 'Invalid filter for this game/category.',
                })

            if not isinstance(raw_option_value, str):
                raise serializers.ValidationError({
                    'filter_values': 'Filter option values must be text.',
                })

            option_value = raw_option_value.strip()
            if not option_value:
                continue

            cleaned_filter_values[str(filter_id)] = option_value
            requested_pairs.add((filter_id, option_value))

        if requested_pairs:
            valid_pairs = set(
                FilterOption.objects.filter(
                    filter_id__in={filter_id for filter_id, _ in requested_pairs},
                    value__in={option_value for _, option_value in requested_pairs},
                ).values_list('filter_id', 'value')
            )
            if requested_pairs - valid_pairs:
                raise serializers.ValidationError({
                    'filter_values': 'Invalid option for this filter.',
                })

        # Dependent filters only apply when their parent filter holds the
        # triggering option. Strip values for filters whose condition is not
        # met (e.g., stale client state) and only require the rest. Loop until
        # stable so chained dependencies collapse correctly.
        assigned_by_id = {gcf.filter_id: gcf for gcf in assigned_filters}

        def filter_applies(gcf):
            conditions = [
                opt for opt in gcf.visible_when_options.all()
                # Ignore conditions on filters not assigned to this category
                # (misconfiguration) — they can never be satisfied.
                if opt.filter_id in assigned_by_id
            ]
            if not conditions:
                return True
            return any(
                cleaned_filter_values.get(str(opt.filter_id)) == opt.value
                for opt in conditions
            )

        while True:
            stripped = [
                filter_id for filter_id in cleaned_filter_values
                if not filter_applies(assigned_by_id[int(filter_id)])
            ]
            if not stripped:
                break
            for filter_id in stripped:
                del cleaned_filter_values[filter_id]

        missing_filter_names = [
            gcf.filter.name
            for gcf in assigned_filters
            if filter_applies(gcf) and str(gcf.filter_id) not in cleaned_filter_values
        ]
        if missing_filter_names:
            raise serializers.ValidationError({
                'filter_values': (
                    'Please select all required filters: '
                    f'{", ".join(missing_filter_names)}.'
                ),
            })

        attrs['filter_values'] = cleaned_filter_values
        return attrs

    def create(self, validated_data):
        validated_data['seller'] = self.context['request'].user
        return Listing.objects.create(**validated_data)


class UpdateListingSerializer(serializers.ModelSerializer):
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))
    quantity = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    min_quantity = serializers.IntegerField(required=False, min_value=1)
    delivery_instructions = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=MAX_DELIVERY_INSTRUCTIONS_LENGTH,
    )

    class Meta:
        model = Listing
        fields = ['title', 'description', 'price', 'quantity', 'min_quantity',
                  'delivery_time', 'delivery_instructions', 'status']

    def validate(self, attrs):
        listing = self.instance
        next_status = attrs.get('status', listing.status)
        next_quantity = attrs.get('quantity', listing.quantity)
        next_delivery_time = attrs.get('delivery_time', listing.delivery_time)

        if listing.game_category.listing_mode == 'currency':
            # Currency offers keep their auto-generated title.
            attrs.pop('title', None)
            if 'delivery_instructions' in attrs and not attrs['delivery_instructions'].strip():
                raise serializers.ValidationError({
                    'delivery_instructions': 'Delivery instructions are required for this category.',
                })
            if next_quantity is None:
                raise serializers.ValidationError({
                    'quantity': 'Currency listings need a stock amount.',
                })
            next_min_quantity = attrs.get('min_quantity', listing.min_quantity)
            if next_min_quantity > next_quantity:
                raise serializers.ValidationError({
                    'min_quantity': 'Minimum purchase cannot exceed your stock.',
                })
            if next_status == 'active' and listing.status != 'active':
                duplicate = Listing.objects.filter(
                    seller=listing.seller,
                    game_category=listing.game_category,
                    status='active',
                ).exclude(pk=listing.pk).exists()
                if duplicate:
                    raise serializers.ValidationError({
                        'status': 'You already have an active offer in this category. '
                                  'Deactivate it first or edit it instead.',
                    })
        else:
            attrs.pop('min_quantity', None)

        if listing.option_id:
            # Offer listings keep their title in sync with the option name.
            attrs.pop('title', None)
            if 'delivery_instructions' in attrs and not attrs['delivery_instructions'].strip():
                raise serializers.ValidationError({
                    'delivery_instructions': 'Delivery instructions are required for this category.',
                })
            if next_status == 'active' and listing.status != 'active':
                duplicate = Listing.objects.filter(
                    seller=listing.seller,
                    option_id=listing.option_id,
                    status='active',
                ).exclude(pk=listing.pk).exists()
                if duplicate:
                    raise serializers.ValidationError({
                        'status': 'You already have an active offer for this option. '
                                  'Deactivate it first or edit it instead.',
                    })

        if listing.is_auto_delivery:
            if 'quantity' in attrs and next_quantity != listing.quantity:
                raise serializers.ValidationError({
                    'quantity': 'Automated delivery stock is controlled by delivery data.',
                })

            available_items = get_auto_delivery_inventory_lines(
                decrypt_sensitive_text(listing.auto_delivery_data)
            )
            if next_status == 'active' and (
                not next_quantity or len(available_items) != next_quantity
            ):
                raise serializers.ValidationError({
                    'status': 'Add automated delivery data before activating this listing.',
                })

            attrs['delivery_time'] = 'Instant'
        elif next_delivery_time == 'Instant':
            # Platform-fulfilled listings (Fazer link) legitimately carry
            # 'Instant' while auto-fulfillment is on; everyone else may not
            # select it manually.
            has_fazer_link = FazerProductLink.objects.filter(
                listing_id=listing.pk, enabled=True,
            ).exists()
            if not has_fazer_link:
                raise serializers.ValidationError({
                    'delivery_time': 'Instant delivery is only available for automated delivery listings.',
                })
        elif next_status == 'active' and next_quantity is not None and next_quantity <= 0:
            raise serializers.ValidationError({
                'status': 'Set stock above 0 or choose unlimited stock before activating this listing.',
            })

        return attrs


# ── Chat Serializers ─────────────────────────────────────────────────────────

class AutoDeliveryRestockSerializer(serializers.Serializer):
    auto_delivery_data = serializers.CharField(
        max_length=MAX_AUTO_DELIVERY_PAYLOAD_LENGTH,
        allow_blank=False,
        trim_whitespace=False,
    )
    activate = serializers.BooleanField(required=False, default=True)

    def validate_auto_delivery_data(self, value):
        return clean_auto_delivery_lines(value)


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()
    sender_id = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    listing_reference = serializers.SerializerMethodField()
    order_info = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            'id', 'sender_id', 'sender_name', 'content', 'image_url',
            'listing_reference', 'message_type', 'system_event', 'order_info',
            'is_read', 'is_mine', 'created_at',
        ]

    def get_sender_id(self, obj):
        return obj.sender_id

    def get_sender_name(self, obj):
        # System notices are always presented as the platform; their sender
        # only records which participant's action triggered the event so
        # unread tracking can badge the other side.
        if obj.message_type == 'system':
            return None
        return obj.sender.username if obj.sender_id else None

    def get_content(self, obj):
        if obj.message_type == 'delivery':
            return decrypt_sensitive_text(obj.content)
        return obj.content

    def get_order_info(self, obj):
        order = obj.order
        if not order:
            return None
        return {
            'order_number': order.order_number,
            'buyer_username': order.buyer.username,
            'seller_username': order.seller.username,
            'listing_title': order.listing_title,
        }

    def get_is_mine(self, obj):
        request = self.context.get('request')
        if request:
            return obj.sender_id == request.user.id
        return False

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            # Use a stable URL (no ticket) so the browser can cache the image.
            # ChatMessageImageView already grants access to authenticated
            # conversation participants without a ticket.
            path = reverse('chat-message-image', args=[obj.pk])
            if request:
                return request.build_absolute_uri(path)
            return path
        return None

    def get_listing_reference(self, obj):
        listing = getattr(obj, 'referenced_listing', None)
        if not listing:
            return None
        return {
            'id': listing.id,
            'title': obj.referenced_listing_title or listing.title,
            'price': str(
                obj.referenced_listing_price
                if obj.referenced_listing_price is not None
                else listing.price
            ),
        }


class ConversationListSerializer(serializers.ModelSerializer):
    other_user = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ['id', 'other_user', 'last_message', 'unread_count', 'updated_at']

    def get_other_user(self, obj):
        request = self.context.get('request')
        if request:
            other = next(
                (participant for participant in obj.participants.all()
                 if participant.id != request.user.id),
                None,
            )
            if other:
                profile = getattr(other, 'profile', None)
                avatar_url = None
                if profile and profile.avatar:
                    request = self.context.get('request')
                    avatar_url = cached_media_url(
                        profile.avatar,
                        request=request,
                        cache_seconds=AVATAR_CACHE_SECONDS,
                        cache_scope='private',
                    )
                return {
                    'id': other.id,
                    'username': other.username,
                    'is_online': profile.is_online if profile else False,
                    'last_active': profile.last_active.isoformat() if profile and profile.last_active else None,
                    'avatar_url': avatar_url,
                }
        return None

    def get_last_message(self, obj):
        latest_created_at = getattr(obj, 'latest_message_created_at', None)
        if latest_created_at is not None:
            content = (getattr(obj, 'latest_message_content', '') or '')[:80]
            message_type = getattr(obj, 'latest_message_type', '')
            if message_type == 'delivery':
                content = 'Delivery details'
            sender_name = getattr(obj, 'latest_message_sender_name', '') or ''
            if message_type == 'system':
                # Presented as the platform; sender only tracks the actor.
                sender_name = ''
            return {
                'content': content,
                'sender_name': sender_name,
                'created_at': latest_created_at,
            }

        prefetched_messages = getattr(obj, 'prefetched_messages_desc', None)
        if prefetched_messages is not None:
            msg = prefetched_messages[0] if prefetched_messages else None
        else:
            msg = obj.messages.order_by('-created_at').first()
        if msg:
            content = msg.content[:80]
            if msg.message_type == 'delivery':
                content = 'Delivery details'
            sender_name = msg.sender.username if msg.sender_id else ''
            if msg.message_type == 'system':
                sender_name = ''
            return {
                'content': content,
                'sender_name': sender_name,
                'created_at': msg.created_at,
            }
        return None

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if hasattr(obj, 'unread_messages_count'):
            return obj.unread_messages_count
        if request:
            return obj.messages.filter(is_read=False).exclude(sender=request.user).count()
        return 0


class ConversationDetailSerializer(serializers.ModelSerializer):
    other_user = serializers.SerializerMethodField()
    messages = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ['id', 'other_user', 'messages', 'updated_at']

    def get_other_user(self, obj):
        request = self.context.get('request')
        if request:
            other = next(
                (participant for participant in obj.participants.all()
                 if participant.id != request.user.id),
                None,
            )
            if other:
                profile = getattr(other, 'profile', None)
                avatar_url = None
                if profile and profile.avatar:
                    request = self.context.get('request')
                    avatar_url = cached_media_url(
                        profile.avatar,
                        request=request,
                        cache_seconds=AVATAR_CACHE_SECONDS,
                        cache_scope='private',
                    )
                return {
                    'id': other.id,
                    'username': other.username,
                    'is_online': profile.is_online if profile else False,
                    'last_active': profile.last_active.isoformat() if profile and profile.last_active else None,
                    'avatar_url': avatar_url,
                }
        return None

    def get_messages(self, obj):
        msgs = self.context.get('messages')
        if msgs is None:
            msgs = obj.messages.select_related('sender', 'referenced_listing').all()
        return MessageSerializer(msgs, many=True, context=self.context).data


# ── Wallet Serializers ───────────────────────────────────────────────────────

class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ['balance', 'updated_at']


class WalletTransactionSerializer(serializers.ModelSerializer):
    transaction_type_display = serializers.CharField(
        source='get_transaction_type_display', read_only=True
    )
    signed_amount = serializers.SerializerMethodField()
    display_amount = serializers.SerializerMethodField()
    is_debit = serializers.SerializerMethodField()

    class Meta:
        model = WalletTransaction
        fields = [
            'id', 'transaction_type', 'transaction_type_display',
            'amount', 'signed_amount', 'display_amount', 'is_debit',
            'balance_after', 'description', 'reference_id', 'created_at',
        ]

    def get_signed_amount(self, obj):
        amount = obj.amount
        if obj.transaction_type in ('purchase', 'commission', 'withdraw_request', 'withdraw_approved'):
            amount = -abs(amount)
        elif obj.transaction_type == 'refund' and obj.description.startswith('Refund issued:'):
            amount = -abs(amount)
        return str(amount)

    def get_display_amount(self, obj):
        return str(abs(Decimal(self.get_signed_amount(obj))))

    def get_is_debit(self, obj):
        return Decimal(self.get_signed_amount(obj)) < 0


class TopUpRequestSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment_proof_url = serializers.SerializerMethodField()

    class Meta:
        model = TopUpRequest
        fields = [
            'id', 'amount', 'payment_method', 'payment_proof_url',
            'transaction_id', 'status', 'status_display',
            'admin_note', 'created_at', 'reviewed_at',
        ]

    def get_payment_proof_url(self, obj):
        if obj.payment_proof:
            request = self.context.get('request')
            return build_private_media_url(request, 'topup-proof', obj.pk, 'topup_proof')
        return None


MIN_TOPUP_AMOUNT = Decimal('500.00')
MIN_TOPUP_ERROR = 'Minimum top-up is PKR 500.'
MAX_PURCHASE_QUANTITY = 1000  # per-order cap for standard/offer listings
MAX_PURCHASE_QUANTITY_ERROR = 'Quantity cannot exceed 1000 per order.'
# Currency listings (coins sold per Million etc.) are bought in much larger
# unit counts — the serializer only sanity-bounds them; real limits are the
# listing's stock and the order-total cap enforced at purchase time.
MAX_CURRENCY_PURCHASE_QUANTITY = 100_000_000
MAX_CURRENCY_PURCHASE_QUANTITY_ERROR = 'Quantity is too large.'


class CreateTopUpRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=MIN_TOPUP_AMOUNT,
        max_value=Decimal('10000.00'),
        error_messages={
            'min_value': MIN_TOPUP_ERROR,
            'max_value': 'Max is 10000. Please contact support if you want to add more.',
        },
    )
    payment_method = serializers.CharField(max_length=200, required=False, default='', allow_blank=True)
    transaction_id = serializers.CharField(max_length=200, allow_blank=False, trim_whitespace=True)

    def validate(self, attrs):
        payment_method = attrs.get('payment_method', '').strip()
        transaction_id = attrs['transaction_id'].strip()

        if TopUpRequest.objects.filter(
            status__in=['pending', 'approved'],
            payment_method__iexact=payment_method,
            transaction_id__iexact=transaction_id,
        ).exists():
            raise serializers.ValidationError({
                'transaction_id': 'This transaction reference has already been submitted.',
            })

        attrs['payment_method'] = payment_method
        attrs['transaction_id'] = transaction_id
        return attrs


PAKISTAN_MOBILE_REGEX = r'^03[0-9]{9}$'
PAKISTAN_MOBILE_ERROR = 'Enter a valid mobile wallet number (e.g., 03001234567).'
MAX_JAZZCASH_TOPUP_AMOUNT = Decimal('10000.00')


class JazzCashTopUpInitiateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=MIN_TOPUP_AMOUNT,
        max_value=MAX_JAZZCASH_TOPUP_AMOUNT,
        error_messages={
            'min_value': MIN_TOPUP_ERROR,
            'max_value': 'Max is 10000. Please contact support if you want to add more.',
        },
    )
    mobile_number = serializers.RegexField(
        PAKISTAN_MOBILE_REGEX,
        error_messages={'invalid': PAKISTAN_MOBILE_ERROR},
    )


class JazzCashBuyInitiateSerializer(serializers.Serializer):
    listing_id = serializers.IntegerField()
    quantity = serializers.IntegerField(
        min_value=1,
        max_value=MAX_CURRENCY_PURCHASE_QUANTITY,
        default=1,
        error_messages={'max_value': MAX_CURRENCY_PURCHASE_QUANTITY_ERROR},
    )
    mobile_number = serializers.RegexField(
        PAKISTAN_MOBILE_REGEX,
        error_messages={'invalid': PAKISTAN_MOBILE_ERROR},
    )
    # Buyer checkout info for auto-fulfilled top-ups (e.g. {"player_id": ...}).
    checkout_fields = serializers.DictField(
        child=serializers.CharField(max_length=100, allow_blank=True),
        required=False,
        default=dict,
    )


class JazzCashPaymentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    order_id = serializers.IntegerField(read_only=True)
    order_number = serializers.SerializerMethodField()
    user_message = serializers.SerializerMethodField()

    class Meta:
        model = JazzCashPayment
        fields = [
            'id', 'purpose', 'amount', 'mobile_number', 'txn_ref_no',
            'status', 'status_display', 'response_message', 'note',
            'user_message', 'order_id', 'order_number', 'created_at', 'completed_at',
        ]

    def get_order_number(self, obj):
        return obj.order.order_number if obj.order_id else None

    def get_user_message(self, obj):
        # response_message is the gateway's own wording ("A confirmer sends the
        # short message 'N' to cancel a transaction.") and is meaningless to a
        # buyer. Show this instead; response_message stays for admin/debugging.
        if obj.status == 'completed':
            return ''
        if obj.status == 'pending':
            return (
                'Still waiting for you to approve this payment in your JazzCash '
                'app. It goes through automatically as soon as you approve it.'
            )
        outcome = (
            'Your order was not placed.' if obj.purpose == 'purchase'
            else 'Your wallet was not topped up.'
        )
        return (
            "Your JazzCash payment wasn't approved — it was declined, or the "
            f'request timed out on your phone. {outcome} Please try again; any '
            'amount that was deducted is reversed automatically.'
        )


class WithdrawRequestSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment_receipt_url = serializers.SerializerMethodField()
    account_title = serializers.SerializerMethodField()
    account_details = serializers.SerializerMethodField()

    def get_account_title(self, obj):
        return decrypt_sensitive_text(obj.account_title)

    def get_account_details(self, obj):
        return decrypt_sensitive_text(obj.account_details)

    class Meta:
        model = WithdrawRequest
        fields = [
            'id', 'amount', 'payment_method', 'account_title',
            'account_details', 'bank_name',
            'status', 'status_display',
            'admin_note', 'payment_receipt_url', 'created_at', 'reviewed_at',
        ]

    def get_payment_receipt_url(self, obj):
        if obj.payment_receipt:
            request = self.context.get('request')
            return build_private_media_url(request, 'withdraw-receipt', obj.pk, 'withdraw_receipt')
        return None


class CreateWithdrawRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('500.00'),
        error_messages={
            'min_value': 'Minimum withdrawal amount is PKR 500.',
        },
    )
    payment_method = serializers.CharField(max_length=200, required=True, allow_blank=False)
    account_title = serializers.CharField(max_length=300, required=True, allow_blank=False)
    account_details = serializers.CharField(max_length=500, required=True, allow_blank=False)
    bank_name = serializers.CharField(max_length=300, required=False, default='', allow_blank=True)

    def validate(self, attrs):
        attrs['payment_method'] = attrs['payment_method'].strip()
        attrs['account_title'] = attrs['account_title'].strip()
        attrs['account_details'] = attrs['account_details'].strip()
        attrs['bank_name'] = attrs.get('bank_name', '').strip()
        if attrs['payment_method'].lower() == 'bank transfer' and not attrs['bank_name']:
            raise serializers.ValidationError({
                'bank_name': 'Bank name is required for bank transfers.',
            })
        return attrs


# ── Order Serializers ────────────────────────────────────────────────────────

class OrderSerializer(serializers.ModelSerializer):
    buyer_id = serializers.IntegerField(source='buyer.id', read_only=True)
    buyer_name = serializers.CharField(source='buyer.username', read_only=True)
    seller_id = serializers.IntegerField(source='seller.id', read_only=True)
    seller_name = serializers.CharField(source='seller.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    listing_id = serializers.IntegerField(source='listing.id', read_only=True, default=None)
    conversation_id = serializers.IntegerField(source='conversation.id', read_only=True, default=None)
    delivery_note = serializers.SerializerMethodField()
    has_review = serializers.SerializerMethodField()
    review_data = serializers.SerializerMethodField()
    is_auto_delivery = serializers.SerializerMethodField()
    auto_delivery_data = serializers.SerializerMethodField()
    delivery_instructions = serializers.SerializerMethodField()
    auto_confirm_at = serializers.SerializerMethodField()
    seller_payout_status = serializers.SerializerMethodField()
    can_dispute = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'buyer_id', 'buyer_name', 'seller_id', 'seller_name',
            'listing_id', 'listing_title', 'quantity',
            'unit_price', 'total_amount',
            'commission_rate', 'commission_amount', 'seller_amount',
            'status', 'status_display',
            'delivery_note', 'dispute_reason',
            'conversation_id', 'has_review', 'review_data',
            'is_auto_delivery', 'auto_delivery_data',
            'delivery_instructions', 'delivered_at', 'auto_confirm_at',
            'buyer_protection_enabled', 'seller_payout_status', 'can_dispute',
            'seller_payout_available_at', 'seller_payout_released_at',
            'created_at', 'updated_at',
        ]

    def get_has_review(self, obj):
        # Use the annotated field if available (avoids a lazy-load query
        # per order on the OneToOneField reverse relation).
        if hasattr(obj, '_has_review_annotation'):
            return obj._has_review_annotation
        return hasattr(obj, 'review') and obj.review is not None

    def get_review_data(self, obj):
        """Return the full review object if present."""
        try:
            review = obj.review
        except Review.DoesNotExist:
            return None
        if review is None:
            return None
        return {
            'id': review.id,
            'rating': review.rating,
            'comment': review.comment,
            'reviewer_name': review.reviewer.username if review.reviewer_id else '',
            'seller_reply': review.seller_reply,
            'seller_reply_at': review.seller_reply_at,
            'created_at': review.created_at,
            'updated_at': review.updated_at,
        }

    def get_delivery_note(self, obj):
        return decrypt_sensitive_text(obj.delivery_note)

    def get_is_auto_delivery(self, obj):
        """Return the purchase-time auto-delivery snapshot."""
        return obj.was_auto_delivery

    def get_auto_delivery_data(self, obj):
        """Return auto delivery data from the delivery_note for auto orders."""
        if obj.delivery_note and obj.was_auto_delivery:
            return decrypt_sensitive_text(obj.delivery_note)
        return None

    def get_delivery_instructions(self, obj):
        """Return purchase-time instructions only to the buyer."""
        request = self.context.get('request')
        if request and getattr(request.user, 'id', None) != obj.buyer_id:
            return None
        if obj.delivery_instructions_snapshot:
            return obj.delivery_instructions_snapshot
        return None

    def get_auto_confirm_at(self, obj):
        """Return the deadline when delivered orders auto-complete."""
        return get_order_auto_confirm_at(obj)

    def _seller_payout_has_been_released(self, obj):
        cache = getattr(self, '_seller_payout_released_cache', None)
        if cache is None:
            cache = {}
            self._seller_payout_released_cache = cache
        if obj.pk in cache:
            return cache[obj.pk]

        if obj.seller_payout_released_at:
            cache[obj.pk] = True
            return cache[obj.pk]

        released_refs = self.context.get('released_seller_payout_order_refs')
        if released_refs is not None:
            cache[obj.pk] = f'order_{obj.pk}' in released_refs
            return cache[obj.pk]

        cache[obj.pk] = order_seller_payout_has_been_released(obj)
        return cache[obj.pk]

    def get_seller_payout_status(self, obj):
        if obj.status == 'cancelled':
            return 'cancelled'
        if obj.status != 'completed':
            return 'pending'
        if self._seller_payout_has_been_released(obj):
            return 'released'
        if obj.buyer_protection_enabled:
            return 'held'
        return 'released'

    def get_can_dispute(self, obj):
        if obj.status in ('pending', 'delivered'):
            return True
        if obj.status != 'completed':
            return False
        if not obj.buyer_protection_enabled or not obj.seller_payout_available_at:
            return False
        if self._seller_payout_has_been_released(obj):
            return False
        return timezone.now() < obj.seller_payout_available_at


class BuyListingSerializer(serializers.Serializer):
    listing_id = serializers.IntegerField()
    quantity = serializers.IntegerField(
        min_value=1,
        max_value=MAX_CURRENCY_PURCHASE_QUANTITY,
        default=1,
        error_messages={'max_value': MAX_CURRENCY_PURCHASE_QUANTITY_ERROR},
    )
    # Buyer checkout info for auto-fulfilled top-ups (e.g. {"player_id": ...}).
    checkout_fields = serializers.DictField(
        child=serializers.CharField(max_length=100, allow_blank=True),
        required=False,
        default=dict,
    )


class DeliverOrderSerializer(serializers.Serializer):
    delivery_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=MAX_DELIVERY_NOTE_LENGTH,
        trim_whitespace=True,
    )


class DisputeOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(
        max_length=MAX_DISPUTE_REASON_LENGTH,
        trim_whitespace=True,
    )


# ── Review Serializers ───────────────────────────────────────────────────────

class ReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.CharField(source='reviewer.username', read_only=True)
    listing_title = serializers.CharField(source='order.listing_title', read_only=True)

    class Meta:
        model = Review
        fields = [
            'id', 'order', 'reviewer_name', 'seller',
            'rating', 'comment', 'listing_title',
            'seller_reply', 'seller_reply_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['order', 'seller', 'reviewer_name', 'listing_title',
                            'seller_reply', 'seller_reply_at', 'created_at', 'updated_at']


class CreateReviewSerializer(serializers.Serializer):
    order_id = serializers.CharField(max_length=32)
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, default='', max_length=2000)


class UpdateReviewSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, default='', max_length=2000)


class ReplyToReviewSerializer(serializers.Serializer):
    reply = serializers.CharField(max_length=2000, allow_blank=False)


# ── Notification Serializers ───────────────────────────────────────────────────

class NotificationSerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(read_only=True)
    order_number = serializers.SerializerMethodField()
    review_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id', 'notification_type', 'title', 'message',
            'is_read', 'order_id', 'order_number', 'review_id', 'created_at',
        ]

    def get_order_number(self, obj):
        if not obj.order_id:
            return None
        return getattr(obj.order, 'order_number', None)


# ── Report Serializers ───────────────────────────────────────────────────────

class CreateReportSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(choices=['listing', 'user'])
    listing_id = serializers.IntegerField(required=False)
    user_id = serializers.IntegerField(required=False)
    reason = serializers.ChoiceField(choices=[c[0] for c in Report.REASON_CHOICES])
    description = serializers.CharField(required=False, default='', max_length=2000, allow_blank=True)

    def validate(self, attrs):
        target_type = attrs['target_type']
        if target_type == 'listing':
            listing_id = attrs.get('listing_id')
            if not listing_id:
                raise serializers.ValidationError({'listing_id': 'Listing ID is required.'})
            if not Listing.objects.filter(pk=listing_id).exists():
                raise serializers.ValidationError({'listing_id': 'Listing not found.'})
        elif target_type == 'user':
            user_id = attrs.get('user_id')
            if not user_id:
                raise serializers.ValidationError({'user_id': 'User ID is required.'})
            from django.contrib.auth.models import User
            if not User.objects.filter(pk=user_id).exists():
                raise serializers.ValidationError({'user_id': 'User not found.'})
        return attrs


class ReportSerializer(serializers.ModelSerializer):
    reporter_name = serializers.CharField(source='reporter.username', read_only=True)
    reason_display = serializers.CharField(source='get_reason_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    target_display = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = [
            'id', 'target_type', 'reported_listing', 'reported_user',
            'reporter_name', 'reason', 'reason_display', 'description',
            'status', 'status_display', 'target_display', 'created_at',
        ]

    def get_target_display(self, obj):
        if obj.target_type == 'listing' and obj.reported_listing_id:
            return f'Listing: {obj.reported_listing.title[:60]}' if obj.reported_listing else f'Listing #{obj.reported_listing_id}'
        elif obj.target_type == 'user' and obj.reported_user_id:
            return f'User: {obj.reported_user.username}' if obj.reported_user else f'User #{obj.reported_user_id}'
        return 'Unknown'


# ── Support Ticket Serializers ───────────────────────────────────────────────

class CreateItemRequestSerializer(serializers.Serializer):
    """Capture buyer demand from an empty category. Works for guests too."""
    game_slug = serializers.SlugField()
    category_slug = serializers.SlugField()
    message = serializers.CharField(max_length=2000)
    email = serializers.EmailField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        request = self.context.get('request')
        is_authed = request and request.user.is_authenticated
        if not is_authed and not attrs.get('email'):
            raise serializers.ValidationError({
                'email': 'Email is required when not logged in.',
            })
        return attrs


class CreateSupportTicketSerializer(serializers.Serializer):
    """Create a support ticket. Works for both logged-in and guest users."""
    name = serializers.CharField(max_length=200, required=False, default='')
    email = serializers.EmailField(required=False, default='')
    category = serializers.ChoiceField(
        choices=SupportTicket.CATEGORY_CHOICES, default='other',
    )
    subject = serializers.CharField(max_length=300)
    message = serializers.CharField(max_length=5000)
    order_id = serializers.IntegerField(required=False, allow_null=True, default=None)

    def validate(self, attrs):
        request = self.context.get('request')
        is_authed = request and request.user.is_authenticated
        if not is_authed and not attrs.get('email'):
            raise serializers.ValidationError({
                'email': 'Email is required when not logged in.',
            })
        return attrs


class SupportTicketSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(
        source='get_category_display', read_only=True,
    )
    status_display = serializers.CharField(
        source='get_status_display', read_only=True,
    )

    class Meta:
        model = SupportTicket
        fields = [
            'id', 'category', 'category_display', 'subject', 'message',
            'order_id', 'status', 'status_display', 'admin_reply',
            'created_at', 'updated_at',
        ]
