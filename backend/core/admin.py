from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils import timezone
from django.urls import reverse
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import UploadedFile
from .models import (
    Game, Category, GameCategory, CategoryOption, Filter, FilterOption,
    GameCategoryFilter, UserProfile, SocialAccount, Listing,
    Conversation, Message,
    Wallet, WalletTransaction, PlatformLedgerEntry,
    TopUpRequest, WithdrawRequest, Order, SellerCommissionOverride, Review,
    JazzCashPayment,
    Notification, Report, SupportTicket,
)
from .payments import run_status_inquiry
from .services import (
    apply_wallet_delta_once,
    approve_topup_request,
    complete_order_with_seller_payout,
    create_notification,
    decrypt_sensitive_text,
    record_withdrawal_approval_once,
    send_topup_status_email,
    send_withdraw_status_email,
    validate_uploaded_image,
    optimize_uploaded_image,
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
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin, GroupAdmin


def can_admin_message_user(user):
    return (
        user.is_superuser or
        (
            user.has_perm('core.view_conversation') and
            user.has_perm('core.add_message')
        )
    )


class GamesBazaarUserAdmin(BaseUserAdmin):
    """Custom User admin with a 'Message user' action and link."""
    list_display = list(BaseUserAdmin.list_display) + ['message_user_link']
    actions = list(BaseUserAdmin.actions or []) + ['send_admin_message']

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change and 'is_active' in form.changed_data:
            UserProfile.objects.filter(user=obj).update(email_verification_pending=False)

    @admin.display(description='Message')
    def message_user_link(self, obj):
        url = reverse('admin:admin_message_user', args=[obj.pk])
        return format_html(
            '<a href="{}" style="white-space:nowrap">💬 Message</a>',
            url,
        )

    @admin.action(description='💬 Message selected user')
    def send_admin_message(self, request, queryset):
        if not can_admin_message_user(request.user):
            raise PermissionDenied
        if queryset.count() != 1:
            self.message_user(
                request, 'Please select exactly one user to message.', level=messages.WARNING,
            )
            return
        user = queryset.first()
        from django.http import HttpResponseRedirect
        return HttpResponseRedirect(
            reverse('admin:admin_message_user', args=[user.pk])
        )


admin.site.register(User, GamesBazaarUserAdmin)
admin.site.register(Group, GroupAdmin)


# ── Inlines ──────────────────────────────────────────────────────────────────

class GameCategoryInline(admin.TabularInline):
    """Inline to assign categories directly from the Game admin page."""
    model = GameCategory
    extra = 1
    autocomplete_fields = ['category']
    fields = ['category', 'order', 'allow_auto_delivery', 'listing_mode',
              'manage_filters_link', 'manage_options_link']
    readonly_fields = ['manage_filters_link', 'manage_options_link']

    @admin.display(description='Filters')
    def manage_filters_link(self, obj):
        if obj.pk:
            url = reverse('admin:core_gamecategory_change', args=[obj.pk])
            count = obj.assigned_filters.count()
            label = f'{count} filter{"s" if count != 1 else ""}'
            return format_html('<a href="{}">⚙️ {} — manage</a>', url, label)
        return '—save game first—'

    @admin.display(description='Options')
    def manage_options_link(self, obj):
        if obj.pk:
            url = reverse('admin:core_gamecategory_change', args=[obj.pk])
            count = obj.options.count()
            label = f'{count} option{"s" if count != 1 else ""}'
            return format_html('<a href="{}">🧩 {} — manage</a>', url, label)
        return '—save game first—'


class CategoryOptionInlineForm(forms.ModelForm):
    class Meta:
        model = CategoryOption
        fields = '__all__'

    def clean_icon(self):
        icon = self.cleaned_data.get('icon')
        if isinstance(icon, UploadedFile):
            validation_error = validate_uploaded_image(icon)
            if validation_error:
                raise forms.ValidationError(validation_error)
        return icon


class CategoryOptionInline(admin.TabularInline):
    """Inline to manage offer options (e.g., 60 UC / 325 UC) on a GameCategory."""
    model = CategoryOption
    form = CategoryOptionInlineForm
    extra = 1
    fields = ['name', 'icon', 'order', 'is_popular', 'offer_count']
    readonly_fields = ['offer_count']

    @admin.display(description='Active Offers')
    def offer_count(self, obj):
        if obj.pk:
            return obj.listings.filter(status='active').count()
        return '—'


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

class GameAdminForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = '__all__'

    def clean_icon(self):
        icon = self.cleaned_data.get('icon')
        if isinstance(icon, UploadedFile):
            validation_error = validate_uploaded_image(icon)
            if validation_error:
                raise forms.ValidationError(validation_error)
        return icon


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    form = GameAdminForm
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

    def save_model(self, request, obj, form, change):
        icon = form.cleaned_data.get('icon') if form else None
        if isinstance(icon, UploadedFile):
            obj.icon = optimize_uploaded_image(icon, preset='game_icon')
        super().save_model(request, obj, form, change)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'icon', 'commission_rate_display',
                    'buyer_protection_enabled', 'game_count', 'created_at']
    list_editable = ['buyer_protection_enabled']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    fields = ['name', 'slug', 'description', 'icon', 'commission_rate',
              'buyer_protection_enabled']

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
    actions = ['approve_sellers', 'reject_sellers', 'send_admin_message']

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

    @admin.action(description='💬 Send admin message to selected users')
    def send_admin_message(self, request, queryset):
        """Open the admin chatbox with each selected user."""
        if not can_admin_message_user(request.user):
            raise PermissionDenied
        if queryset.count() == 1:
            profile = queryset.first()
            # Import locally to avoid circular import
            from .views import get_or_create_private_conversation
            # Get or create conversation with this user
            conversation, _ = get_or_create_private_conversation(request.user, profile.user)
            from django.urls import reverse
            url = reverse('admin:conversation_chatbox', args=[conversation.pk])
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect(url)
        self.message_user(
            request,
            'Please select only one user to message.',
            level=messages.WARNING,
        )


@admin.register(SocialAccount)
class SocialAccountAdmin(admin.ModelAdmin):
    list_display = ['user', 'provider', 'email', 'created_at']
    list_filter = ['provider']
    search_fields = ['user__username', 'user__email', 'email', 'uid']
    autocomplete_fields = ['user']
    readonly_fields = ['provider', 'uid', 'email', 'created_at', 'updated_at']


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

    def _create_topup_notification(self, topup):
        """Create in-app notification for top-up status change."""
        if topup.status == 'approved':
            title = f'Top-up approved — PKR {topup.amount}'
            message = f'Your top-up request for PKR {topup.amount} has been approved and credited to your wallet.'
            if topup.admin_note:
                message += f'\n\nAdmin note: {topup.admin_note}'
            create_notification(
                recipient=topup.user,
                notification_type='topup_approved',
                title=title,
                message=message,
            )
        elif topup.status == 'rejected':
            title = f'Top-up rejected — PKR {topup.amount}'
            message = f'Your top-up request for PKR {topup.amount} was rejected.'
            if topup.admin_note:
                message += f'\n\nReason: {topup.admin_note}'
            else:
                message += ' Please check your wallet for details or contact support.'
            create_notification(
                recipient=topup.user,
                notification_type='topup_rejected',
                title=title,
                message=message,
            )

    def save_model(self, request, obj, form, change):
        """Handle status changes via edit form."""
        if change and 'status' in form.changed_data:
            with transaction.atomic():
                locked = TopUpRequest.objects.select_for_update().select_related('user').get(pk=obj.pk)
                previous_status = locked.status
                if previous_status != 'pending':
                    obj.status = previous_status
                    super().save_model(request, obj, form, change)
                    self.message_user(
                        request,
                        'Only pending top-ups can be approved or rejected.',
                        level=messages.WARNING,
                    )
                    return

                if obj.reviewed_at is None and obj.status in ('approved', 'rejected'):
                    obj.reviewed_at = timezone.now()
                super().save_model(request, obj, form, change)
                obj.refresh_from_db()
                if obj.status == 'approved':
                    approve_topup_request(obj)
                    self._create_topup_notification(obj)
                elif obj.status == 'rejected':
                    send_topup_status_email(obj)
                    self._create_topup_notification(obj)
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
                self._create_topup_notification(topup)
                count += 1
        self.message_user(request, f'{count} top-up(s) approved and wallets credited.')

    @admin.action(description='❌ Reject selected top-ups')
    def reject_topups(self, request, queryset):
        count = 0
        for topup_id in queryset.filter(status='pending').values_list('pk', flat=True):
            with transaction.atomic():
                topup = TopUpRequest.objects.select_for_update().select_related('user').get(pk=topup_id)
                if topup.status != 'pending':
                    continue
                topup.status = 'rejected'
                topup.reviewed_at = timezone.now()
                topup.save(update_fields=['status', 'reviewed_at'])
                send_topup_status_email(topup)
                self._create_topup_notification(topup)
                count += 1
        self.message_user(request, f'{count} top-up(s) rejected.')


@admin.register(JazzCashPayment)
class JazzCashPaymentAdmin(admin.ModelAdmin):
    """Read-only ledger of JazzCash gateway payments.

    Money movement is fully automated (IPN + status inquiry); the only admin
    action is forcing a status inquiry for stuck transactions.
    """
    list_display = ['txn_ref_no', 'user', 'purpose', 'amount', 'status',
                    'response_code', 'order', 'created_at', 'completed_at']
    list_filter = ['status', 'purpose']
    search_fields = ['txn_ref_no', 'user__username', 'mobile_number',
                     'retrieval_reference_no']
    readonly_fields = [
        'user', 'purpose', 'amount', 'mobile_number', 'txn_ref_no',
        'bill_reference', 'status', 'response_code', 'response_message',
        'retrieval_reference_no', 'note', 'listing', 'listing_quantity',
        'order', 'wallet_credited', 'last_status_inquiry_at', 'completed_at',
        'created_at', 'updated_at',
    ]
    actions = ['run_status_inquiries']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='🔄 Run JazzCash status inquiry')
    def run_status_inquiries(self, request, queryset):
        checked = 0
        completed = 0
        for payment in queryset.exclude(status='completed')[:25]:
            payment = run_status_inquiry(payment)
            checked += 1
            if payment.status == 'completed':
                completed += 1
        self.message_user(
            request,
            f'Status inquiry run for {checked} payment(s); {completed} completed.',
        )


@admin.register(WithdrawRequest)
class WithdrawRequestAdmin(admin.ModelAdmin):
    list_display = ['user', 'amount', 'payment_method', 'account_title', 'account_details', 'bank_name', 'status', 'created_at', 'reviewed_at']
    list_filter = ['status']
    search_fields = ['user__username', 'account_details', 'account_title']
    readonly_fields = ['user', 'amount', 'payment_method', 'account_title', 'account_details', 'bank_name', 'created_at']
    fields = ['user', 'amount', 'payment_method', 'account_title', 'account_details', 'bank_name',
              'status', 'admin_note', 'payment_receipt', 'reviewed_at', 'created_at']
    actions = ['approve_withdrawals', 'reject_withdrawals']

    def _create_withdraw_notification(self, wd):
        """Create in-app notification for withdrawal status change."""
        if wd.status == 'approved':
            title = f'Withdrawal approved — PKR {wd.amount}'
            message = f'Your withdrawal request for PKR {wd.amount} has been approved and sent via {wd.payment_method or "N/A"}.'
            if wd.payment_receipt:
                message += ' A payment receipt has been attached — check your wallet for details.'
            if wd.admin_note:
                message += f'\n\nAdmin note: {wd.admin_note}'
            create_notification(
                recipient=wd.user,
                notification_type='withdraw_approved',
                title=title,
                message=message,
            )
        elif wd.status == 'rejected':
            title = f'Withdrawal rejected — PKR {wd.amount}'
            message = f'Your withdrawal request for PKR {wd.amount} was rejected. The held amount has been returned to your wallet.'
            if wd.admin_note:
                message += f'\n\nReason: {wd.admin_note}'
            else:
                message += ' Please check your wallet for details or contact support.'
            create_notification(
                recipient=wd.user,
                notification_type='withdraw_rejected',
                title=title,
                message=message,
            )

    def save_model(self, request, obj, form, change):
        """Handle status changes via edit form."""
        # Validate receipt image if uploaded
        if 'payment_receipt' in form.changed_data and obj.payment_receipt:
            cleaned_data = getattr(form, 'cleaned_data', {}) or {}
            uploaded_receipt = cleaned_data.get('payment_receipt') or obj.payment_receipt
            validation_error = validate_uploaded_image(uploaded_receipt)
            if validation_error:
                self.message_user(request, f'Invalid receipt image: {validation_error}', level=messages.ERROR)
                return
            # Optimize the receipt image
            obj.payment_receipt = optimize_uploaded_image(uploaded_receipt, preset='proof')

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
                    _, returned = apply_wallet_delta_once(
                        obj.user,
                        delta=obj.amount,
                        transaction_type='withdraw_rejected',
                        amount=obj.amount,
                        description=f'Withdrawal rejected: PKR {obj.amount} returned',
                        reference_id=f'withdraw_{obj.pk}',
                    )
                    if returned:
                        send_withdraw_status_email(obj)
                    self._create_withdraw_notification(obj)
                elif obj.status == 'approved':
                    record_withdrawal_approval_once(obj)
                    self._create_withdraw_notification(obj)
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
                self._create_withdraw_notification(wd)
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
                _, returned = apply_wallet_delta_once(
                    wd.user,
                    delta=wd.amount,
                    transaction_type='withdraw_rejected',
                    amount=wd.amount,
                    description=f'Withdrawal rejected: PKR {wd.amount} returned',
                    reference_id=f'withdraw_{wd.pk}',
                )
                if returned:
                    send_withdraw_status_email(wd)
                self._create_withdraw_notification(wd)
                count += 1
        self.message_user(request, f'{count} withdrawal(s) rejected and funds returned.')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'order_number', 'listing_title', 'buyer', 'seller', 'total_amount',
                    'commission_display', 'buyer_protection_enabled', 'payout_display',
                    'status', 'created_at']
    list_filter = ['status', 'buyer_protection_enabled']
    search_fields = ['order_number', 'listing_title', 'buyer__username', 'seller__username']
    # status is read-only: editing it directly would skip the refund/payout
    # logic — use the refund_and_cancel / release_to_seller actions instead.
    readonly_fields = ['order_number', 'buyer', 'seller', 'listing', 'listing_title', 'quantity',
                       'unit_price', 'total_amount', 'commission_rate',
                       'commission_amount', 'seller_amount', 'status', 'delivery_note_status',
                       'delivered_at', 'buyer_protection_enabled',
                       'seller_payout_available_at', 'seller_payout_released_at',
                       'created_at', 'updated_at', 'chat_link']
    exclude = ['delivery_note', 'conversation']
    actions = ['refund_and_cancel', 'release_to_seller']

    @admin.display(description='Commission')
    def commission_display(self, obj):
        return f'{obj.commission_rate}% (PKR {obj.commission_amount})'

    @admin.display(description='Payout')
    def payout_display(self, obj):
        if obj.seller_payout_released_at:
            return 'Released'
        if obj.buyer_protection_enabled and obj.seller_payout_available_at:
            return f'Held until {timezone.localtime(obj.seller_payout_available_at):%Y-%m-%d %H:%M}'
        if obj.status == 'completed':
            return 'Released'
        return 'Pending'

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
                order = Order.objects.select_for_update().select_related('buyer', 'seller').get(pk=order_id)
                if order.status not in ('pending', 'delivered', 'disputed'):
                    continue
                was_disputed = order.status == 'disputed'

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
                create_notification(
                    recipient=order.buyer,
                    notification_type='order_cancelled',
                    title=(
                        'Dispute resolved - refund issued'
                        if was_disputed else 'Order cancelled - refund issued'
                    ),
                    message=(
                        f'Order "{order.listing_title}" was cancelled. '
                        'The order has been refunded.'
                    ),
                    order=order,
                )
                create_notification(
                    recipient=order.seller,
                    notification_type='order_cancelled',
                    title=(
                        'Dispute resolved - order cancelled'
                        if was_disputed else 'Order cancelled - buyer refunded'
                    ),
                    message=(
                        f'Order "{order.listing_title}" was cancelled and the buyer was refunded.'
                    ),
                    order=order,
                )
                count += 1
        self.message_user(request, f'{count} order(s) refunded and cancelled.')

    @admin.action(description='✅ Release to seller (resolve dispute in seller favor)')
    def release_to_seller(self, request, queryset):
        count = 0
        for order_id in queryset.filter(status='disputed').values_list('pk', flat=True):
            with transaction.atomic():
                order = Order.objects.select_for_update().select_related('buyer', 'seller').get(pk=order_id)
                if order.status != 'disputed':
                    continue

                complete_order_with_seller_payout(
                    order,
                    sale_description=f'Dispute resolved (seller): {order.listing_title}',
                    commission_description=f'Commission ({order.commission_rate}%): {order.listing_title}',
                    ledger_description=f'Commission collected: {order.listing_title}',
                )
                seller_title = 'Dispute resolved - order completed'
                seller_message = (
                    f'The dispute for "{order.listing_title}" was resolved in your favour. '
                    'The order is now marked as completed.'
                )
                create_notification(
                    recipient=order.seller,
                    notification_type='order_confirmed',
                    title=seller_title,
                    message=seller_message,
                    order=order,
                )
                create_notification(
                    recipient=order.buyer,
                    notification_type='order_confirmed',
                    title='Dispute resolved - order completed',
                    message=(
                        f'The dispute for "{order.listing_title}" was resolved. '
                        'The order is now marked as completed.'
                    ),
                    order=order,
                )
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
    list_display = ['__str__', 'order', 'allow_auto_delivery', 'listing_mode',
                    'filter_count', 'option_count']
    list_filter = ['game', 'allow_auto_delivery', 'listing_mode']
    list_editable = ['order', 'allow_auto_delivery', 'listing_mode']
    search_fields = ['game__name', 'category__name']
    autocomplete_fields = ['game', 'category']
    inlines = [GameCategoryFilterInline, CategoryOptionInline]

    @admin.display(description='Filters')
    def filter_count(self, obj):
        return obj.assigned_filters.count()

    @admin.display(description='Options')
    def option_count(self, obj):
        return obj.options.count()

    def save_formset(self, request, form, formset, change):
        if formset.model is CategoryOption:
            for inline_form in formset.forms:
                icon = inline_form.cleaned_data.get('icon') if inline_form.cleaned_data else None
                if isinstance(icon, UploadedFile):
                    inline_form.instance.icon = optimize_uploaded_image(icon, preset='game_icon')
        super().save_formset(request, form, formset, change)


@admin.register(CategoryOption)
class CategoryOptionAdmin(HiddenModelAdmin):
    list_display = ['name', 'game_category', 'order', 'is_popular']
    list_filter = ['game_category__game']
    list_editable = ['order', 'is_popular']
    search_fields = ['name', 'game_category__game__name', 'game_category__category__name']
    autocomplete_fields = ['game_category']


@admin.register(FilterOption)
class FilterOptionAdmin(HiddenModelAdmin):
    list_display = ['label', 'value', 'filter', 'order']
    list_filter = ['filter']
    search_fields = ['label', 'value']


@admin.register(GameCategoryFilter)
class GameCategoryFilterAdmin(HiddenModelAdmin):
    list_display = ['__str__', 'order', 'require_selection']
    list_filter = ['game_category__game']
    list_editable = ['order', 'require_selection']
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
