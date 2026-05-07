from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils import timezone
from django.urls import reverse
from django.db import transaction
from .models import (
    Game, Category, GameCategory, Filter, FilterOption,
    GameCategoryFilter, UserProfile, Listing,
    Conversation, Message,
    Wallet, WalletTransaction, PlatformLedgerEntry,
    TopUpRequest, WithdrawRequest, Order, SellerCommissionOverride, Review,
    Notification, Report, SupportTicket,
)
from .services import (
    apply_wallet_delta_once,
    approve_topup_request,
    decrypt_sensitive_text,
    record_withdrawal_approval_once,
    release_order_funds_to_seller_once,
)
from .serializers import get_auto_delivery_inventory_lines

# Import the custom admin site and set it as the default
from .admin_dashboard import GamesBazaarAdminSite

# Replace the default admin site with our custom one
site = GamesBazaarAdminSite(name='admin')
admin.site = site
admin.sites.site = site

# Re-register User and Group (lost when we replaced the default site)
from django.contrib.auth.models import User, Group
from django.contrib.auth.admin import UserAdmin, GroupAdmin
admin.site.register(User, UserAdmin)
admin.site.register(Group, GroupAdmin)


# ── Inlines ──────────────────────────────────────────────────────────────────

class GameCategoryInline(admin.TabularInline):
    """Inline to assign categories directly from the Game admin page."""
    model = GameCategory
    extra = 1
    autocomplete_fields = ['category']
    fields = ['category', 'order', 'allow_auto_delivery', 'manage_filters_link']
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
    list_display = ['name', 'is_active', 'order', 'category_count', 'search_keywords_preview', 'created_at']
    list_filter = ['is_active']
    list_editable = ['order', 'is_active']
    search_fields = ['name', 'slug', 'search_keywords']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [GameCategoryInline]

    @admin.display(description='Categories')
    def category_count(self, obj):
        return obj.game_categories.count()

    @admin.display(description='Search Keywords')
    def search_keywords_preview(self, obj):
        if obj.search_keywords:
            return obj.search_keywords[:60] + ('...' if len(obj.search_keywords) > 60 else '')
        return '—'


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
    list_display = ['name', 'admin_label', 'filter_type', 'assigned_to', 'option_count', 'created_at']
    list_editable = ['admin_label']
    list_filter = ['filter_type']
    search_fields = ['name', 'admin_label']
    inlines = [FilterOptionInline]

    @admin.display(description='Options')
    def option_count(self, obj):
        return obj.options.count()

    @admin.display(description='Assigned To')
    def assigned_to(self, obj):
        count = obj.game_category_assignments.count()
        if not count:
            return '—'
        return f'{count} game categor{"ies" if count != 1 else "y"}'


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
    readonly_fields = ['seller', 'created_at', 'updated_at', 'auto_delivery_inventory']
    exclude = ['auto_delivery_data']

    @admin.display(description='Auto-delivery inventory')
    def auto_delivery_inventory(self, obj):
        if not obj or not obj.is_auto_delivery:
            return 'N/A'
        item_count = len(get_auto_delivery_inventory_lines(
            decrypt_sensitive_text(obj.auto_delivery_data)
        ))
        return f'{item_count} encrypted item{"s" if item_count != 1 else ""} stored'


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


@admin.register(WithdrawRequest)
class WithdrawRequestAdmin(admin.ModelAdmin):
    list_display = ['user', 'amount', 'payment_method', 'account_title', 'account_details', 'bank_name', 'status', 'created_at', 'reviewed_at']
    list_filter = ['status']
    search_fields = ['user__username', 'account_details', 'account_title']
    readonly_fields = ['user', 'amount', 'payment_method', 'account_title', 'account_details', 'bank_name', 'created_at']
    fields = ['user', 'amount', 'payment_method', 'account_title', 'account_details', 'bank_name',
              'status', 'admin_note', 'reviewed_at', 'created_at']
    actions = ['approve_withdrawals', 'reject_withdrawals']

    def save_model(self, request, obj, form, change):
        """Handle status changes via edit form."""
        if change and 'status' in form.changed_data:
            with transaction.atomic():
                locked = WithdrawRequest.objects.select_for_update().select_related('user').get(pk=obj.pk)
                previous_status = locked.status
                if previous_status != 'pending':
                    obj.status = previous_status
                    super().save_model(request, obj, form, change)
                    self.message_user(
                        request,
                        'Only pending withdrawals can be approved or rejected.',
                        level=messages.WARNING,
                    )
                    return

                if obj.reviewed_at is None:
                    obj.reviewed_at = timezone.now()
                super().save_model(request, obj, form, change)
                obj.refresh_from_db()

                if obj.status == 'rejected':
                    apply_wallet_delta_once(
                        obj.user,
                        delta=obj.amount,
                        transaction_type='withdraw_rejected',
                        amount=obj.amount,
                        description=f'Withdrawal rejected: PKR {obj.amount} returned',
                        reference_id=f'withdraw_{obj.pk}',
                    )
                elif obj.status == 'approved':
                    record_withdrawal_approval_once(obj)
            return
        super().save_model(request, obj, form, change)

    @admin.action(description='✅ Approve selected withdrawals')
    def approve_withdrawals(self, request, queryset):
        count = 0
        for wd_id in queryset.filter(status='pending').values_list('pk', flat=True):
            with transaction.atomic():
                wd = WithdrawRequest.objects.select_for_update().select_related('user').get(pk=wd_id)
                if wd.status != 'pending':
                    continue
                wd.status = 'approved'
                wd.reviewed_at = timezone.now()
                wd.save(update_fields=['status', 'reviewed_at'])
                record_withdrawal_approval_once(wd)
                count += 1
        self.message_user(request, f'{count} withdrawal(s) approved.')

    @admin.action(description='❌ Reject selected withdrawals (refund balance)')
    def reject_withdrawals(self, request, queryset):
        count = 0
        for wd_id in queryset.filter(status='pending').values_list('pk', flat=True):
            with transaction.atomic():
                wd = WithdrawRequest.objects.select_for_update().select_related('user').get(pk=wd_id)
                if wd.status != 'pending':
                    continue
                wd.status = 'rejected'
                wd.reviewed_at = timezone.now()
                wd.save(update_fields=['status', 'reviewed_at'])
                # Return funds
                apply_wallet_delta_once(
                    wd.user,
                    delta=wd.amount,
                    transaction_type='withdraw_rejected',
                    amount=wd.amount,
                    description=f'Withdrawal rejected: PKR {wd.amount} returned',
                    reference_id=f'withdraw_{wd.pk}',
                )
                count += 1
        self.message_user(request, f'{count} withdrawal(s) rejected and funds returned.')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'order_number', 'listing_title', 'buyer', 'seller', 'total_amount',
                    'commission_display', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['order_number', 'listing_title', 'buyer__username', 'seller__username']
    readonly_fields = ['order_number', 'buyer', 'seller', 'listing', 'listing_title', 'quantity',
                       'unit_price', 'total_amount', 'commission_rate',
                       'commission_amount', 'seller_amount', 'delivery_note_status',
                       'created_at', 'updated_at', 'chat_link']
    exclude = ['delivery_note', 'conversation']
    actions = ['refund_and_cancel', 'release_to_seller']

    @admin.display(description='Commission')
    def commission_display(self, obj):
        return f'{obj.commission_rate}% (PKR {obj.commission_amount})'

    @admin.display(description='Delivery note')
    def delivery_note_status(self, obj):
        if not obj or not obj.delivery_note:
            return 'Empty'
        return 'Stored, redacted'

    @admin.display(description='💬 Order Conversation')
    def chat_link(self, obj):
        if not obj or not obj.conversation_id:
            return format_html(
                '<span style="color:#94a3b8;">No conversation linked to this order</span>'
            )
        url = reverse('admin:conversation_chatbox', args=[obj.conversation_id])
        url += f'?order={obj.pk}'
        return format_html(
            '<a href="{}" style="display:inline-flex;align-items:center;gap:8px;'
            'padding:10px 20px;background:linear-gradient(135deg,#3b82f6,#2563eb);'
            'color:#fff;border-radius:10px;text-decoration:none;font-weight:600;'
            'font-size:0.9em;transition:all 0.2s;box-shadow:0 2px 6px rgba(37,99,235,0.3);"'
            ' onmouseover="this.style.transform=\'translateY(-1px)\';this.style.boxShadow=\'0 4px 12px rgba(37,99,235,0.4)\';"'
            ' onmouseout="this.style.transform=\'none\';this.style.boxShadow=\'0 2px 6px rgba(37,99,235,0.3)\';">'
            '💬 Open Chat &rarr;</a>'
            '&nbsp;&nbsp;'
            '<span style="color:#64748b;font-size:0.82em;">'
            '({})'
            '</span>',
            url,
            obj.conversation,
        )

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
                    if listing and listing.quantity is not None and not listing.is_auto_delivery:
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

                release_order_funds_to_seller_once(
                    order,
                    sale_description=f'Dispute resolved (seller): {order.listing_title}',
                    commission_description=f'Commission ({order.commission_rate}%): {order.listing_title}',
                    ledger_description=f'Commission collected: {order.listing_title}',
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
    list_display = ['__str__', 'order', 'allow_auto_delivery', 'filter_count']
    list_filter = ['game', 'allow_auto_delivery']
    list_editable = ['order', 'allow_auto_delivery']
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


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['id', 'recipient', 'notification_type', 'title', 'is_read', 'created_at']
    list_filter = ['notification_type', 'is_read']
    search_fields = ['recipient__username', 'title', 'message']
    raw_id_fields = ['recipient', 'order', 'review']
    readonly_fields = ['created_at']


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'reporter', 'target_type', 'target_display',
        'reason', 'status', 'created_at', 'reviewed_at',
    ]
    list_filter = ['status', 'target_type', 'reason']
    search_fields = [
        'reporter__username',
        'reported_user__username',
        'reported_listing__title',
        'description',
    ]
    readonly_fields = [
        'reporter', 'target_type', 'reported_listing', 'reported_user',
        'reason', 'description', 'created_at',
    ]
    fields = [
        'reporter', 'target_type', 'reported_listing', 'reported_user',
        'reason', 'description', 'status', 'admin_note',
        'reviewed_at', 'created_at',
    ]
    actions = ['mark_reviewed', 'mark_action_taken', 'dismiss_reports']

    @admin.display(description='Target')
    def target_display(self, obj):
        if obj.target_type == 'listing' and obj.reported_listing:
            return f'Listing: {obj.reported_listing.title[:40]}'
        elif obj.target_type == 'user' and obj.reported_user:
            return f'User: {obj.reported_user.username}'
        return '—'

    @admin.action(description='👁️ Mark as Reviewed')
    def mark_reviewed(self, request, queryset):
        updated = queryset.filter(status='pending').update(
            status='reviewed',
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f'{updated} report(s) marked as reviewed.')

    @admin.action(description='⚡ Mark as Action Taken')
    def mark_action_taken(self, request, queryset):
        updated = queryset.filter(status__in=('pending', 'reviewed')).update(
            status='action_taken',
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f'{updated} report(s) marked as action taken.')

    @admin.action(description='✖ Dismiss selected reports')
    def dismiss_reports(self, request, queryset):
        updated = queryset.filter(status__in=('pending', 'reviewed')).update(
            status='dismissed',
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f'{updated} report(s) dismissed.')


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'user_display', 'category', 'subject_preview',
        'status', 'priority', 'created_at', 'resolved_at',
    ]
    list_filter = ['status', 'category', 'priority']
    search_fields = [
        'user__username', 'guest_email', 'subject', 'message', 'name',
    ]
    readonly_fields = [
        'user', 'guest_email', 'name', 'category', 'subject',
        'message', 'order_id', 'created_at', 'updated_at',
    ]
    fields = [
        'user', 'guest_email', 'name', 'category', 'subject',
        'message', 'order_id', 'priority', 'status', 'admin_reply',
        'admin_note', 'resolved_at', 'created_at', 'updated_at',
    ]
    actions = ['mark_in_progress', 'mark_resolved', 'close_tickets']

    @admin.display(description='User')
    def user_display(self, obj):
        if obj.user:
            return obj.user.username
        return obj.guest_email or obj.name or 'Guest'

    @admin.display(description='Subject')
    def subject_preview(self, obj):
        return obj.subject[:50] + ('...' if len(obj.subject) > 50 else '')

    @admin.action(description='🔄 Mark as In Progress')
    def mark_in_progress(self, request, queryset):
        updated = queryset.filter(status='open').update(status='in_progress')
        self.message_user(request, f'{updated} ticket(s) marked as in progress.')

    @admin.action(description='✅ Mark as Resolved')
    def mark_resolved(self, request, queryset):
        updated = queryset.filter(
            status__in=('open', 'in_progress'),
        ).update(status='resolved', resolved_at=timezone.now())
        self.message_user(request, f'{updated} ticket(s) marked as resolved.')

    @admin.action(description='🔒 Close selected tickets')
    def close_tickets(self, request, queryset):
        updated = queryset.exclude(status='closed').update(status='closed')
        self.message_user(request, f'{updated} ticket(s) closed.')
