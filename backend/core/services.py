import base64
import hashlib
import secrets
import warnings
from time import time

from cryptography.fernet import Fernet, InvalidToken
from PIL import Image, UnidentifiedImageError
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.core import signing
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from .models import PlatformLedgerEntry, Wallet, WalletTransaction


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

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


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

    return wallet, True


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
    apply_wallet_delta_once(
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
    from django.core.mail import send_mail
    from django.conf import settings as django_settings

    send_mail(
        subject='GamesBazaar — Email Change Verification Code',
        message=(
            f'Hi {user.username},\n\n'
            f'Your email change verification code is: {code}\n\n'
            f'This code expires in 15 minutes.\n'
            f'If you did not request this, please ignore this email.\n\n'
            f'— GamesBazaar'
        ),
        from_email=django_settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def send_new_email_change_code(user, new_email, code):
    """Send the verification code to the requested new email address."""
    from django.core.mail import send_mail
    from django.conf import settings as django_settings

    send_mail(
        subject='GamesBazaar — Confirm Your New Email',
        message=(
            f'Hi {user.username},\n\n'
            f'Use this code to confirm this email address for your GamesBazaar account: {code}\n\n'
            f'This code expires in 15 minutes.\n'
            f'If you did not request this, please ignore this email.\n\n'
            f'— GamesBazaar'
        ),
        from_email=django_settings.DEFAULT_FROM_EMAIL,
        recipient_list=[new_email],
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
    from django.core.mail import send_mail
    from django.conf import settings as django_settings

    send_mail(
        subject='GamesBazaar — Password Reset Code',
        message=(
            f'Hi {user.username},\n\n'
            f'Your password reset code is: {code}\n\n'
            f'This code expires in 15 minutes.\n'
            f'If you did not request this, please ignore this email.\n\n'
            f'— GamesBazaar'
        ),
        from_email=django_settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
