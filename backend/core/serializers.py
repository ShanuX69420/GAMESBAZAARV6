from decimal import Decimal
from urllib.parse import urlencode
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.settings import api_settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User, update_last_login
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from .models import (
    Game, Category, GameCategory, Filter, FilterOption,
    GameCategoryFilter, UserProfile, Listing,
    Conversation, Message,
    Wallet, WalletTransaction, TopUpRequest, Order,
    SellerCommissionOverride, Review, Notification,
)
from .services import (
    create_private_media_ticket,
    decrypt_sensitive_text,
    encrypt_sensitive_text,
)


MAX_AUTO_DELIVERY_PAYLOAD_LENGTH = 100_000
MAX_AUTO_DELIVERY_LINES = 1_000
MAX_AUTO_DELIVERY_LINE_LENGTH = 2_000
MAX_DELIVERY_INSTRUCTIONS_LENGTH = 2_000


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
        fields = ['id', 'name', 'slug', 'description', 'icon']


class GameCategorySerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)

    class Meta:
        model = GameCategory
        fields = ['id', 'category', 'order']


class GameListSerializer(serializers.ModelSerializer):
    category_count = serializers.SerializerMethodField()
    icon_url = serializers.SerializerMethodField()

    class Meta:
        model = Game
        fields = ['id', 'name', 'slug', 'description', 'icon_url', 'category_count']

    def get_category_count(self, obj):
        return obj.game_categories.count()

    def get_icon_url(self, obj):
        if obj.icon:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.icon.url)
            return obj.icon.url
        return None


class GameDetailSerializer(serializers.ModelSerializer):
    categories = serializers.SerializerMethodField()
    icon_url = serializers.SerializerMethodField()

    class Meta:
        model = Game
        fields = ['id', 'name', 'slug', 'description', 'icon_url', 'categories']

    def get_categories(self, obj):
        game_categories = obj.game_categories.select_related('category').all()
        return GameCategorySerializer(game_categories, many=True).data

    def get_icon_url(self, obj):
        if obj.icon:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.icon.url)
            return obj.icon.url
        return None


class GameCategoryDetailSerializer(serializers.Serializer):
    game = serializers.SerializerMethodField()
    category = CategorySerializer()
    filters = serializers.SerializerMethodField()
    allow_auto_delivery = serializers.BooleanField(read_only=True)

    def get_game(self, obj):
        return {
            'id': obj.game.id,
            'name': obj.game.name,
            'slug': obj.game.slug,
        }

    def get_filters(self, obj):
        assigned = obj.assigned_filters.select_related('filter').prefetch_related('filter__options').all()
        return [FilterSerializer(gcf.filter).data for gcf in assigned]


# ── Auth Serializers ─────────────────────────────────────────────────────────

class RegisterSerializer(serializers.ModelSerializer):
    username = serializers.CharField(max_length=150, required=True)
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, min_length=6)
    password2 = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password2']

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
        try:
            with transaction.atomic():
                return User.objects.create_user(**validated_data)
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

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'seller_status', 'is_seller', 'wallet_balance',
                  'avatar_url', 'date_joined', 'username_changed_at']

    def get_wallet_balance(self, obj):
        wallet = getattr(obj, 'wallet', None)
        if wallet:
            return str(wallet.balance)
        return '0.00'

    def get_avatar_url(self, obj):
        profile = getattr(obj, 'profile', None)
        if profile and profile.avatar:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(profile.avatar.url)
            return profile.avatar.url
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
        profile = user.profile
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


class SellerApplicationSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=1000, required=True)


# ── Listing Serializers ──────────────────────────────────────────────────────

class ListingSerializer(serializers.ModelSerializer):
    seller_id = serializers.IntegerField(source='seller.id', read_only=True)
    seller_name = serializers.CharField(source='seller.username', read_only=True)
    seller_is_online = serializers.SerializerMethodField()
    seller_last_active = serializers.SerializerMethodField()
    seller_avatar_url = serializers.SerializerMethodField()
    game_name = serializers.CharField(source='game_category.game.name', read_only=True)
    category_name = serializers.CharField(source='game_category.category.name', read_only=True)
    filter_display = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = [
            'id', 'title', 'description', 'price', 'quantity', 'status',
            'seller_id', 'seller_name', 'seller_is_online', 'seller_last_active',
            'seller_avatar_url',
            'game_name', 'category_name',
            'filter_values', 'filter_display', 'delivery_time',
            'is_auto_delivery', 'delivery_instructions', 'created_at',
        ]

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
            if request:
                return request.build_absolute_uri(profile.avatar.url)
            return profile.avatar.url
        return None

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
                continue
            try:
                opt = FilterOption.objects.select_related('filter').get(
                    filter__id=int(filter_id_str), value=option_value
                )
                result[opt.filter.name] = opt.label
            except (FilterOption.DoesNotExist, ValueError):
                result[filter_id_str] = option_value
        return result


class CreateListingSerializer(serializers.ModelSerializer):
    game_slug = serializers.SlugField(write_only=True)
    category_slug = serializers.SlugField(write_only=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))
    quantity = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=1)
    is_auto_delivery = serializers.BooleanField(required=False, default=False)
    auto_delivery_data = serializers.CharField(
        required=False,
        default='',
        allow_blank=True,
        max_length=MAX_AUTO_DELIVERY_PAYLOAD_LENGTH,
    )
    delivery_instructions = serializers.CharField(
        required=False,
        default='',
        allow_blank=True,
        max_length=MAX_DELIVERY_INSTRUCTIONS_LENGTH,
    )

    class Meta:
        model = Listing
        fields = ['game_slug', 'category_slug', 'title', 'description', 'price', 'quantity',
                  'delivery_time', 'filter_values', 'is_auto_delivery', 'auto_delivery_data',
                  'delivery_instructions']

    def validate(self, attrs):
        game_slug = attrs.pop('game_slug')
        category_slug = attrs.pop('category_slug')
        try:
            gc = GameCategory.objects.get(
                game__slug=game_slug, category__slug=category_slug, game__is_active=True
            )
        except GameCategory.DoesNotExist:
            raise serializers.ValidationError('Invalid game/category combination.')
        attrs['game_category'] = gc

        # Validate auto-delivery
        is_auto = attrs.get('is_auto_delivery', False)
        if is_auto:
            if not gc.allow_auto_delivery:
                raise serializers.ValidationError({
                    'is_auto_delivery': 'Automated delivery is not allowed for this category.',
                })
            auto_data = attrs.get('auto_delivery_data', '').strip()
            if not auto_data:
                raise serializers.ValidationError({
                    'auto_delivery_data': 'Delivery data is required for automated delivery listings.',
                })
            # Force instant delivery for auto-delivery listings
            attrs['delivery_time'] = 'Instant'
            # Quantity = number of non-empty lines (each line = 1 deliverable item)
            lines = [line for line in auto_data.split('\n') if line.strip()]
            if len(lines) == 0:
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
            attrs['auto_delivery_data'] = encrypt_sensitive_text('\n'.join(lines))
            attrs['quantity'] = len(lines)
        else:
            # Manual listings cannot select Instant delivery
            delivery_time = attrs.get('delivery_time', '1-2 Hours')
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

        missing_filter_names = [
            gcf.filter.name
            for gcf in assigned_filters
            if str(gcf.filter_id) not in cleaned_filter_values
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

    class Meta:
        model = Listing
        fields = ['title', 'description', 'price', 'quantity', 'delivery_time', 'status']

    def validate(self, attrs):
        listing = self.instance
        next_status = attrs.get('status', listing.status)
        next_quantity = attrs.get('quantity', listing.quantity)
        next_delivery_time = attrs.get('delivery_time', listing.delivery_time)

        if listing.is_auto_delivery:
            if 'quantity' in attrs and next_quantity != listing.quantity:
                raise serializers.ValidationError({
                    'quantity': 'Automated delivery stock is controlled by delivery data.',
                })

            available_items = [
                line for line in decrypt_sensitive_text(listing.auto_delivery_data).splitlines()
                if line.strip()
            ]
            if next_status == 'active' and (
                not next_quantity or len(available_items) != next_quantity
            ):
                raise serializers.ValidationError({
                    'status': 'Add automated delivery data before activating this listing.',
                })

            attrs['delivery_time'] = 'Instant'
        elif next_delivery_time == 'Instant':
            raise serializers.ValidationError({
                'delivery_time': 'Instant delivery is only available for automated delivery listings.',
            })

        return attrs


# ── Chat Serializers ─────────────────────────────────────────────────────────

class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source='sender.username', read_only=True)
    sender_id = serializers.IntegerField(source='sender.id', read_only=True)
    is_mine = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ['id', 'sender_id', 'sender_name', 'content', 'image_url', 'is_read', 'is_mine', 'created_at']

    def get_is_mine(self, obj):
        request = self.context.get('request')
        if request:
            return obj.sender_id == request.user.id
        return False

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            return build_private_media_url(request, 'chat-message-image', obj.pk, 'chat_message_image')
        return None


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
                    if request:
                        avatar_url = request.build_absolute_uri(profile.avatar.url)
                    else:
                        avatar_url = profile.avatar.url
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
            return {
                'content': (getattr(obj, 'latest_message_content', '') or '')[:80],
                'sender_name': getattr(obj, 'latest_message_sender_name', '') or '',
                'created_at': latest_created_at,
            }

        prefetched_messages = getattr(obj, 'prefetched_messages_desc', None)
        if prefetched_messages is not None:
            msg = prefetched_messages[0] if prefetched_messages else None
        else:
            msg = obj.messages.order_by('-created_at').first()
        if msg:
            return {
                'content': msg.content[:80],
                'sender_name': msg.sender.username,
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
                    if request:
                        avatar_url = request.build_absolute_uri(profile.avatar.url)
                    else:
                        avatar_url = profile.avatar.url
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
            msgs = obj.messages.select_related('sender').all()
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
        if obj.transaction_type in ('purchase', 'commission'):
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


class CreateTopUpRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('1.00'),
        max_value=Decimal('10000.00'),
        error_messages={
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
    is_auto_delivery = serializers.SerializerMethodField()
    auto_delivery_data = serializers.SerializerMethodField()
    delivery_instructions = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'buyer_id', 'buyer_name', 'seller_id', 'seller_name',
            'listing_id', 'listing_title', 'quantity',
            'unit_price', 'total_amount',
            'commission_rate', 'commission_amount', 'seller_amount',
            'status', 'status_display',
            'delivery_note', 'dispute_reason',
            'conversation_id', 'has_review',
            'is_auto_delivery', 'auto_delivery_data',
            'delivery_instructions',
            'created_at', 'updated_at',
        ]

    def get_has_review(self, obj):
        return hasattr(obj, 'review') and obj.review is not None

    def get_delivery_note(self, obj):
        return decrypt_sensitive_text(obj.delivery_note)

    def get_is_auto_delivery(self, obj):
        """Check if the original listing was an auto-delivery listing."""
        if obj.listing:
            return obj.listing.is_auto_delivery
        return False

    def get_auto_delivery_data(self, obj):
        """Return auto delivery data from the delivery_note for auto orders."""
        # Auto delivery data is stored in delivery_note on the order
        if obj.delivery_note and obj.listing and obj.listing.is_auto_delivery:
            return decrypt_sensitive_text(obj.delivery_note)
        return None

    def get_delivery_instructions(self, obj):
        """Return delivery instructions from the listing, if any."""
        if obj.listing and obj.listing.delivery_instructions:
            return obj.listing.delivery_instructions
        return None


class BuyListingSerializer(serializers.Serializer):
    listing_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, default=1)


# ── Review Serializers ───────────────────────────────────────────────────────

class ReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.CharField(source='reviewer.username', read_only=True)
    listing_title = serializers.CharField(source='order.listing_title', read_only=True)

    class Meta:
        model = Review
        fields = [
            'id', 'order', 'reviewer_name', 'seller',
            'rating', 'comment', 'listing_title', 'created_at',
        ]
        read_only_fields = ['order', 'seller', 'reviewer_name', 'listing_title', 'created_at']


class CreateReviewSerializer(serializers.Serializer):
    order_id = serializers.IntegerField()
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, default='', max_length=2000)


# ── Notification Serializers ───────────────────────────────────────────────────

class NotificationSerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(read_only=True)
    review_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id', 'notification_type', 'title', 'message',
            'is_read', 'order_id', 'review_id', 'created_at',
        ]
