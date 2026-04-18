from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.urls import reverse
from .models import (
    Game, Category, GameCategory, Filter, FilterOption,
    GameCategoryFilter, UserProfile, Listing,
)


# ── Inlines ──────────────────────────────────────────────────────────────────

class GameCategoryInline(admin.TabularInline):
    """Inline to assign categories directly from the Game admin page."""
    model = GameCategory
    extra = 1
    autocomplete_fields = ['category']
    fields = ['category', 'order', 'manage_filters_link']
    readonly_fields = ['manage_filters_link']

    @admin.display(description='Filters')
    def manage_filters_link(self, obj):
        if obj.pk:
            url = reverse('admin:core_gamecategory_change', args=[obj.pk])
            count = obj.assigned_filters.count()
            label = f'{count} filter{"s" if count != 1 else ""}'
            return format_html('<a href="{}">⚙️ {} — manage</a>', url, label)
        return '—save game first—'


class FilterOptionInline(admin.TabularInline):
    """Inline to add options directly when creating/editing a filter."""
    model = FilterOption
    extra = 3
    fields = ['label', 'value', 'order']


class GameCategoryFilterInline(admin.TabularInline):
    """Inline to assign filters directly from the GameCategory admin page."""
    model = GameCategoryFilter
    extra = 1
    autocomplete_fields = ['filter']


# ── Visible in Sidebar ──────────────────────────────────────────────────────

@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'order', 'category_count', 'created_at']
    list_filter = ['is_active']
    list_editable = ['order', 'is_active']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [GameCategoryInline]

    @admin.display(description='Categories')
    def category_count(self, obj):
        return obj.game_categories.count()


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'icon', 'game_count', 'created_at']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}

    @admin.display(description='Used in Games')
    def game_count(self, obj):
        return obj.game_categories.count()


@admin.register(Filter)
class FilterAdmin(admin.ModelAdmin):
    list_display = ['name', 'filter_type', 'option_count', 'created_at']
    list_filter = ['filter_type']
    search_fields = ['name']
    inlines = [FilterOptionInline]

    @admin.display(description='Options')
    def option_count(self, obj):
        return obj.options.count()


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'seller_status', 'created_at', 'seller_reviewed_at']
    list_filter = ['seller_status']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['user', 'seller_application_note', 'created_at']
    actions = ['approve_sellers', 'reject_sellers']

    @admin.action(description='✅ Approve selected sellers')
    def approve_sellers(self, request, queryset):
        updated = queryset.filter(seller_status='pending').update(
            seller_status='approved',
            seller_reviewed_at=timezone.now(),
        )
        self.message_user(request, f'{updated} seller(s) approved.')

    @admin.action(description='❌ Reject selected sellers')
    def reject_sellers(self, request, queryset):
        updated = queryset.filter(seller_status='pending').update(
            seller_status='rejected',
            seller_reviewed_at=timezone.now(),
        )
        self.message_user(request, f'{updated} seller(s) rejected.')


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ['title', 'seller', 'game_category', 'price', 'status', 'created_at']
    list_filter = ['status', 'game_category__game']
    search_fields = ['title', 'seller__username']
    readonly_fields = ['seller', 'created_at', 'updated_at']


# ── Hidden from Sidebar (still accessible via links) ────────────────────────

class HiddenModelAdmin(admin.ModelAdmin):
    """Base class for models that should not appear in the sidebar."""
    def has_module_permission(self, request):
        return False

    def has_view_permission(self, request, obj=None):
        return True

    def has_change_permission(self, request, obj=None):
        return True

    def has_add_permission(self, request):
        return True

    def has_delete_permission(self, request, obj=None):
        return True


@admin.register(GameCategory)
class GameCategoryAdmin(HiddenModelAdmin):
    list_display = ['__str__', 'order', 'filter_count']
    list_filter = ['game']
    list_editable = ['order']
    search_fields = ['game__name', 'category__name']
    autocomplete_fields = ['game', 'category']
    inlines = [GameCategoryFilterInline]

    @admin.display(description='Filters')
    def filter_count(self, obj):
        return obj.assigned_filters.count()


@admin.register(FilterOption)
class FilterOptionAdmin(HiddenModelAdmin):
    list_display = ['label', 'value', 'filter', 'order']
    list_filter = ['filter']
    search_fields = ['label', 'value']


@admin.register(GameCategoryFilter)
class GameCategoryFilterAdmin(HiddenModelAdmin):
    list_display = ['__str__', 'order']
    list_filter = ['game_category__game']
    list_editable = ['order']
    autocomplete_fields = ['game_category', 'filter']


# ── Admin Site Customization ─────────────────────────────────────────────────

admin.site.site_header = '🎮 GamesBazaar Admin'
admin.site.site_title = 'GamesBazaar'
admin.site.index_title = 'Dashboard'
