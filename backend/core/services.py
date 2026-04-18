from PIL import Image, UnidentifiedImageError
from django.utils import timezone

from .models import Wallet, WalletTransaction


ALLOWED_IMAGE_CONTENT_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
MAX_IMAGE_UPLOAD_SIZE = 5 * 1024 * 1024


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
