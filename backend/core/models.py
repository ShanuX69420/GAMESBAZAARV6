from decimal import Decimal
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils.text import slugify


class Game(models.Model):
    """A top-level game (e.g., Valorant, PUBG Mobile, Free Fire)."""
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    description = models.TextField(blank=True, default='')
    icon = models.ImageField(upload_to='game_icons/', blank=True, null=True,
                             help_text='Small icon/logo for the game (recommended: 64x64 or 128x128)')
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0, help_text='Display order (lower = first)')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']

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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Categories'
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
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='game_categories')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='game_categories')
    order = models.PositiveIntegerField(default=0, help_text='Display order within the game')

    class Meta:
        ordering = ['order']
        unique_together = ['game', 'category']
        verbose_name = 'Game Category'
        verbose_name_plural = 'Game Categories'

    def __str__(self):
        return f"{self.game.name} → {self.category.name}"


class Filter(models.Model):
    """A reusable filter definition (e.g., Rank, Region, Platform)."""
    FILTER_TYPE_CHOICES = [
        ('button', 'Button (chips/tags)'),
        ('dropdown', 'Dropdown (select)'),
    ]

    name = models.CharField(max_length=200)
    filter_type = models.CharField(max_length=20, choices=FILTER_TYPE_CHOICES, default='button')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_filter_type_display()})"


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
    seller_status = models.CharField(max_length=20, choices=SELLER_STATUS_CHOICES, default='none')
    seller_application_note = models.TextField(blank=True, default='',
                                                help_text='Why do you want to become a seller?')
    seller_reviewed_at = models.DateTimeField(null=True, blank=True)
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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    # Stores filter values as JSON: {"filter_id": "option_value", ...}
    filter_values = models.JSONField(default=dict, blank=True)
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
            GinIndex(fields=['filter_values'], name='listing_filter_values_gin'),
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
    """A message within a conversation."""
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE,
                                      related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='sent_messages')
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
        return f"{self.sender.username}: {self.content[:40] or '[image]'}"


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

    def __str__(self):
        return f"{self.user.username} — PKR {self.balance}"


class WalletTransaction(models.Model):
    """Logs every wallet balance change."""
    TYPE_CHOICES = [
        ('topup_request', 'Top-Up Request'),
        ('topup_approved', 'Top-Up Approved'),
        ('topup_rejected', 'Top-Up Rejected'),
        ('purchase', 'Purchase (Escrow)'),
        ('sale', 'Sale Received'),
        ('commission', 'Commission Deducted'),
        ('refund', 'Refund'),
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
    amount = models.DecimalField(max_digits=12, decimal_places=2)
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

    def __str__(self):
        return f"{self.user.username} — PKR {self.amount} — {self.get_status_display()}"


# ── Orders (Escrow) ──────────────────────────────────────────────────────────

class Order(models.Model):
    """Escrow-based order. Funds held until buyer confirms delivery."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),           # Buyer paid, waiting for seller
        ('delivered', 'Delivered'),        # Seller marked as delivered
        ('completed', 'Completed'),       # Buyer confirmed, funds released
        ('disputed', 'Disputed'),         # Buyer opened a dispute
        ('cancelled', 'Cancelled'),       # Order cancelled, funds refunded
    ]

    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name='orders_as_buyer')
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
    delivery_note = models.TextField(blank=True, default='',
                                      help_text='Seller can include delivery details')
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
        ]

    def __str__(self):
        return f"Order #{self.pk} — {self.listing_title} — {self.get_status_display()}"
