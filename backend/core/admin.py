from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.urls import reverse
from django.db import transaction
from .models import (
    Game, Category, GameCategory, Filter, FilterOption,
    GameCategoryFilter, UserProfile, Listing,
    Conversation, Message,
    Wallet, WalletTransaction, PlatformLedgerEntry,
    TopUpRequest, Order, SellerCommissionOverride, Review,
)
from .services import (
    apply_wallet_delta_once,
    approve_topup_request,
    record_platform_ledger_once,
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
    list_display = ['name', 'slug', 'icon', 'commission_rate_display', 'game_count', 'created_at']
    list_editable = []
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    fields = ['name', 'slug', 'description', 'icon', 'commission_rate']

    @admin.display(description='Commission')
    def commission_rate_display(self, obj):
        return f'{obj.commission_rate}%'

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
    list_display = ['user', 'seller_status', 'wallet_balance', 'created_at', 'seller_reviewed_at']
    list_filter = ['seller_status']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['user', 'seller_application_note', 'created_at']
    actions = ['approve_sellers', 'reject_sellers']

    @admin.display(description='Wallet Balance')
    def wallet_balance(self, obj):
        wallet = getattr(obj.user, 'wallet', None)
        if wallet:
            return f'PKR {wallet.balance}'
        return 'N/A'

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
    list_display = ['title', 'seller', 'game_category', 'price', 'quantity', 'status', 'created_at']
    list_filter = ['status', 'game_category__game']
    search_fields = ['title', 'seller__username']
    readonly_fields = ['seller', 'created_at', 'updated_at']


# ── Wallet & Orders (Visible in Sidebar) ────────────────────────────────────

@admin.register(TopUpRequest)
class TopUpRequestAdmin(admin.ModelAdmin):
    list_display = ['user', 'amount', 'payment_method', 'status', 'created_at', 'reviewed_at']
    list_filter = ['status']
    search_fields = ['user__username', 'transaction_id']
    readonly_fields = ['user', 'amount', 'payment_method', 'transaction_id',
                       'payment_proof', 'created_at']
    fields = ['user', 'amount', 'payment_method', 'transaction_id',
              'payment_proof', 'status', 'admin_note', 'reviewed_at', 'created_at']
    actions = ['approve_topups', 'reject_topups']

    def save_model(self, request, obj, form, change):
        """Credit wallet when admin changes status to 'approved' via edit form."""
        if change and 'status' in form.changed_data and obj.status == 'approved':
            with transaction.atomic():
                TopUpRequest.objects.select_for_update().get(pk=obj.pk)
                super().save_model(request, obj, form, change)
                obj.refresh_from_db()
                approve_topup_request(obj)
            return
        super().save_model(request, obj, form, change)

    @admin.action(description='✅ Approve selected top-ups')
    def approve_topups(self, request, queryset):
        count = 0
        for topup_id in queryset.filter(status='pending').values_list('pk', flat=True):
            with transaction.atomic():
                topup = TopUpRequest.objects.select_for_update().select_related('user').get(pk=topup_id)
                if topup.status != 'pending':
                    continue
                approve_topup_request(topup)
                count += 1
        self.message_user(request, f'{count} top-up(s) approved and wallets credited.')

    @admin.action(description='❌ Reject selected top-ups')
    def reject_topups(self, request, queryset):
        updated = queryset.filter(status='pending').update(
            status='rejected',
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f'{updated} top-up(s) rejected.')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'listing_title', 'buyer', 'seller', 'total_amount',
                    'commission_display', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['listing_title', 'buyer__username', 'seller__username']
    readonly_fields = ['buyer', 'seller', 'listing', 'listing_title', 'quantity',
                       'unit_price', 'total_amount', 'commission_rate',
                       'commission_amount', 'seller_amount', 'created_at', 'updated_at']
    actions = ['refund_and_cancel', 'release_to_seller']

    @admin.display(description='Commission')
    def commission_display(self, obj):
        return f'{obj.commission_rate}% (PKR {obj.commission_amount})'

    @admin.action(description='💰 Refund buyer & cancel (for disputes)')
    def refund_and_cancel(self, request, queryset):
        count = 0
        for order_id in queryset.filter(status__in=('pending', 'delivered', 'disputed')).values_list('pk', flat=True):
            with transaction.atomic():
                order = Order.objects.select_for_update().select_related('buyer').get(pk=order_id)
                if order.status not in ('pending', 'delivered', 'disputed'):
                    continue

                apply_wallet_delta_once(
                    order.buyer,
                    delta=order.total_amount,
                    transaction_type='refund',
                    amount=order.total_amount,
                    description=f'Refund: {order.listing_title}',
                    reference_id=f'order_{order.pk}',
                )

                # Restore stock if listing still exists and has finite stock.
                if order.listing_id:
                    listing = Listing.objects.select_for_update().filter(pk=order.listing_id).first()
                    if listing and listing.quantity is not None:
                        listing.quantity += order.quantity
                        if listing.status == 'sold':
                            listing.status = 'active'
                        listing.save(update_fields=['quantity', 'status'])

                order.status = 'cancelled'
                order.save(update_fields=['status', 'updated_at'])
                count += 1
        self.message_user(request, f'{count} order(s) refunded and cancelled.')

    @admin.action(description='✅ Release to seller (resolve dispute in seller favor)')
    def release_to_seller(self, request, queryset):
        count = 0
        for order_id in queryset.filter(status='disputed').values_list('pk', flat=True):
            with transaction.atomic():
                order = Order.objects.select_for_update().select_related('seller').get(pk=order_id)
                if order.status != 'disputed':
                    continue

                apply_wallet_delta_once(
                    order.seller,
                    delta=order.seller_amount,
                    transaction_type='sale',
                    amount=order.seller_amount,
                    description=f'Dispute resolved (seller): {order.listing_title}',
                    reference_id=f'order_{order.pk}',
                )

                if order.commission_amount > 0:
                    apply_wallet_delta_once(
                        order.seller,
                        delta=0,
                        transaction_type='commission',
                        amount=order.commission_amount,
                        description=f'Commission ({order.commission_rate}%): {order.listing_title}',
                        reference_id=f'order_{order.pk}',
                    )
                    record_platform_ledger_once(
                        entry_type='commission_collected',
                        amount=order.commission_amount,
                        description=f'Commission collected: {order.listing_title}',
                        reference_id=f'order_{order.pk}',
                    )

                order.status = 'completed'
                order.save(update_fields=['status', 'updated_at'])
                count += 1
        self.message_user(request, f'{count} order(s) released to seller.')


@admin.register(SellerCommissionOverride)
class SellerCommissionOverrideAdmin(admin.ModelAdmin):
    list_display = ['seller', 'category', 'commission_rate', 'created_at']
    list_filter = ['category']
    search_fields = ['seller__username', 'category__name']
    autocomplete_fields = ['seller', 'category']


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['user', 'balance', 'updated_at']
    search_fields = ['user__username']
    readonly_fields = ['user', 'balance', 'updated_at', 'created_at']


# ── Hidden from Sidebar (still accessible via links) ────────────────────────

@admin.register(PlatformLedgerEntry)
class PlatformLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ['entry_type', 'amount', 'reference_id', 'created_at']
    list_filter = ['entry_type']
    search_fields = ['reference_id', 'description']
    readonly_fields = ['entry_type', 'amount', 'description', 'reference_id', 'created_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


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


# ── Chat Admin (hidden from sidebar) ─────────────────────────────────────────

class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ['sender', 'content', 'is_read', 'created_at']


@admin.register(Conversation)
class ConversationAdmin(HiddenModelAdmin):
    list_display = ['__str__', 'message_count', 'updated_at']
    inlines = [MessageInline]

    @admin.display(description='Messages')
    def message_count(self, obj):
        return obj.messages.count()


@admin.register(Message)
class MessageAdmin(HiddenModelAdmin):
    list_display = ['sender', 'content_preview', 'conversation', 'is_read', 'created_at']
    list_filter = ['is_read']

    @admin.display(description='Content')
    def content_preview(self, obj):
        return obj.content[:60]


@admin.register(WalletTransaction)
class WalletTransactionAdmin(HiddenModelAdmin):
    list_display = ['wallet', 'transaction_type', 'amount', 'balance_after', 'created_at']
    list_filter = ['transaction_type']
    search_fields = ['wallet__user__username', 'description']


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['id', 'reviewer', 'seller', 'rating', 'order', 'created_at']
    list_filter = ['rating']
    search_fields = ['reviewer__username', 'seller__username', 'comment']
    raw_id_fields = ['order', 'reviewer', 'seller']
