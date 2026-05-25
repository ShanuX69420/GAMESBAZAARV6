import base64
import hashlib
import secrets
import warnings
from datetime import timedelta
from decimal import Decimal
from time import time

from cryptography.fernet import Fernet, InvalidToken
from PIL import Image, UnidentifiedImageError
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.core import signing
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from .models import Listing, Notification, Order, PlatformLedgerEntry, Wallet, WalletTransaction


ALLOWED_IMAGE_CONTENT_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
ALLOWED_IMAGE_FORMATS = {'JPEG', 'PNG', 'WEBP'}
MAX_IMAGE_UPLOAD_SIZE = 5 * 1024 * 1024
MAX_IMAGE_WIDTH = 6000
MAX_IMAGE_HEIGHT = 6000
MAX_IMAGE_PIXELS = 24_000_000
MAX_CHAT_MESSAGE_LENGTH = 2000
CHAT_MESSAGE_EMPTY_ERROR = 'Message cannot be empty.'
CHAT_MESSAGE_NOT_TEXT_ERROR = 'Message must be text.'
CHAT_MESSAGE_TOO_LONG_ERROR = f'Message cannot be longer than {MAX_CHAT_MESSAGE_LENGTH} characters.'
CHAT_LISTING_REFERENCE_INVALID_ERROR = 'Listing reference is invalid for this conversation.'
CHAT_WS_MESSAGE_LIMIT = 20
CHAT_WS_MESSAGE_WINDOW_SECONDS = 60
CHAT_WS_RATE_LIMIT_CACHE_PREFIX = 'chat-ws-rate'
CHAT_WS_TICKET_MAX_AGE_SECONDS = 60
CHAT_WS_TICKET_CACHE_PREFIX = 'chat-ws-ticket'
CHAT_WS_TICKET_SALT = 'core.chat.websocket'
PRIVATE_MEDIA_TICKET_MAX_AGE_SECONDS = 5 * 60
PRIVATE_MEDIA_TICKET_SALT = 'core.private_media'
ENCRYPTED_TEXT_V1_PREFIX = 'enc:v1:'
ENCRYPTED_TEXT_V2_PREFIX = 'enc:v2:'
ENCRYPTED_TEXT_PREFIX = ENCRYPTED_TEXT_V1_PREFIX
CHALLENGE_MAX_FAILED_ATTEMPTS = 5
AUTO_CONFIRM_ORDER_AFTER = timedelta(hours=72)
BUYER_PROTECTION_HOLD = timedelta(days=14)

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


def _money(amount):
    return f'PKR {amount}'


def _order_reference(order):
    return order.order_number or f'#{order.pk}'


def _send_html_email(recipient_email, *, subject, template_name, context, fail_silently=None):
    """Render an HTML template and send as multipart email (HTML + plain text)."""
    if fail_silently is None:
        fail_silently = getattr(settings, 'TRANSACTIONAL_EMAIL_FAIL_SILENTLY', True)

    context.setdefault('email_subject', subject)
    html_body = render_to_string(template_name, context)

    # Build a minimal plain-text fallback from context
    text_parts = ['Hi,', '']
    if context.get('message_body'):
        text_parts.append(str(context['message_body']))
    if context.get('detail_rows'):
        for label, value in context['detail_rows']:
            text_parts.append(f'{label}: {value}')
    if context.get('status_text'):
        text_parts.append(f'Status: {context["status_text"]}')
    if context.get('admin_note'):
        text_parts.append(f'Admin note: {context["admin_note"]}')
    if context.get('extra_message'):
        text_parts.append(str(context['extra_message']))
    if context.get('code'):
        text_parts.append(f'Your code: {context["code"]}')
    text_parts.extend(['', 'GamesBazaar'])
    text_body = '\n'.join(text_parts)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient_email],
    )
    msg.attach_alternative(html_body, 'text/html')
    msg.send(fail_silently=fail_silently)


def send_transactional_email(user, *, subject, message_body, detail_rows=None,
                             status_text=None, status_class='info',
                             admin_note=None, extra_message=None):
    """Send a branded HTML transactional email to a user."""
    if not getattr(settings, 'TRANSACTIONAL_EMAILS_ENABLED', True):
        return False

    recipient = (getattr(user, 'email', '') or '').strip()
    if not recipient:
        return False

    username = getattr(user, 'username', '') or ''

    _send_html_email(
        recipient,
        subject=subject,
        template_name='email/transactional.html',
        context={
            'username': username,
            'message_body': message_body,
            'detail_rows': detail_rows or [],
            'status_text': status_text,
            'status_class': status_class,
            'admin_note': admin_note,
            'extra_message': extra_message,
        },
    )
    return True


def _basic_order_rows(order):
    """Return a list of (label, value) tuples for order detail cards."""
    return [
        ('Order', _order_reference(order)),
        ('Listing', order.listing_title),
        ('Quantity', str(order.quantity)),
    ]


def _build_order_notification_email(notification):
    order = notification.order
    is_buyer = notification.recipient_id == order.buyer_id
    is_seller = notification.recipient_id == order.seller_id
    title = notification.title or ''
    title_lower = title.lower()

    order_details = _basic_order_rows(order)

    if title_lower.startswith('dispute resolved'):
        if is_seller and 'favour' in (notification.message or '').lower():
            message = 'The dispute for this order was resolved in your favour.'
            status = ('Resolved — Your Favour', 'success')
        elif is_seller:
            message = 'The dispute for this order was resolved in favour of the buyer.'
            status = ('Resolved — Buyer Favour', 'warning')
        elif is_buyer and 'refund' in title_lower:
            message = 'The dispute for your order was resolved and the order was refunded.'
            status = ('Refunded', 'success')
        elif is_buyer:
            message = 'The dispute for your order has been resolved.'
            status = ('Resolved', 'info')
        else:
            return None
        return 'Dispute Result', message, order_details, status

    if notification.notification_type == 'new_order' and is_seller:
        rows = order_details + [('Order Total', _money(order.total_amount))]
        return 'New Order Received', 'A new order has been placed.', rows, ('New Order', 'info')

    if notification.notification_type == 'order_delivered' and is_buyer:
        return (
            'Order Delivered',
            'Your order has been delivered. Open the order page to review the delivery details.',
            order_details,
            ('Delivered', 'success'),
        )

    if notification.notification_type == 'order_confirmed' and is_seller:
        if (
            order_seller_payout_has_been_released(order)
            or order.seller_payout_released_at
        ):
            return 'Order Completed', 'This order has been completed.', order_details, ('Completed', 'success')
        return None

    if notification.notification_type == 'order_cancelled':
        if is_buyer:
            if 'refund' in title_lower or 'refund' in (notification.message or '').lower():
                return 'Order Refunded', 'Your order has been refunded.', order_details, ('Refunded', 'success')
            return 'Order Cancelled', 'Your order has been cancelled.', order_details, ('Cancelled', 'danger')
        return None

    if notification.notification_type == 'order_disputed' and is_seller:
        return 'Order Disputed', 'A dispute has been opened for this order.', order_details, ('Disputed', 'warning')

    return None


def send_notification_email(notification):
    """Send email only for marketplace events that should reach the inbox."""
    if not notification.order_id:
        return False

    email_payload = _build_order_notification_email(notification)
    if email_payload is None:
        return False

    subject_label, message_body, detail_rows, (status_text, status_class) = email_payload
    return send_transactional_email(
        notification.recipient,
        subject=f'GamesBazaar — {subject_label}',
        message_body=message_body,
        detail_rows=detail_rows,
        status_text=status_text,
        status_class=status_class,
    )


def create_notification(*, recipient, notification_type, title, message='', order=None, review=None):
    """Create an in-app notification and send the matching transactional email."""
    notification = Notification.objects.create(
        recipient=recipient,
        notification_type=notification_type,
        title=title,
        message=message,
        order=order,
        review=review,
    )
    send_notification_email(notification)
    return notification


def send_topup_request_received_email(topup):
    return send_transactional_email(
        topup.user,
        subject='GamesBazaar — Top-up Request Received',
        message_body=f'We received your top-up request for {_money(topup.amount)}.',
        detail_rows=[('Amount', _money(topup.amount))],
        status_text='Pending Review',
        status_class='warning',
        extra_message='We will email you again when it is approved or rejected.',
    )


def send_topup_status_email(topup):
    detail_rows = [('Amount', _money(topup.amount))]

    if topup.status == 'approved':
        message = f'Your top-up request for {_money(topup.amount)} has been approved.'
        extra = 'The funds have been credited to your wallet.'
        status_text, status_class = 'Approved', 'success'
    elif topup.status == 'rejected':
        message = f'Your top-up request for {_money(topup.amount)} was rejected.'
        extra = 'No funds were added to your wallet.'
        status_text, status_class = 'Rejected', 'danger'
    else:
        message = f'Your top-up request for {_money(topup.amount)} is now {topup.get_status_display()}.'
        extra = None
        status_text, status_class = topup.get_status_display(), 'info'

    return send_transactional_email(
        topup.user,
        subject=f'GamesBazaar — Top-up {topup.get_status_display()}',
        message_body=message,
        detail_rows=detail_rows,
        status_text=status_text,
        status_class=status_class,
        admin_note=topup.admin_note or None,
        extra_message=extra,
    )


def send_withdraw_request_received_email(withdraw):
    return send_transactional_email(
        withdraw.user,
        subject='GamesBazaar — Withdrawal Request Received',
        message_body=f'We received your withdrawal request for {_money(withdraw.amount)}.',
        detail_rows=[('Amount', _money(withdraw.amount))],
        status_text='Pending Review',
        status_class='warning',
        extra_message='The requested amount has been held from your wallet until the request is approved or rejected.',
    )


def send_withdraw_status_email(withdraw):
    detail_rows = [
        ('Amount', _money(withdraw.amount)),
    ]

    if withdraw.status == 'approved':
        message = f'Your withdrawal request for {_money(withdraw.amount)} has been approved.'
        extra = None
        status_text, status_class = 'Approved', 'success'
        detail_rows.append(('Payment Method', withdraw.payment_method or 'N/A'))
    elif withdraw.status == 'rejected':
        message = f'Your withdrawal request for {_money(withdraw.amount)} was rejected.'
        extra = 'The held amount has been returned to your wallet.'
        status_text, status_class = 'Rejected', 'danger'
    else:
        message = f'Your withdrawal request for {_money(withdraw.amount)} is now {withdraw.get_status_display()}.'
        extra = None
        status_text, status_class = withdraw.get_status_display(), 'info'

    return send_transactional_email(
        withdraw.user,
        subject=f'GamesBazaar — Withdrawal {withdraw.get_status_display()}',
        message_body=message,
        detail_rows=detail_rows,
        status_text=status_text,
        status_class=status_class,
        admin_note=withdraw.admin_note or None,
        extra_message=extra,
    )


def _legacy_sensitive_text_fernet():
    key = hashlib.sha256(str(settings.SECRET_KEY).encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _field_encryption_fernet(key_id):
    keys = getattr(settings, 'FIELD_ENCRYPTION_KEYS', {}) or {}
    key = keys.get(key_id)
    if not key:
        return None
    try:
        return Fernet(str(key).encode('ascii'))
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(
            f'FIELD_ENCRYPTION_KEYS contains an invalid Fernet key for "{key_id}".'
        ) from exc


def _primary_field_encryption_fernet():
    primary_key_id = getattr(settings, 'FIELD_ENCRYPTION_PRIMARY_KEY_ID', '')
    if not primary_key_id:
        return None, None
    fernet = _field_encryption_fernet(primary_key_id)
    if fernet is None:
        return None, None
    return primary_key_id, fernet


def encrypt_sensitive_text(value):
    """Encrypt sensitive text while accepting already-encrypted values."""
    if value in (None, ''):
        return ''
    text = str(value)
    if text.startswith(ENCRYPTED_TEXT_V1_PREFIX) or text.startswith(ENCRYPTED_TEXT_V2_PREFIX):
        return text
    key_id, fernet = _primary_field_encryption_fernet()
    if fernet is not None:
        token = fernet.encrypt(text.encode('utf-8')).decode('ascii')
        return f'{ENCRYPTED_TEXT_V2_PREFIX}{key_id}:{token}'

    token = _legacy_sensitive_text_fernet().encrypt(text.encode('utf-8')).decode('ascii')
    return f'{ENCRYPTED_TEXT_V1_PREFIX}{token}'


def decrypt_sensitive_text(value):
    """Decrypt sensitive text, leaving legacy plaintext rows readable."""
    if value in (None, ''):
        return ''
    text = str(value)
    if text.startswith(ENCRYPTED_TEXT_V2_PREFIX):
        try:
            key_id, token = text[len(ENCRYPTED_TEXT_V2_PREFIX):].split(':', 1)
            fernet = _field_encryption_fernet(key_id)
            if fernet is None:
                return ''
            return fernet.decrypt(token.encode('ascii')).decode('utf-8')
        except (InvalidToken, UnicodeDecodeError, ValueError):
            return ''

    if not text.startswith(ENCRYPTED_TEXT_V1_PREFIX):
        return text
    token = text[len(ENCRYPTED_TEXT_V1_PREFIX):]
    try:
        return _legacy_sensitive_text_fernet().decrypt(token.encode('ascii')).decode('utf-8')
    except (InvalidToken, UnicodeDecodeError, ValueError):
        return ''


def get_or_create_locked_wallet(user):
    """Return the user's wallet locked for the current transaction."""
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return Wallet.objects.select_for_update().get(pk=wallet.pk)


def revoke_user_refresh_tokens(user):
    """Blacklist every outstanding refresh token for a user."""
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


def apply_wallet_delta_once(user, *, delta, transaction_type, amount, description, reference_id):
    wallet = get_or_create_locked_wallet(user)
    if reference_id and WalletTransaction.objects.filter(
        wallet=wallet,
        transaction_type=transaction_type,
        reference_id=reference_id,
    ).exists():
        return wallet, False

    wallet.balance += delta
    wallet.save(update_fields=['balance', 'updated_at'])
    WalletTransaction.objects.create(
        wallet=wallet,
        transaction_type=transaction_type,
        amount=amount,
        balance_after=wallet.balance,
        description=description,
        reference_id=reference_id,
    )
    return wallet, True


def release_order_funds_to_seller_once(order, *, sale_description, commission_description, ledger_description):
    """Credit gross sale proceeds, then debit commission, once per order."""
    wallet = get_or_create_locked_wallet(order.seller)
    reference_id = f'order_{order.pk}'
    if WalletTransaction.objects.filter(
        wallet=wallet,
        transaction_type='sale',
        reference_id=reference_id,
    ).exists():
        if not order.seller_payout_released_at:
            order.seller_payout_released_at = timezone.now()
            order.save(update_fields=['seller_payout_released_at', 'updated_at'])
        return wallet, False

    wallet.balance += order.total_amount
    wallet.save(update_fields=['balance', 'updated_at'])
    WalletTransaction.objects.create(
        wallet=wallet,
        transaction_type='sale',
        amount=order.total_amount,
        balance_after=wallet.balance,
        description=sale_description,
        reference_id=reference_id,
    )

    if order.commission_amount > 0:
        wallet.balance -= order.commission_amount
        wallet.save(update_fields=['balance', 'updated_at'])
        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type='commission',
            amount=order.commission_amount,
            balance_after=wallet.balance,
            description=commission_description,
            reference_id=reference_id,
        )
        record_platform_ledger_once(
            entry_type='commission_collected',
            amount=order.commission_amount,
            description=ledger_description,
            reference_id=reference_id,
        )

    order.seller_payout_released_at = timezone.now()
    order.save(update_fields=['seller_payout_released_at', 'updated_at'])
    return wallet, True


def complete_order_with_seller_payout(order, *, sale_description, commission_description, ledger_description, completed_at=None):
    """Complete an order and either release seller funds now or schedule the hold."""
    completed_at = completed_at or timezone.now()
    if order.buyer_protection_enabled:
        if not order.seller_payout_available_at:
            order.seller_payout_available_at = completed_at + BUYER_PROTECTION_HOLD
        order.status = 'completed'
        order.save(update_fields=['status', 'seller_payout_available_at', 'updated_at'])
        return {
            'held': True,
            'released': False,
            'seller_payout_available_at': order.seller_payout_available_at,
        }

    _, released = release_order_funds_to_seller_once(
        order,
        sale_description=sale_description,
        commission_description=commission_description,
        ledger_description=ledger_description,
    )
    order.status = 'completed'
    order.save(update_fields=['status', 'updated_at'])
    return {
        'held': False,
        'released': released,
        'seller_payout_available_at': None,
    }


def order_seller_payout_has_been_released(order):
    """Return whether a completed order's seller payout is already available."""
    if order.status != 'completed':
        return False
    if not order.buyer_protection_enabled:
        return True
    if order.seller_payout_released_at:
        return True

    return WalletTransaction.objects.filter(
        wallet__user=order.seller,
        transaction_type='sale',
        reference_id=f'order_{order.pk}',
    ).exists()


def is_order_in_buyer_protection_dispute_window(order, *, now=None):
    """Return whether a completed order can still be disputed under buyer protection."""
    if (
        order.status != 'completed'
        or not order.buyer_protection_enabled
        or not order.seller_payout_available_at
        or order.seller_payout_released_at
    ):
        return False

    if order_seller_payout_has_been_released(order):
        return False

    now = now or timezone.now()
    return now < order.seller_payout_available_at


def get_order_auto_confirm_at(order):
    """Return when a delivered order becomes eligible for auto-confirmation."""
    if order.status != 'delivered' or not order.delivered_at:
        return None
    return order.delivered_at + AUTO_CONFIRM_ORDER_AFTER


def get_seller_held_payout_summary(user):
    held_orders = Order.objects.filter(
        seller=user,
        status='completed',
        buyer_protection_enabled=True,
        seller_payout_released_at__isnull=True,
    )
    summary = held_orders.aggregate(
        total=models.Sum('seller_amount'),
        count=models.Count('id'),
        next_release_at=models.Min('seller_payout_available_at'),
    )
    return {
        'held_balance': summary['total'] or Decimal('0.00'),
        'held_order_count': summary['count'] or 0,
        'next_release_at': summary['next_release_at'],
    }


def release_due_held_order_funds(*, now=None, batch_size=100, dry_run=False):
    """Release completed buyer-protected payouts whose 14-day hold has expired."""
    if batch_size < 1:
        raise ValueError('batch_size must be at least 1.')

    now = now or timezone.now()
    due_order_ids = list(
        Order.objects.filter(
            status='completed',
            buyer_protection_enabled=True,
            seller_payout_released_at__isnull=True,
            seller_payout_available_at__isnull=False,
            seller_payout_available_at__lte=now,
        )
        .order_by('seller_payout_available_at', 'pk')
        .values_list('pk', flat=True)[:batch_size]
    )

    if dry_run:
        return {
            'due_count': len(due_order_ids),
            'released_count': 0,
            'skipped_count': 0,
            'order_ids': due_order_ids,
        }

    released_order_ids = []
    skipped_count = 0

    for order_id in due_order_ids:
        with transaction.atomic():
            order = (
                Order.objects.select_for_update()
                .select_related('seller')
                .get(pk=order_id)
            )
            if (
                order.status != 'completed'
                or not order.buyer_protection_enabled
                or order.seller_payout_released_at
                or not order.seller_payout_available_at
                or order.seller_payout_available_at > now
            ):
                skipped_count += 1
                continue

            _, released = release_order_funds_to_seller_once(
                order,
                sale_description=f'Order completed: {order.listing_title} (x{order.quantity})',
                commission_description=f'Commission ({order.commission_rate}%): {order.listing_title}',
                ledger_description=f'Commission collected: {order.listing_title} (x{order.quantity})',
            )
            if not released:
                skipped_count += 1
                continue

            create_notification(
                recipient=order.seller,
                notification_type='order_confirmed',
                title='Order completed',
                message=f'Order "{order.listing_title}" has been completed.',
                order=order,
            )
            released_order_ids.append(order.pk)

    return {
        'due_count': len(due_order_ids),
        'released_count': len(released_order_ids),
        'skipped_count': skipped_count,
        'order_ids': released_order_ids,
    }


def auto_confirm_due_orders(*, now=None, batch_size=100, dry_run=False):
    """Complete delivered orders whose 72-hour buyer review window has expired."""
    if batch_size < 1:
        raise ValueError('batch_size must be at least 1.')

    now = now or timezone.now()
    cutoff = now - AUTO_CONFIRM_ORDER_AFTER
    due_filter = Q(delivered_at__lte=cutoff) | (
        Q(delivered_at__isnull=True) & Q(updated_at__lte=cutoff)
    )
    due_order_ids = list(
        Order.objects.filter(status='delivered')
        .filter(due_filter)
        .order_by('delivered_at', 'pk')
        .values_list('pk', flat=True)[:batch_size]
    )

    if dry_run:
        return {
            'due_count': len(due_order_ids),
            'confirmed_count': 0,
            'skipped_count': 0,
            'order_ids': due_order_ids,
        }

    confirmed_order_ids = []
    skipped_count = 0

    for order_id in due_order_ids:
        with transaction.atomic():
            order = (
                Order.objects.select_for_update()
                .select_related('buyer', 'seller')
                .get(pk=order_id)
            )
            if order.status != 'delivered':
                skipped_count += 1
                continue

            delivered_at = order.delivered_at or order.updated_at
            if not delivered_at or delivered_at > cutoff:
                skipped_count += 1
                continue

            complete_order_with_seller_payout(
                order,
                sale_description=f'Order completed: {order.listing_title} (x{order.quantity})',
                commission_description=f'Commission ({order.commission_rate}%): {order.listing_title}',
                ledger_description=f'Commission collected: {order.listing_title} (x{order.quantity})',
            )

            title = 'Order confirmed'
            message = (
                f'Order "{order.listing_title}" was automatically confirmed after '
                f'72 hours without a dispute.'
            )

            create_notification(
                recipient=order.seller,
                notification_type='order_confirmed',
                title=title,
                message=message,
                order=order,
            )
            create_notification(
                recipient=order.buyer,
                notification_type='order_confirmed',
                title='Order automatically confirmed',
                message=(
                    f'Order "{order.listing_title}" was automatically confirmed after '
                    f'72 hours without a dispute.'
                ),
                order=order,
            )
            confirmed_order_ids.append(order.pk)

    return {
        'due_count': len(due_order_ids),
        'confirmed_count': len(confirmed_order_ids),
        'skipped_count': skipped_count,
        'order_ids': confirmed_order_ids,
    }


def record_platform_ledger_once(*, entry_type, amount, description, reference_id):
    """Record a platform ledger entry once per entry type/reference pair."""
    if not amount:
        return None, False

    entry, created = PlatformLedgerEntry.objects.get_or_create(
        entry_type=entry_type,
        reference_id=reference_id,
        defaults={
            'amount': amount,
            'description': description,
        },
    )
    return entry, created


def approve_topup_request(topup):
    _, credited = apply_wallet_delta_once(
        topup.user,
        delta=topup.amount,
        transaction_type='topup_approved',
        amount=topup.amount,
        description=f'Top-up approved: PKR {topup.amount} via {topup.payment_method or "N/A"}',
        reference_id=f'topup_{topup.pk}',
    )
    topup.status = 'approved'
    topup.reviewed_at = timezone.now()
    topup.save(update_fields=['status', 'reviewed_at'])
    if credited:
        send_topup_status_email(topup)


def record_withdrawal_approval_once(withdraw):
    wallet = get_or_create_locked_wallet(withdraw.user)
    transaction, created = WalletTransaction.objects.get_or_create(
        wallet=wallet,
        transaction_type='withdraw_approved',
        reference_id=f'withdraw_{withdraw.pk}',
        defaults={
            'amount': withdraw.amount,
            'balance_after': wallet.balance,
            'description': (
                f'Withdrawal approved: PKR {withdraw.amount} via '
                f'{withdraw.payment_method or "N/A"}'
            ),
        },
    )
    if created and withdraw.status == 'approved':
        send_withdraw_status_email(withdraw)
    return transaction, created


def validate_uploaded_image(image):
    if image.content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        return 'Invalid image type.'

    if image.size > MAX_IMAGE_UPLOAD_SIZE:
        return 'Image too large. Max 5MB.'

    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(image) as img:
                if img.format not in ALLOWED_IMAGE_FORMATS:
                    return 'Invalid image type.'
                width, height = img.size
                if (
                    width > MAX_IMAGE_WIDTH or
                    height > MAX_IMAGE_HEIGHT or
                    width * height > MAX_IMAGE_PIXELS
                ):
                    return 'Image dimensions too large.'
                img.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return 'Invalid image file.'
    finally:
        image.seek(0)

    return None


# ── Image optimization ───────────────────────────────────────────────────────

# Presets for different upload contexts
IMAGE_OPTIMIZE_PRESETS = {
    'avatar': {'max_size': 512, 'quality': 85},
    'game_icon': {'max_size': 256, 'quality': 85},
    'chat': {'max_size': 1920, 'quality': 80},
    'proof': {'max_size': 2000, 'quality': 80},
}


def optimize_uploaded_image(image, preset='chat'):
    """Resize (if needed) and convert an uploaded image to WebP.

    Returns a new ``InMemoryUploadedFile`` ready for storage.
    The original file object is left unchanged (seeked back to 0).

    Parameters
    ----------
    image : UploadedFile
        A Django ``UploadedFile`` that has already passed ``validate_uploaded_image``.
    preset : str
        One of ``IMAGE_OPTIMIZE_PRESETS`` keys: 'avatar', 'game_icon', 'chat', 'proof'.
    """
    from io import BytesIO
    from django.core.files.uploadedfile import InMemoryUploadedFile

    config = IMAGE_OPTIMIZE_PRESETS.get(preset, IMAGE_OPTIMIZE_PRESETS['chat'])
    max_dim = config['max_size']
    quality = config['quality']

    try:
        img = Image.open(image)

        # Handle EXIF orientation (auto-rotate phone photos)
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        # Convert palette/CMYK images to RGB(A)
        if img.mode in ('P', 'CMYK'):
            img = img.convert('RGBA' if 'transparency' in img.info else 'RGB')
        elif img.mode == 'LA':
            img = img.convert('RGBA')
        elif img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')

        # Resize if larger than max dimensions
        width, height = img.size
        if width > max_dim or height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)

        # Flatten alpha for WebP (use white background)
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background

        # Save as WebP to buffer
        buffer = BytesIO()
        img.save(buffer, format='WEBP', quality=quality, method=4)
        buffer.seek(0)

        # Build a new filename
        original_name = getattr(image, 'name', 'image.webp')
        base_name = original_name.rsplit('.', 1)[0] if '.' in original_name else original_name
        new_name = f'{base_name}.webp'

        optimized = InMemoryUploadedFile(
            file=buffer,
            field_name=image.field_name if hasattr(image, 'field_name') else None,
            name=new_name,
            content_type='image/webp',
            size=buffer.getbuffer().nbytes,
            charset=None,
        )
        return optimized

    except Exception:
        # If optimization fails for any reason, fall back to the original
        image.seek(0)
        return image
    finally:
        image.seek(0)



def validate_chat_message_content(content, *, allow_empty=False):
    """Return normalized chat text plus a validation error string, if any."""
    if content is None:
        text = ''
    elif isinstance(content, str):
        text = content.strip()
    else:
        return '', CHAT_MESSAGE_NOT_TEXT_ERROR

    if not text and not allow_empty:
        return text, CHAT_MESSAGE_EMPTY_ERROR

    if len(text) > MAX_CHAT_MESSAGE_LENGTH:
        return text, CHAT_MESSAGE_TOO_LONG_ERROR

    return text, None


def validate_chat_listing_reference(listing_id, *, seller_id=None, conversation_id=None):
    """Resolve a listing reference only when it belongs in this conversation."""
    if listing_id in (None, ''):
        return None, None
    if isinstance(listing_id, bool):
        return None, CHAT_LISTING_REFERENCE_INVALID_ERROR
    try:
        listing_id = int(listing_id)
    except (TypeError, ValueError):
        return None, CHAT_LISTING_REFERENCE_INVALID_ERROR
    if listing_id <= 0:
        return None, CHAT_LISTING_REFERENCE_INVALID_ERROR

    # References can be created only from listings visible to buyers. Messages
    # retain their snapshot after the listing later becomes unavailable.
    listings = Listing.objects.filter(pk=listing_id, status='active')
    if seller_id is not None:
        listings = listings.filter(seller_id=seller_id)
    elif conversation_id is not None:
        listings = listings.filter(seller__conversations__pk=conversation_id)
    else:
        return None, CHAT_LISTING_REFERENCE_INVALID_ERROR

    listing = listings.first()
    if listing is None:
        return None, CHAT_LISTING_REFERENCE_INVALID_ERROR
    return listing, None


def consume_chat_ws_message_quota(user_id, conversation_id):
    bucket = int(time() // CHAT_WS_MESSAGE_WINDOW_SECONDS)
    cache_key = (
        f'core:{CHAT_WS_RATE_LIMIT_CACHE_PREFIX}:'
        f'{int(user_id)}:{int(conversation_id)}:{bucket}'
    )
    timeout = CHAT_WS_MESSAGE_WINDOW_SECONDS + 5
    cache.add(cache_key, 0, timeout=timeout)
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, timeout=timeout)
        count = 1
    return count <= CHAT_WS_MESSAGE_LIMIT


def create_chat_ws_ticket(user, conversation_id):
    """Create a short-lived ticket for opening one chat WebSocket."""
    nonce = secrets.token_urlsafe(24)
    cache.set(
        f'{CHAT_WS_TICKET_CACHE_PREFIX}:{nonce}',
        True,
        timeout=CHAT_WS_TICKET_MAX_AGE_SECONDS,
    )
    return signing.dumps(
        {
            'user_id': user.pk,
            'conversation_id': int(conversation_id),
            'nonce': nonce,
        },
        salt=CHAT_WS_TICKET_SALT,
    )


def decode_chat_ws_ticket(ticket, max_age=CHAT_WS_TICKET_MAX_AGE_SECONDS):
    payload = signing.loads(ticket, salt=CHAT_WS_TICKET_SALT, max_age=max_age)
    return {
        'user_id': int(payload['user_id']),
        'conversation_id': int(payload['conversation_id']),
        'nonce': str(payload.get('nonce', '')),
    }


def consume_chat_ws_ticket(ticket):
    payload = decode_chat_ws_ticket(ticket)
    nonce = payload.get('nonce')
    if not nonce:
        raise signing.BadSignature('Missing ticket nonce.')

    cache_key = f'{CHAT_WS_TICKET_CACHE_PREFIX}:{nonce}'
    if not cache.get(cache_key):
        raise signing.BadSignature('Ticket has already been used.')
    cache.delete(cache_key)
    return payload


def create_private_media_ticket(kind, object_id, *, viewer_user_id=None):
    """Create a short-lived ticket scoped to one viewer for protected media."""
    payload = {
        'kind': kind,
        'object_id': int(object_id),
    }
    if viewer_user_id is not None:
        payload['viewer_user_id'] = int(viewer_user_id)

    return signing.dumps(
        payload,
        salt=PRIVATE_MEDIA_TICKET_SALT,
    )


def decode_private_media_ticket(ticket, max_age=PRIVATE_MEDIA_TICKET_MAX_AGE_SECONDS):
    payload = signing.loads(ticket, salt=PRIVATE_MEDIA_TICKET_SALT, max_age=max_age)
    return {
        'kind': str(payload['kind']),
        'object_id': int(payload['object_id']),
        'viewer_user_id': int(payload['viewer_user_id']),
    }


# ── Email change verification ───────────────────────────────────────────────

EMAIL_CHANGE_CODE_MAX_AGE = 15 * 60  # 15 minutes
EMAIL_CHANGE_CACHE_PREFIX = 'email-change'
USERNAME_CHANGE_COOLDOWN_DAYS = 90


def _generate_six_digit_code():
    return f'{secrets.randbelow(1_000_000):06d}'


def _hash_challenge_code(challenge_id, code):
    return hashlib.sha256(f'{challenge_id}:{code}'.encode('utf-8')).hexdigest()


def _challenge_cache_key(prefix, challenge_id):
    return f'core:{prefix}:{challenge_id}'


def _create_cached_challenge(prefix, code, payload, timeout):
    challenge_id = secrets.token_urlsafe(32)
    cache.set(
        _challenge_cache_key(prefix, challenge_id),
        {
            **payload,
            'code_hash': _hash_challenge_code(challenge_id, code),
            'failed_attempts': 0,
        },
        timeout=timeout,
    )
    return challenge_id


def _get_cached_challenge(prefix, challenge_id):
    if not challenge_id:
        return None
    return cache.get(_challenge_cache_key(prefix, challenge_id))


def _delete_cached_challenge(prefix, challenge_id):
    if challenge_id:
        cache.delete(_challenge_cache_key(prefix, challenge_id))


def _record_failed_challenge_attempt(prefix, challenge_id, payload, timeout):
    failed_attempts = int(payload.get('failed_attempts') or 0) + 1
    if failed_attempts >= CHALLENGE_MAX_FAILED_ATTEMPTS:
        _delete_cached_challenge(prefix, challenge_id)
        return

    cache.set(
        _challenge_cache_key(prefix, challenge_id),
        {
            **payload,
            'failed_attempts': failed_attempts,
        },
        timeout=timeout,
    )


def _verify_cached_challenge(prefix, challenge_id, code, timeout):
    payload = _get_cached_challenge(prefix, challenge_id)
    if not payload:
        return None
    expected = payload.get('code_hash', '')
    actual = _hash_challenge_code(challenge_id, code)
    if not constant_time_compare(expected, actual):
        _record_failed_challenge_attempt(prefix, challenge_id, payload, timeout)
        return None
    return payload


def generate_email_change_code():
    """Generate a 6-digit verification code."""
    return _generate_six_digit_code()


def create_email_change_token(user_id, current_code, new_email, new_code):
    """Create an opaque email-change challenge ID stored server-side."""
    challenge_id = secrets.token_urlsafe(32)
    cache.set(
        _challenge_cache_key(EMAIL_CHANGE_CACHE_PREFIX, challenge_id),
        {
            'user_id': user_id,
            'new_email': new_email,
            'current_code_hash': _hash_challenge_code(challenge_id, current_code),
            'new_code_hash': _hash_challenge_code(challenge_id, new_code),
            'failed_attempts': 0,
        },
        EMAIL_CHANGE_CODE_MAX_AGE,
    )
    return challenge_id


def verify_email_change_token(token, current_code, new_code):
    payload = _get_cached_challenge(EMAIL_CHANGE_CACHE_PREFIX, token)
    if not payload:
        return None

    current_expected = payload.get('current_code_hash', '')
    current_actual = _hash_challenge_code(token, current_code)
    new_expected = payload.get('new_code_hash', '')
    new_actual = _hash_challenge_code(token, new_code)
    if not (
        constant_time_compare(current_expected, current_actual)
        and constant_time_compare(new_expected, new_actual)
    ):
        _record_failed_challenge_attempt(
            EMAIL_CHANGE_CACHE_PREFIX,
            token,
            payload,
            EMAIL_CHANGE_CODE_MAX_AGE,
        )
        return None
    return payload


def consume_email_change_token(token):
    _delete_cached_challenge(EMAIL_CHANGE_CACHE_PREFIX, token)


def send_email_change_code(user, code):
    """Send the verification code to the user's current email."""
    _send_html_email(
        user.email,
        subject='GamesBazaar — Email Change Verification Code',
        template_name='email/verification_code.html',
        context={
            'username': user.username,
            'code': code,
            'message_body': 'Use the code below to verify your email change request.',
        },
        fail_silently=False,
    )


def send_new_email_change_code(user, new_email, code):
    """Send the verification code to the requested new email address."""
    _send_html_email(
        new_email,
        subject='GamesBazaar — Confirm Your New Email',
        template_name='email/verification_code.html',
        context={
            'username': user.username,
            'code': code,
            'message_body': 'Use the code below to confirm this email address for your GamesBazaar account.',
        },
        fail_silently=False,
    )


# ── Password reset ──────────────────────────────────────────────────────────

PASSWORD_RESET_CODE_MAX_AGE = 15 * 60  # 15 minutes
PASSWORD_RESET_CACHE_PREFIX = 'password-reset'


def generate_password_reset_code():
    """Generate a 6-digit reset code."""
    return _generate_six_digit_code()


def create_password_reset_token(user_id=None, code=None):
    """Create an opaque password-reset challenge ID.

    When user_id/code are omitted, no cache entry is created. This lets the
    reset-request endpoint return an indistinguishable token for unknown emails.
    """
    if user_id is None or code is None:
        return secrets.token_urlsafe(32)
    return _create_cached_challenge(
        PASSWORD_RESET_CACHE_PREFIX,
        code,
        {'user_id': user_id},
        PASSWORD_RESET_CODE_MAX_AGE,
    )


def verify_password_reset_token(token, code):
    return _verify_cached_challenge(
        PASSWORD_RESET_CACHE_PREFIX,
        token,
        code,
        PASSWORD_RESET_CODE_MAX_AGE,
    )


def consume_password_reset_token(token):
    _delete_cached_challenge(PASSWORD_RESET_CACHE_PREFIX, token)


def send_password_reset_code(user, code):
    """Send the password reset code to the user's email."""
    _send_html_email(
        user.email,
        subject='GamesBazaar — Password Reset Code',
        template_name='email/verification_code.html',
        context={
            'username': user.username,
            'code': code,
            'message_body': 'Use the code below to reset your password.',
        },
        fail_silently=False,
    )


# ── Email verification (registration) ───────────────────────────────────────

EMAIL_VERIFICATION_CODE_MAX_AGE = 15 * 60  # 15 minutes
EMAIL_VERIFICATION_CACHE_PREFIX = 'email-verify'


def generate_email_verification_code():
    """Generate a 6-digit verification code."""
    return _generate_six_digit_code()


def create_email_verification_token(user_id, code):
    """Create an opaque email-verification challenge ID stored server-side."""
    return _create_cached_challenge(
        EMAIL_VERIFICATION_CACHE_PREFIX,
        code,
        {'user_id': user_id},
        EMAIL_VERIFICATION_CODE_MAX_AGE,
    )


def verify_email_verification_token(token, code):
    return _verify_cached_challenge(
        EMAIL_VERIFICATION_CACHE_PREFIX,
        token,
        code,
        EMAIL_VERIFICATION_CODE_MAX_AGE,
    )


def consume_email_verification_token(token):
    _delete_cached_challenge(EMAIL_VERIFICATION_CACHE_PREFIX, token)


def send_email_verification_code(email, username, code):
    """Send the email verification code to the user's email."""
    _send_html_email(
        email,
        subject='GamesBazaar — Verify Your Email',
        template_name='email/verification_code.html',
        context={
            'username': username,
            'code': code,
            'message_body': 'Use the code below to verify your email address and activate your account.',
        },
        fail_silently=False,
    )
