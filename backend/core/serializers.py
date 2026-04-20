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
    SellerCommissionOverride, Review,
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
    game_name = serializers.CharField(source='game_category.game.name', read_only=True)
    category_name = serializers.CharField(source='game_category.category.name', read_only=True)
    filter_display = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = [
            'id', 'title', 'description', 'price', 'quantity', 'status',
            'seller_id', 'seller_name', 'game_name', 'category_name',
            'filter_values', 'filter_display', 'created_at',
        ]

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

    class Meta:
        model = Listing
        fields = ['game_slug', 'category_slug', 'title', 'description', 'price', 'quantity', 'filter_values']

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

        raw_filter_values = attrs.get('filter_values', {})
        if raw_filter_values in (None, ''):
            raw_filter_values = {}

        if not isinstance(raw_filter_values, dict):
            raise serializers.ValidationError({
                'filter_values': 'Filter values must be an object.',
            })

        assigned_filter_ids = set(
            GameCategoryFilter.objects.filter(game_category=gc).values_list('filter_id', flat=True)
        )
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
        fields = ['title', 'description', 'price', 'quantity', 'status']


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

    class Meta:
        model = WalletTransaction
        fields = [
            'id', 'transaction_type', 'transaction_type_display',
            'amount', 'balance_after', 'description', 'reference_id',
            'created_at',
        ]


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
            'created_at', 'updated_at',
        ]

    def get_has_review(self, obj):
        return hasattr(obj, 'review') and obj.review is not None


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
