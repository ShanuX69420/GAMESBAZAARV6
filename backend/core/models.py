from django.db import models
from django.conf import settings
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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Categories'

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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'

    @property
    def is_seller(self):
        return self.seller_status == 'approved'

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
    price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    # Stores filter values as JSON: {"filter_id": "option_value", ...}
    filter_values = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} — PKR {self.price}"

