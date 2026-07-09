from decimal import Decimal
import secrets
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import models
from django.db.models.functions import Lower, Trim, Upper
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils.text import slugify


ORDER_NUMBER_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'


def generate_order_number():
    token = ''.join(secrets.choice(ORDER_NUMBER_ALPHABET) for _ in range(12))
    return f'GB-{token[:4]}-{token[4:8]}-{token[8:]}'


class Game(models.Model):
    """A top-level game (e.g., Valorant, PUBG Mobile, Free Fire)."""
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    description = models.TextField(blank=True, default='')
    icon = models.ImageField(upload_to='game_icons/', blank=True, null=True,
                             help_text='Small icon/logo for the game (recommended: 64x64 or 128x128)')
    search_keywords = models.TextField(
        blank=True, default='',
        help_text='Comma-separated search aliases (e.g., "gta, grand theft auto, gta5"). '
                  'Users searching these terms will find this game.',
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0, help_text='Display order (lower = first)')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        indexes = [
            # Expression indexes on UPPER(...) so __icontains (compiled to
            # UPPER(col) LIKE UPPER(%s) on PostgreSQL) can use them.
            GinIndex(
                OpClass(Upper('name'), name='gin_trgm_ops'),
                name='game_name_upper_trgm_idx',
            ),
            GinIndex(
                OpClass(Upper('search_keywords'), name='gin_trgm_ops'),
                name='game_keywords_upper_trgm_idx',
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Category(models.Model):
    """A reusable category (e.g., Accounts, Top-Up, Items, Boosting)."""
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    description = models.TextField(blank=True, default='')
    icon = models.CharField(max_length=10, blank=True, default='',
                            help_text='Emoji icon for the category (e.g., 🎮, 💰, ⚔️)')
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('5.00'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))],
        help_text='Default platform commission % for this category (e.g., 10.00 = 10%)',
    )
    buyer_protection_enabled = models.BooleanField(
        default=False,
        help_text='Hold seller payouts for 14 days after order completion in this category.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Categories'
        indexes = [
            GinIndex(
                OpClass(Upper('name'), name='gin_trgm_ops'),
                name='category_name_upper_trgm_idx',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(commission_rate__gte=Decimal('0.00')) &
                      models.Q(commission_rate__lte=Decimal('100.00')),
                name='category_commission_rate_0_100',
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class GameCategory(models.Model):
    """
    Assigns a category to a game. Explicit through-table so we can:
    - Control display order per game
    - Attach filters to specific game+category combos
    """
    LISTING_MODE_CHOICES = [
        ('standard', 'Standard (sellers list their own items)'),
        ('offer', 'Offers (admin-defined options, sellers compete on price)'),
        ('currency', 'Currency (per-unit pricing, buyers choose an amount)'),
    ]

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='game_categories')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='game_categories')
    display_name = models.CharField(
        max_length=200, blank=True, default='',
        help_text='Optional. What buyers see instead of the category name for this game '
                  '(e.g., "Subscriptions" instead of "Top Ups"). Leave blank to show the '
                  'category name as-is.',
    )
    display_slug = models.SlugField(max_length=200, blank=True, default='', editable=False)
    order = models.PositiveIntegerField(default=0, help_text='Display order within the game')
    featured = models.BooleanField(
        default=False,
        help_text='Pin this game to the top of its category\'s "Popular" panel '
                  'on the home page.',
    )
    allow_auto_delivery = models.BooleanField(
        default=False,
        help_text='Allow sellers to create automated delivery listings in this game+category.',
    )
    listing_mode = models.CharField(
        max_length=20, choices=LISTING_MODE_CHOICES, default='standard',
        help_text='Offers mode shows admin-defined options (e.g., 60 UC, 325 UC) '
                  'with competing seller offers — best for top-ups and subscriptions. '
                  'Currency mode sells stackable in-game currency by the unit '
                  '(e.g., 8 Ball Pool coins per Million) — set "Unit name" below.',
    )
    unit_name = models.CharField(
        max_length=20, blank=True, default='',
        help_text='Currency mode only: the unit buyers purchase in (e.g., "M" for '
                  'million coins, "K" for thousand). Seller prices are PKR per 1 unit.',
    )

    class Meta:
        ordering = ['order']
        unique_together = ['game', 'category']
        verbose_name = 'Game Category'
        verbose_name_plural = 'Game Categories'

    @property
    def effective_name(self):
        """Buyer-facing category name (display override or the category's own name)."""
        return self.display_name or self.category.name

    @property
    def effective_slug(self):
        """Buyer-facing URL slug (display override or the category's own slug)."""
        return self.display_slug or self.category.slug

    @classmethod
    def resolve_for_slug(cls, game_slug, category_slug, queryset=None):
        """Find the game-category a buyer-facing slug points to.

        Matches either the custom display slug or the category's own slug, so
        old links keep working after a rename. When both match different rows
        within a game, the display slug wins (a rename frees up the original
        slug for another category).
        """
        qs = (queryset if queryset is not None else cls.objects).filter(
            game__slug=game_slug, game__is_active=True,
        ).filter(
            models.Q(display_slug=category_slug) | models.Q(category__slug=category_slug)
        )
        matches = sorted(qs, key=lambda gc: 0 if gc.display_slug == category_slug else 1)
        return matches[0] if matches else None

    def clean(self):
        super().clean()
        if not self.game_id or not self.category_id:
            return
        if self.display_name:
            slug = slugify(self.display_name)
            if not slug:
                raise ValidationError(
                    {'display_name': 'Display name must contain letters or numbers.'})
        else:
            slug = self.category.slug
        siblings = (
            GameCategory.objects.filter(game_id=self.game_id)
            .exclude(pk=self.pk)
            .select_related('category')
        )
        for sibling in siblings:
            if slug in (sibling.display_slug, sibling.category.slug):
                field = 'display_name' if self.display_name else 'category'
                raise ValidationError({
                    field: f'The URL name "{slug}" is already used by the '
                           f'"{sibling.effective_name}" category in this game.',
                })

    def save(self, *args, **kwargs):
        self.display_slug = slugify(self.display_name) if self.display_name else ''
        super().save(*args, **kwargs)

    def __str__(self):
        label = f"{self.game.name} → {self.category.name}"
        if self.display_name:
            label += f' (shown as "{self.display_name}")'
        return label


class CategoryOption(models.Model):
    """A buyable option in an offers-mode game category (e.g., '60 UC', 'Plus — 1 Month')."""
    game_category = models.ForeignKey(GameCategory, on_delete=models.CASCADE,
                                      related_name='options')
    name = models.CharField(max_length=200, help_text='Shown to buyers (e.g., "60 UC")')
    icon = models.ImageField(upload_to='option_icons/', blank=True, null=True,
                             help_text='Small icon for the option (recommended: 64x64 or 128x128)')
    order = models.PositiveIntegerField(default=0, help_text='Display order (lower = first)')
    is_popular = models.BooleanField(
        default=False,
        help_text='Show a "Popular" badge and preselect this option on the browse page.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['game_category', 'name'],
                name='category_option_gc_name_uniq',
            ),
        ]

    def __str__(self):
        return f"{self.game_category} — {self.name}"


class Filter(models.Model):
    """A reusable filter definition (e.g., Rank, Region, Platform)."""
    FILTER_TYPE_CHOICES = [
        ('button', 'Button (chips/tags)'),
        ('dropdown', 'Dropdown (select)'),
    ]

    name = models.CharField(max_length=200)
    admin_label = models.CharField(
        max_length=300, blank=True, default='',
        help_text='Internal note for admin only (e.g., "Valorant Accounts - Rank"). '
                  'Not shown to users on the frontend.',
    )
    filter_type = models.CharField(max_length=20, choices=FILTER_TYPE_CHOICES, default='button')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        label = f"{self.name} ({self.get_filter_type_display()})"
        if self.admin_label:
            label += f" — {self.admin_label}"
        return label


class FilterOption(models.Model):
    """An individual option for a filter (e.g., 'Iron', 'Gold', 'Diamond' for Rank filter)."""
    filter = models.ForeignKey(Filter, on_delete=models.CASCADE, related_name='options')
    label = models.CharField(max_length=200, help_text='Display text')
    value = models.SlugField(max_length=200, help_text='URL-safe value')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'label']

    def save(self, *args, **kwargs):
        if not self.value:
            self.value = slugify(self.label)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.filter.name}: {self.label}"


class GameCategoryFilter(models.Model):
    """Assigns a filter to a specific game-category combination."""
    game_category = models.ForeignKey(GameCategory, on_delete=models.CASCADE,
                                       related_name='assigned_filters')
    filter = models.ForeignKey(Filter, on_delete=models.CASCADE,
                                related_name='game_category_assignments')
    order = models.PositiveIntegerField(default=0, help_text='Display order of this filter')
    require_selection = models.BooleanField(
        default=False,
        help_text='Buyers must pick a value for this filter before offers are shown '
                  '(e.g., Region for region-locked gift cards). Used by offers-mode categories.',
    )
    visible_when_options = models.ManyToManyField(
        FilterOption, blank=True,
        related_name='dependent_filter_assignments',
        help_text='Only show this filter after the buyer/seller picks ANY of these '
                  'options on another filter in the same category (e.g., show '
                  '"Region — Gift/Account" when Method = As a Gift OR By logging into '
                  'account). Leave empty to always show this filter.',
    )

    class Meta:
        ordering = ['order']
        unique_together = ['game_category', 'filter']
        verbose_name = 'Game Category Filter'
        verbose_name_plural = 'Game Category Filters'

    def __str__(self):
        return f"{self.game_category} — {self.filter.name}"


# ── User & Seller ────────────────────────────────────────────────────────────

class UserProfile(models.Model):
    """Extends the default User model with marketplace-related fields."""
    SELLER_STATUS_CHOICES = [
        ('none', 'Not Applied'),
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='profile')
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True,
                               help_text='Profile picture (recommended: 256x256)')
    username_changed_at = models.DateTimeField(null=True, blank=True,
                                               help_text='Last time the username was changed')
    seller_status = models.CharField(max_length=20, choices=SELLER_STATUS_CHOICES, default='none')
    seller_application_note = models.TextField(blank=True, default='',
                                                help_text='Why do you want to become a seller?')
    seller_reviewed_at = models.DateTimeField(null=True, blank=True)
    has_accepted_terms = models.BooleanField(
        default=False,
        help_text='Whether the user has accepted the Terms of Service and Privacy Policy.',
    )
    email_verification_pending = models.BooleanField(
        default=False,
        help_text='Whether password registration is awaiting email verification.',
    )
    last_active = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'

    @property
    def is_seller(self):
        return self.seller_status == 'approved'

    @property
    def is_online(self):
        if not self.last_active:
            return False
        from django.utils import timezone
        return (timezone.now() - self.last_active).total_seconds() < 120

    def __str__(self):
        return f"{self.user.username} ({self.get_seller_status_display()})"


# ── Listings ─────────────────────────────────────────────────────────────────

class SocialAccount(models.Model):
    """External sign-in identity linked to a local user account."""

    PROVIDER_GOOGLE = 'google'
    PROVIDER_CHOICES = [
        (PROVIDER_GOOGLE, 'Google'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='social_accounts')
    provider = models.CharField(max_length=30, choices=PROVIDER_CHOICES)
    uid = models.CharField(max_length=255)
    email = models.EmailField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'uid'],
                name='social_account_provider_uid_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'provider'], name='social_user_provider_idx'),
        ]

    def __str__(self):
        return f"{self.get_provider_display()} account for {self.user}"


class Listing(models.Model):
    """A seller's listing in the marketplace."""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('sold', 'Sold'),
        ('inactive', 'Inactive'),
    ]

    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name='listings')
    game_category = models.ForeignKey(GameCategory, on_delete=models.CASCADE,
                                       related_name='listings')
    option = models.ForeignKey(
        CategoryOption, on_delete=models.PROTECT, null=True, blank=True,
        related_name='listings',
        help_text='For offers-mode categories: the option this offer is for. '
                  'Title is kept in sync with the option name.',
    )
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True, default='')
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    quantity = models.PositiveIntegerField(
        null=True, blank=True, default=None,
        help_text='Available stock. Leave empty for unlimited (evergreen). Auto-deactivates when finite stock reaches 0.',
    )
    min_quantity = models.PositiveIntegerField(
        default=1,
        help_text='Currency mode: the smallest amount (in units) a buyer can '
                  'purchase per order. Always 1 for other modes.',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    # Stores filter values as JSON: {"filter_id": "option_value", ...}
    filter_values = models.JSONField(default=dict, blank=True)
    delivery_time = models.CharField(
        max_length=50, default='1-2 Hours', blank=True,
        help_text='Estimated delivery time (e.g., Instant, 1-2 Hours, 24 Hours)',
    )
    is_auto_delivery = models.BooleanField(
        default=False,
        help_text='If True, delivery data is sent automatically to buyers upon purchase.',
    )
    auto_delivery_data = models.TextField(
        blank=True, default='',
        help_text='Content delivered automatically to the buyer (e.g., account credentials, keys, codes).',
    )
    delivery_instructions = models.TextField(
        blank=True, default='',
        help_text='Optional instructions shown to every buyer (e.g., "Change password after receiving").',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['game_category', 'status', '-created_at'],
                name='listing_gc_status_created_idx',
            ),
            models.Index(
                fields=['seller', '-created_at'],
                name='listing_seller_created_idx',
            ),
            models.Index(
                fields=['option', 'status'],
                name='listing_option_status_idx',
            ),
            GinIndex(fields=['filter_values'], name='listing_filter_values_gin'),
            GinIndex(
                OpClass(Upper('title'), name='gin_trgm_ops'),
                name='listing_title_upper_trgm_idx',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(price__gt=Decimal('0.00')),
                name='listing_price_positive',
            ),
        ]

    def __str__(self):
        return f"{self.title} — PKR {self.price}"


# ── Chat ─────────────────────────────────────────────────────────────────────

class Conversation(models.Model):
    """A unified conversation between two users (not tied to orders/listings)."""
    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='conversations')
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        names = ', '.join(u.username for u in self.participants.all()[:2])
        return f"Chat: {names}"

    def other_user(self, user):
        """Return the other participant in the conversation."""
        return self.participants.exclude(id=user.id).first()


class Message(models.Model):
    """A message within a conversation.

    Besides regular user messages, a message can be posted by the platform
    itself (``sender`` is NULL) to announce order events, or by the system on
    the seller's behalf to hand over delivery data / instructions.
    """
    MESSAGE_TYPE_CHOICES = [
        ('text', 'Text'),
        ('system', 'System Notice'),
        ('delivery', 'Delivery Data'),
        ('instructions', 'Delivery Instructions'),
    ]
    SYSTEM_EVENT_CHOICES = [
        ('order_paid', 'Order Paid'),
        ('order_delivered', 'Order Delivered'),
        ('order_confirmed', 'Order Confirmed'),
        ('order_disputed', 'Order Disputed'),
        ('order_refunded', 'Order Refunded'),
        ('review_posted', 'Review Posted'),
        ('review_updated', 'Review Updated'),
    ]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE,
                                      related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='sent_messages', null=True, blank=True)
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPE_CHOICES,
                                    default='text')
    system_event = models.CharField(max_length=30, choices=SYSTEM_EVENT_CHOICES,
                                    blank=True, default='')
    order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True,
                              blank=True, related_name='order_messages')
    referenced_listing = models.ForeignKey(
        Listing,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_messages',
    )
    referenced_listing_title = models.CharField(max_length=300, blank=True, default='')
    referenced_listing_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    content = models.TextField(blank=True, default='')
    image = models.ImageField(upload_to='chat_images/', blank=True, null=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(
                fields=['conversation', '-id'],
                name='message_convo_id_desc_idx',
            ),
            models.Index(
                fields=['conversation', 'is_read', 'sender'],
                name='message_unread_sender_idx',
            ),
        ]

    def __str__(self):
        sender_name = self.sender.username if self.sender_id else 'GamesBazaar'
        return f"{sender_name}: {self.content[:40] or '[image]'}"


# ── Commission Overrides ─────────────────────────────────────────────────────

class SellerCommissionOverride(models.Model):
    """Per-seller commission rate overrides for specific categories.
    When set, this rate bypasses the category's default commission_rate.
    """
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name='commission_overrides')
    category = models.ForeignKey(Category, on_delete=models.CASCADE,
                                 related_name='commission_overrides')
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))],
        help_text='Custom commission % for this seller on this category',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['seller', 'category']
        verbose_name = 'Seller Commission Override'
        verbose_name_plural = 'Seller Commission Overrides'
        constraints = [
            models.CheckConstraint(
                check=models.Q(commission_rate__gte=Decimal('0.00')) &
                      models.Q(commission_rate__lte=Decimal('100.00')),
                name='seller_override_commission_rate_0_100',
            ),
        ]

    def __str__(self):
        return f"{self.seller.username} — {self.category.name}: {self.commission_rate}%"


# ── Wallet ───────────────────────────────────────────────────────────────────

class Wallet(models.Model):
    """Each user has one wallet with a balance."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(balance__gte=Decimal('0.00')),
                name='wallet_balance_non_negative',
            ),
        ]

    def __str__(self):
        return f"{self.user.username} — PKR {self.balance}"


class WalletTransaction(models.Model):
    """Logs every wallet balance change."""
    TYPE_CHOICES = [
        ('topup_request', 'Top-Up Request'),
        ('topup_approved', 'Top-Up Approved'),
        ('topup_rejected', 'Top-Up Rejected'),
        ('jazzcash_topup', 'JazzCash Payment'),
        ('purchase', 'Purchase'),
        ('sale', 'Sale Received'),
        ('commission', 'Commission Deducted'),
        ('refund', 'Refund'),
        ('withdraw_request', 'Withdraw Request'),
        ('withdraw_approved', 'Withdraw Approved'),
        ('withdraw_rejected', 'Withdraw Rejected'),
    ]

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2,
                                         help_text='Wallet balance after this transaction')
    description = models.CharField(max_length=500, blank=True, default='')
    reference_id = models.CharField(max_length=100, blank=True, default='',
                                     help_text='Order ID or top-up request ID for reference')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['wallet', '-created_at'],
                name='wallet_tx_wallet_created_idx',
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['wallet', 'transaction_type', 'reference_id'],
                condition=~models.Q(reference_id=''),
                name='uniq_wallet_tx_type_reference',
            ),
        ]

    def __str__(self):
        return f"{self.wallet.user.username} — {self.get_transaction_type_display()} — PKR {self.amount}"


class PlatformLedgerEntry(models.Model):
    """Signed ledger entries for platform-owned money such as commissions."""
    ENTRY_TYPE_CHOICES = [
        ('commission_collected', 'Commission Collected'),
        ('commission_reversed', 'Commission Reversed'),
    ]

    entry_type = models.CharField(max_length=40, choices=ENTRY_TYPE_CHOICES)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text='Signed amount. Positive credits platform revenue, negative reverses it.',
    )
    description = models.CharField(max_length=500, blank=True, default='')
    reference_id = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='Order ID or other external reference.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['entry_type', 'reference_id'],
                name='platform_ledger_ref_idx',
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['entry_type', 'reference_id'],
                condition=~models.Q(reference_id=''),
                name='uniq_platform_ledger_type_reference',
            ),
        ]

    def __str__(self):
        return f"{self.get_entry_type_display()} - PKR {self.amount}"


class TopUpRequest(models.Model):
    """Manual top-up request. Admin approves/rejects from Django admin."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='topup_requests')
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1.00'))],
    )
    payment_method = models.CharField(max_length=200, blank=True, default='',
                                       help_text='e.g., JazzCash, EasyPaisa, Bank Transfer')
    payment_proof = models.ImageField(upload_to='topup_proofs/', blank=True, null=True,
                                       help_text='Screenshot of payment')
    transaction_id = models.CharField(max_length=200, blank=True, default='',
                                       help_text='External payment transaction ID')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_note = models.TextField(blank=True, default='')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['user', '-created_at'],
                name='topup_user_created_idx',
            ),
            models.Index(
                fields=['status', '-created_at'],
                name='topup_status_created_idx',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gte=Decimal('1.00')),
                name='topup_amount_min_1',
            ),
            models.UniqueConstraint(
                Lower(Trim('payment_method')),
                Lower(Trim('transaction_id')),
                condition=models.Q(status__in=['pending', 'approved']) &
                          ~models.Q(transaction_id=''),
                name='uniq_active_topup_method_txid_ci',
            ),
        ]

    def save(self, *args, **kwargs):
        self.payment_method = (self.payment_method or '').strip()
        self.transaction_id = (self.transaction_id or '').strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} — PKR {self.amount} — {self.get_status_display()}"


class WithdrawRequest(models.Model):
    """Manual withdraw request. Admin approves/rejects from Django admin."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='withdraw_requests')
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('500.00'))],
    )
    payment_method = models.CharField(max_length=200, blank=True, default='',
                                       help_text='e.g., JazzCash, EasyPaisa, Bank Transfer')
    account_title = models.TextField(blank=True, default='',
                                     help_text='Name on the account (encrypted at rest)')
    account_details = models.TextField(blank=True, default='',
                                       help_text='Account number, IBAN, or mobile wallet number (encrypted at rest)')
    bank_name = models.CharField(max_length=300, blank=True, default='',
                                  help_text='Bank name (for bank transfers only)')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_note = models.TextField(blank=True, default='')
    payment_receipt = models.ImageField(
        upload_to='withdraw_receipts/', blank=True, null=True,
        help_text='Payment receipt/proof uploaded by admin after processing the withdrawal',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['user', '-created_at'],
                name='withdraw_user_created_idx',
            ),
            models.Index(
                fields=['status', '-created_at'],
                name='withdraw_status_created_idx',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gte=Decimal('500.00')),
                name='withdraw_amount_min_500',
            ),
        ]

    def __str__(self):
        return f"{self.user.username} — PKR {self.amount} — {self.get_status_display()}"


class JazzCashPayment(models.Model):
    """A JazzCash MWallet gateway transaction (instant top-up or direct buy).

    Successful payments always credit the user's wallet first (idempotently,
    keyed on ``jazzcash_<pk>``). Purchase-purpose payments only charge the
    buyer's wallet shortfall (at least the minimum top-up) and then execute
    the listing purchase, paid in full from the wallet; if the listing became
    unavailable while the customer was paying, the money safely stays in the
    wallet.
    """
    PURPOSE_CHOICES = [
        ('topup', 'Wallet Top-Up'),
        ('purchase', 'Direct Purchase'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='jazzcash_payments')
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1.00'))],
    )
    mobile_number = models.CharField(max_length=15,
                                     help_text='JazzCash mobile wallet number (e.g., 03001234567)')
    txn_ref_no = models.CharField(max_length=20, unique=True,
                                  help_text='pp_TxnRefNo sent to JazzCash')
    bill_reference = models.CharField(max_length=30, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    response_code = models.CharField(max_length=10, blank=True, default='')
    response_message = models.CharField(max_length=500, blank=True, default='')
    retrieval_reference_no = models.CharField(max_length=50, blank=True, default='')
    note = models.CharField(max_length=500, blank=True, default='')

    # Purchase-purpose payments
    listing = models.ForeignKey('Listing', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='jazzcash_payments')
    listing_quantity = models.PositiveIntegerField(default=1)
    order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='jazzcash_payments')

    wallet_credited = models.BooleanField(default=False)
    last_status_inquiry_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['user', '-created_at'],
                name='jazzcash_user_created_idx',
            ),
            models.Index(
                fields=['status', 'created_at'],
                name='jazzcash_status_created_idx',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gte=Decimal('1.00')),
                name='jazzcash_amount_min_1',
            ),
        ]

    def __str__(self):
        return f"{self.txn_ref_no} — {self.user.username} — PKR {self.amount} — {self.get_status_display()}"


# ── Orders (Escrow) ──────────────────────────────────────────────────────────

class Order(models.Model):
    """Escrow-based order. Funds held until buyer confirms delivery."""
    STATUS_CHOICES = [
        ('pending', 'Awaiting Delivery'), # Buyer paid, waiting for seller
        ('delivered', 'Delivered'),        # Seller marked as delivered
        ('completed', 'Completed'),       # Buyer confirmed, funds released
        ('disputed', 'Disputed'),         # Buyer opened a dispute
        ('cancelled', 'Cancelled'),       # Order cancelled, funds refunded
    ]

    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name='orders_as_buyer')
    order_number = models.CharField(max_length=17, unique=True,
                                    editable=False, blank=True)
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name='orders_as_seller')
    listing = models.ForeignKey(Listing, on_delete=models.SET_NULL, null=True,
                                related_name='orders')
    listing_title = models.CharField(max_length=300, help_text='Snapshot of listing title at purchase')
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2,
                                      help_text='Price per unit at time of purchase')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                       help_text='Total amount held in escrow')
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2,
                                          help_text='Commission % applied to this order')
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                            help_text='Platform commission deducted')
    seller_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                         help_text='Amount seller receives after commission')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    was_auto_delivery = models.BooleanField(
        default=False,
        help_text='Snapshot of whether this order was fulfilled by automated delivery.',
    )
    delivery_note = models.TextField(blank=True, default='',
                                      help_text='Seller can include delivery details')
    delivery_instructions_snapshot = models.TextField(
        blank=True,
        default='',
        help_text='Seller instructions captured at purchase time.',
    )
    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the order entered delivered status.',
    )
    buyer_protection_enabled = models.BooleanField(
        default=False,
        help_text='Snapshot of whether this order uses the 14-day buyer protection payout hold.',
    )
    seller_payout_available_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When held seller funds become eligible for release.',
    )
    seller_payout_released_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When seller funds were credited to the available wallet balance.',
    )
    dispute_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Link to conversation for easy access
    conversation = models.ForeignKey('Conversation', on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name='orders')

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['buyer', '-created_at'],
                name='order_buyer_created_idx',
            ),
            models.Index(
                fields=['seller', '-created_at'],
                name='order_seller_created_idx',
            ),
            models.Index(
                fields=['seller', 'status'],
                name='order_seller_status_idx',
            ),
            models.Index(
                fields=['status', '-created_at'],
                name='order_status_created_idx',
            ),
            models.Index(
                fields=['status', 'delivered_at'],
                name='order_status_deliv_idx',
            ),
            models.Index(
                fields=['status', 'seller_payout_available_at'],
                name='order_payout_due_idx',
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.order_number:
            order_number = generate_order_number()
            while Order.objects.filter(order_number=order_number).exists():
                order_number = generate_order_number()
            self.order_number = order_number
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = set(kwargs['update_fields']) | {'order_number'}
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Order #{self.order_number or self.pk} - {self.listing_title} - {self.get_status_display()}"


# ── Reviews ──────────────────────────────────────────────────────────────────

class Review(models.Model):
    """Buyer review of a seller after a completed order."""
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='review')
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews_given',
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews_received',
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text='1-5 star rating',
    )
    comment = models.TextField(blank=True, default='', help_text='Optional review text')
    seller_reply = models.TextField(blank=True, default='',
                                     help_text='Optional one-time seller reply')
    seller_reply_at = models.DateTimeField(null=True, blank=True,
                                            help_text='When the seller replied')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True,
                                       help_text='Set when the buyer edits the review')

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['seller', '-created_at'], name='review_seller_created_idx'),
        ]

    def __str__(self):
        return f"{self.reviewer.username} → {self.seller.username}: {self.rating}★"


# ── Notifications ────────────────────────────────────────────────────────────

class Notification(models.Model):
    """In-app notification for a user."""
    TYPE_CHOICES = [
        ('new_order', 'New Order'),                    # Seller: someone bought your listing
        ('order_delivered', 'Order Delivered'),         # Buyer: seller marked as delivered
        ('order_confirmed', 'Order Confirmed'),        # Seller: buyer confirmed delivery
        ('order_disputed', 'Order Disputed'),          # Seller: buyer opened a dispute
        ('order_cancelled', 'Order Cancelled'),        # Buyer/Seller: order cancelled/refunded
        ('new_review', 'New Review'),                  # Seller: buyer left a review
        ('topup_approved', 'Top-Up Approved'),         # User: admin approved top-up
        ('topup_rejected', 'Top-Up Rejected'),         # User: admin rejected top-up
        ('withdraw_approved', 'Withdraw Approved'),    # User: admin approved withdrawal
        ('withdraw_rejected', 'Withdraw Rejected'),    # User: admin rejected withdrawal
        ('admin_message', 'Admin Message'),            # User: admin sent a direct message
        ('item_request', 'Item Request'),              # Staff: buyer asked for an item with no listings
        ('seller_approved', 'Seller Application Approved'),  # User: admin approved seller application
        ('seller_rejected', 'Seller Application Rejected'),  # User: admin rejected seller application
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='notifications',
    )
    notification_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    title = models.CharField(max_length=300)
    message = models.TextField(blank=True, default='')
    is_read = models.BooleanField(default=False)

    # Optional links to related objects
    order = models.ForeignKey(
        'Order', on_delete=models.CASCADE, null=True, blank=True,
        related_name='notifications',
    )
    review = models.ForeignKey(
        'Review', on_delete=models.CASCADE, null=True, blank=True,
        related_name='notifications',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['recipient', '-created_at'],
                name='notif_recipient_created_idx',
            ),
            models.Index(
                fields=['recipient', 'is_read', '-created_at'],
                name='notif_recipient_unread_idx',
            ),
        ]

    def __str__(self):
        return f"{self.recipient.username}: {self.title}"


# ── Reports / Flags ─────────────────────────────────────────────────────────

class Report(models.Model):
    """User-submitted report / flag for listings or users."""
    TARGET_TYPE_CHOICES = [
        ('listing', 'Listing'),
        ('user', 'User'),
    ]

    REASON_CHOICES = [
        ('scam', 'Scam / Fraud'),
        ('inappropriate', 'Inappropriate Content'),
        ('duplicate', 'Duplicate / Spam'),
        ('wrong_category', 'Wrong Category'),
        ('misleading', 'Misleading Information'),
        ('harassment', 'Harassment / Abuse'),
        ('stolen', 'Stolen Account / Item'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('reviewed', 'Reviewed'),
        ('action_taken', 'Action Taken'),
        ('dismissed', 'Dismissed'),
    ]

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='reports_submitted',
    )
    target_type = models.CharField(max_length=20, choices=TARGET_TYPE_CHOICES)
    # One of these will be set depending on target_type
    reported_listing = models.ForeignKey(
        Listing, on_delete=models.CASCADE, null=True, blank=True,
        related_name='reports',
    )
    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name='reports_received',
    )
    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    description = models.TextField(
        blank=True, default='',
        help_text='Additional details about the report',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_note = models.TextField(blank=True, default='',
                                   help_text='Internal admin notes on this report')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['status', '-created_at'],
                name='report_status_created_idx',
            ),
            models.Index(
                fields=['reporter', '-created_at'],
                name='report_reporter_created_idx',
            ),
            models.Index(
                fields=['target_type', 'status'],
                name='report_target_status_idx',
            ),
        ]
        constraints = [
            # Prevent duplicate pending reports from same user on same listing
            models.UniqueConstraint(
                fields=['reporter', 'reported_listing'],
                condition=models.Q(status='pending', target_type='listing'),
                name='uniq_pending_listing_report',
            ),
            # Prevent duplicate pending reports from same user on same user
            models.UniqueConstraint(
                fields=['reporter', 'reported_user'],
                condition=models.Q(status='pending', target_type='user'),
                name='uniq_pending_user_report',
            ),
        ]

    def __str__(self):
        target = ''
        if self.target_type == 'listing' and self.reported_listing_id:
            target = f'Listing #{self.reported_listing_id}'
        elif self.target_type == 'user' and self.reported_user_id:
            target = f'User #{self.reported_user_id}'
        return f"Report by {self.reporter.username} → {target} ({self.get_status_display()})"


# ── Support Tickets ──────────────────────────────────────────────────────────

class SupportTicket(models.Model):
    """User-submitted support/contact ticket."""
    CATEGORY_CHOICES = [
        ('account', 'Account Issue'),
        ('order', 'Order Problem'),
        ('payment', 'Payment / Wallet'),
        ('seller', 'Seller Application'),
        ('report', 'Report / Safety'),
        ('feedback', 'Feedback / Suggestion'),
        ('other', 'Other'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]

    STATUS_CHOICES = [
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name='support_tickets',
        help_text='Null for guest (non-logged-in) submissions',
    )
    guest_email = models.EmailField(
        blank=True, default='',
        help_text='Email for non-logged-in users',
    )
    name = models.CharField(max_length=200, blank=True, default='',
                            help_text='Name provided by the user')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    subject = models.CharField(max_length=300)
    message = models.TextField()
    order_id = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Related order ID if applicable',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    admin_reply = models.TextField(blank=True, default='',
                                    help_text='Admin response to the user')
    admin_note = models.TextField(blank=True, default='',
                                   help_text='Internal admin notes (not visible to user)')
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['status', '-created_at'],
                name='support_ticket_status_idx',
            ),
            models.Index(
                fields=['user', '-created_at'],
                name='support_ticket_user_idx',
            ),
        ]

    def __str__(self):
        user_label = self.user.username if self.user else (self.guest_email or 'Guest')
        return f"Ticket #{self.pk} — {user_label} — {self.subject[:40]}"


class ItemRequest(models.Model):
    """Buyer demand captured from a category with no listings ("Request this item")."""
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('fulfilled', 'Fulfilled'),
        ('closed', 'Closed'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name='item_requests',
        help_text='Null for guest (non-logged-in) submissions',
    )
    guest_email = models.EmailField(
        blank=True, default='',
        help_text='Email for non-logged-in users',
    )
    game_category = models.ForeignKey(
        GameCategory, on_delete=models.CASCADE, related_name='item_requests',
    )
    message = models.TextField(help_text='What the buyer is looking for')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    admin_note = models.TextField(blank=True, default='',
                                  help_text='Internal admin notes (not visible to user)')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['status', '-created_at'],
                name='item_request_status_idx',
            ),
        ]

    def __str__(self):
        user_label = self.user.username if self.user else (self.guest_email or 'Guest')
        return f"Request #{self.pk} — {user_label} — {self.game_category}"
