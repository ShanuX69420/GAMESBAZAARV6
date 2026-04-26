from decimal import Decimal
from urllib.parse import urlencode
from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse
from .models import (
    Game, Category, GameCategory, Filter, FilterOption,
    GameCategoryFilter, UserProfile, Listing,
    Conversation, Message,
    Wallet, WalletTransaction, TopUpRequest, Order,
    SellerCommissionOverride, Review, Notification,
)
from .services import create_private_media_ticket


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
    password = serializers.CharField(write_only=True, min_length=6)
    password2 = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password2']

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
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
        user = User.objects.create_user(**validated_data)
        return user


class UserSerializer(serializers.ModelSerializer):
    seller_status = serializers.CharField(source='profile.seller_status', read_only=True)
    is_seller = serializers.BooleanField(source='profile.is_seller', read_only=True)
    wallet_balance = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'seller_status', 'is_seller', 'wallet_balance']

    def get_wallet_balance(self, obj):
        wallet = getattr(obj, 'wallet', None)
        if wallet:
            return str(wallet.balance)
        return '0.00'


class SellerApplicationSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=1000, required=True)


# ── Listing Serializers ──────────────────────────────────────────────────────

class ListingSerializer(serializers.ModelSerializer):
    seller_id = serializers.IntegerField(source='seller.id', read_only=True)
    seller_name = serializers.CharField(source='seller.username', read_only=True)
    seller_is_online = serializers.SerializerMethodField()
    seller_last_active = serializers.SerializerMethodField()
    game_name = serializers.CharField(source='game_category.game.name', read_only=True)
    category_name = serializers.CharField(source='game_category.category.name', read_only=True)
    filter_display = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = [
            'id', 'title', 'description', 'price', 'quantity', 'status',
            'seller_id', 'seller_name', 'seller_is_online', 'seller_last_active',
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
    auto_delivery_data = serializers.CharField(required=False, default='', allow_blank=True)
    delivery_instructions = serializers.CharField(required=False, default='', allow_blank=True)

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
            attrs['auto_delivery_data'] = auto_data
            # Force instant delivery for auto-delivery listings
            attrs['delivery_time'] = 'Instant'
            # Quantity = number of non-empty lines (each line = 1 deliverable item)
            lines = [line for line in auto_data.split('\n') if line.strip()]
            if len(lines) == 0:
                raise serializers.ValidationError({
                    'auto_delivery_data': 'Please enter at least one item.',
                })
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
                return {
                    'id': other.id,
                    'username': other.username,
                    'is_online': profile.is_online if profile else False,
                    'last_active': profile.last_active.isoformat() if profile and profile.last_active else None,
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
                return {
                    'id': other.id,
                    'username': other.username,
                    'is_online': profile.is_online if profile else False,
                    'last_active': profile.last_active.isoformat() if profile and profile.last_active else None,
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
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    payment_method = serializers.CharField(max_length=200, required=False, default='')
    transaction_id = serializers.CharField(max_length=200, required=False, default='')


# ── Order Serializers ────────────────────────────────────────────────────────

class OrderSerializer(serializers.ModelSerializer):
    buyer_id = serializers.IntegerField(source='buyer.id', read_only=True)
    buyer_name = serializers.CharField(source='buyer.username', read_only=True)
    seller_id = serializers.IntegerField(source='seller.id', read_only=True)
    seller_name = serializers.CharField(source='seller.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    listing_id = serializers.IntegerField(source='listing.id', read_only=True, default=None)
    conversation_id = serializers.IntegerField(source='conversation.id', read_only=True, default=None)
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

    def get_is_auto_delivery(self, obj):
        """Check if the original listing was an auto-delivery listing."""
        if obj.listing:
            return obj.listing.is_auto_delivery
        return False

    def get_auto_delivery_data(self, obj):
        """Return auto delivery data from the delivery_note for auto orders."""
        # Auto delivery data is stored in delivery_note on the order
        if obj.delivery_note and obj.listing and obj.listing.is_auto_delivery:
            return obj.delivery_note
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
