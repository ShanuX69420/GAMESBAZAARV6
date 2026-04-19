from PIL import Image, UnidentifiedImageError
from django.core import signing
from django.utils import timezone

from .models import Wallet, WalletTransaction


ALLOWED_IMAGE_CONTENT_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
MAX_IMAGE_UPLOAD_SIZE = 5 * 1024 * 1024
MAX_CHAT_MESSAGE_LENGTH = 2000
CHAT_MESSAGE_EMPTY_ERROR = 'Message cannot be empty.'
CHAT_MESSAGE_NOT_TEXT_ERROR = 'Message must be text.'
CHAT_MESSAGE_TOO_LONG_ERROR = f'Message cannot be longer than {MAX_CHAT_MESSAGE_LENGTH} characters.'
CHAT_WS_MESSAGE_LIMIT = 20
CHAT_WS_MESSAGE_WINDOW_SECONDS = 60
CHAT_WS_TICKET_MAX_AGE_SECONDS = 60
CHAT_WS_TICKET_SALT = 'core.chat.websocket'
PRIVATE_MEDIA_TICKET_MAX_AGE_SECONDS = 5 * 60
PRIVATE_MEDIA_TICKET_SALT = 'core.private_media'


def get_or_create_locked_wallet(user):
    """Return the user's wallet locked for the current transaction."""
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return Wallet.objects.select_for_update().get(pk=wallet.pk)


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


def validate_uploaded_image(image):
    if image.content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        return 'Invalid image type.'

    if image.size > MAX_IMAGE_UPLOAD_SIZE:
        return 'Image too large. Max 5MB.'

    try:
        with Image.open(image) as img:
            img.verify()
    except (UnidentifiedImageError, OSError):
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


def create_chat_ws_ticket(user, conversation_id):
    """Create a short-lived ticket for opening one chat WebSocket."""
    return signing.dumps(
        {
            'user_id': user.pk,
            'conversation_id': int(conversation_id),
        },
        salt=CHAT_WS_TICKET_SALT,
    )


def decode_chat_ws_ticket(ticket, max_age=CHAT_WS_TICKET_MAX_AGE_SECONDS):
    payload = signing.loads(ticket, salt=CHAT_WS_TICKET_SALT, max_age=max_age)
    return {
        'user_id': int(payload['user_id']),
        'conversation_id': int(payload['conversation_id']),
    }


def create_private_media_ticket(kind, object_id):
    """Create a short-lived bearer ticket for a protected uploaded file."""
    return signing.dumps(
        {
            'kind': kind,
            'object_id': int(object_id),
        },
        salt=PRIVATE_MEDIA_TICKET_SALT,
    )


def decode_private_media_ticket(ticket, max_age=PRIVATE_MEDIA_TICKET_MAX_AGE_SECONDS):
    payload = signing.loads(ticket, salt=PRIVATE_MEDIA_TICKET_SALT, max_age=max_age)
    return {
        'kind': str(payload['kind']),
        'object_id': int(payload['object_id']),
    }
