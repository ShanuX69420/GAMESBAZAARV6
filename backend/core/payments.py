"""Orchestration for JazzCash MWallet gateway payments.

Lifecycle of a JazzCashPayment:

1. ``start_jazzcash_payment`` creates the row and sends the MWallet request.
2. The immediate gateway response, the IPN webhook, and the Status Inquiry
   API all funnel through ``apply_gateway_result``, which classifies the
   response code and either finalizes, fails, or keeps the payment pending.
3. ``finalize_jazzcash_payment`` credits the wallet exactly once (idempotent
   via the ``jazzcash_<pk>`` wallet-transaction reference) and, for direct
   purchases, executes the listing purchase. If the listing sold out while
   the customer was paying, the money stays in their wallet.

Pending payments are reconciled by the ``reconcile_jazzcash_payments``
management command (Status Inquiry is a mandatory integration) and
opportunistically when the user polls the payment status endpoint.
"""

import json
import logging
from datetime import timedelta
from decimal import InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import jazzcash
from .models import JazzCashPayment, Listing
from .services import (
    apply_wallet_delta_once,
    create_notification,
    decrypt_sensitive_text,
)

logger = logging.getLogger(__name__)

# The 2026 Status Inquiry guide requires at least 10 minutes between initiation
# and the first inquiry. Inquiring earlier risks a verdict on an in-flight
# transaction, which apply_gateway_result would treat as final.
STATUS_INQUIRY_MIN_AGE = timedelta(minutes=10)
# Don't hammer the inquiry API when the user is polling our status endpoint.
STATUS_INQUIRY_REPOLL_SECONDS = 60
# pp_TxnExpiryDateTime is one day after initiation; add an hour of grace
# before declaring an unconfirmed payment expired.
PAYMENT_EXPIRY_AGE = timedelta(hours=25)

TXN_REF_ALLOCATION_ATTEMPTS = 5


def start_jazzcash_payment(*, user, purpose, amount, mobile_number, description,
                           listing=None, listing_quantity=1, checkout_payload=''):
    """Create a payment row and send the MWallet initiation request.

    Returns the payment in its post-initiation state. Network failures leave
    the payment pending so IPN / Status Inquiry can settle it later — the
    same pp_TxnRefNo is never re-sent. ``checkout_payload`` (already
    encrypted) carries buyer checkout info for auto-fulfilled purchases.
    """
    payment = None
    for _ in range(TXN_REF_ALLOCATION_ATTEMPTS):
        try:
            payment = JazzCashPayment.objects.create(
                user=user,
                purpose=purpose,
                amount=amount,
                mobile_number=mobile_number,
                txn_ref_no=jazzcash.generate_txn_ref_no(),
                listing=listing,
                listing_quantity=listing_quantity,
                checkout_payload=checkout_payload,
            )
            break
        except IntegrityError:
            continue
    if payment is None:
        raise jazzcash.JazzCashUnavailable('Could not allocate a unique transaction reference.')

    # pp_BillReference allows alphanumeric characters only.
    payment.bill_reference = f'GB{purpose.upper()}{payment.pk}'
    payment.save(update_fields=['bill_reference', 'updated_at'])

    try:
        response = jazzcash.initiate_mwallet_payment(
            amount=payment.amount,
            mobile_number=payment.mobile_number,
            txn_ref_no=payment.txn_ref_no,
            bill_reference=payment.bill_reference,
            description=description,
        )
    except jazzcash.JazzCashUnavailable as exc:
        logger.warning('JazzCash initiation for %s had no usable response: %s',
                       payment.txn_ref_no, exc)
        payment.note = 'Awaiting confirmation from JazzCash.'
        payment.save(update_fields=['note', 'updated_at'])
        return payment

    return apply_gateway_result(
        payment,
        response_code=response.get('pp_ResponseCode'),
        response_message=response.get('pp_ResponseMessage'),
        retrieval_reference_no=(
            response.get('pp_RetreivalReferenceNo')  # gateway spells it this way
            or response.get('pp_RetrievalReferenceNo')
        ),
        hash_verified=jazzcash.verify_secure_hash(response),
        source='initiation',
        gateway_amount=response.get('pp_Amount'),
    )


def apply_gateway_result(payment, *, response_code, response_message='',
                         retrieval_reference_no='', payment_status='',
                         hash_verified=True, source='gateway',
                         gateway_amount=None):
    """Map a gateway verdict onto the payment and return the fresh payment.

    ``hash_verified`` is informational for responses we fetched ourselves over
    TLS (we log mismatches but trust the channel); inbound IPNs must be
    verified by the caller *before* getting here.

    ``gateway_amount`` is the raw pp_Amount (paisa) when the response carries
    one. A successful verdict whose amount does not match the stored payment
    amount is quarantined for manual review instead of finalized — credits
    always use the stored amount, so a partial settlement must never finalize.
    """
    code = str(response_code or '').strip()
    message = str(response_message or '').strip()
    status_value = str(payment_status or '').strip().lower()

    if not hash_verified:
        logger.warning(
            'JazzCash %s response for %s failed secure-hash verification '
            '(code=%s); proceeding on TLS trust',
            source, payment.txn_ref_no, code,
        )

    is_completed = (
        code in jazzcash.COMPLETED_RESPONSE_CODES
        or status_value in jazzcash.COMPLETED_STATUS_VALUES
    )
    is_pending = (
        code in jazzcash.PENDING_RESPONSE_CODES
        or status_value in jazzcash.PENDING_STATUS_VALUES
    )

    if is_completed and gateway_amount not in (None, ''):
        try:
            reported_amount = jazzcash.paisa_to_amount(gateway_amount)
        except (InvalidOperation, ValueError, TypeError):
            reported_amount = None
        if reported_amount != payment.amount:
            logger.error(
                'JazzCash %s reported amount %r for %s but PKR %s was expected; '
                'payment quarantined for manual review',
                source, gateway_amount, payment.txn_ref_no, payment.amount,
            )
            JazzCashPayment.objects.filter(pk=payment.pk).exclude(
                status='completed',
            ).update(
                response_code=code[:10],
                response_message=message[:500],
                note=(
                    f'Amount mismatch from {source}: gateway reported '
                    f'{gateway_amount!r}, expected PKR {payment.amount}. '
                    'Manual review required.'
                )[:500],
                updated_at=timezone.now(),
            )
            payment.refresh_from_db()
            return payment

    if is_completed:
        return finalize_jazzcash_payment(
            payment.pk,
            response_code=code,
            response_message=message,
            retrieval_reference_no=retrieval_reference_no,
        )

    if is_pending:
        JazzCashPayment.objects.filter(pk=payment.pk, status='pending').update(
            response_code=code[:10],
            response_message=message[:500],
            updated_at=timezone.now(),
        )
        payment.refresh_from_db()
        return payment

    return mark_jazzcash_payment_failed(
        payment.pk,
        response_code=code,
        response_message=message,
    )


def finalize_jazzcash_payment(payment_id, *, response_code='', response_message='',
                              retrieval_reference_no=''):
    """Complete a confirmed payment: credit the wallet and run the purchase.

    Idempotent — safe to call from the initiation response, IPN retries, the
    status-inquiry reconciler, and admin actions in any order. Also recovers
    payments that were previously marked failed but turn out to have been
    paid (e.g., a late IPN after a misclassified initiation response).
    """
    with transaction.atomic():
        payment = (
            JazzCashPayment.objects.select_for_update()
            .select_related('user')
            .get(pk=payment_id)
        )
        if payment.status == 'completed':
            return payment

        if payment.purpose == 'purchase' and payment.listing_id:
            # Lock the listing before the wallet so the lock order matches
            # BuyListingView (listing -> wallet); the reverse order can
            # deadlock when the same buyer wallet-buys this listing while
            # the gateway confirmation is being finalized.
            list(Listing.objects.select_for_update().filter(pk=payment.listing_id))

        _, credited = apply_wallet_delta_once(
            payment.user,
            delta=payment.amount,
            transaction_type='jazzcash_topup',
            amount=payment.amount,
            description=f'JazzCash payment received: PKR {payment.amount} (ref {payment.txn_ref_no})',
            reference_id=f'jazzcash_{payment.pk}',
        )

        payment.status = 'completed'
        payment.wallet_credited = True
        payment.completed_at = timezone.now()
        payment.note = ''
        if response_code:
            payment.response_code = str(response_code)[:10]
        if response_message:
            payment.response_message = str(response_message)[:500]
        if retrieval_reference_no:
            payment.retrieval_reference_no = str(retrieval_reference_no)[:50]

        order = None
        purchase_error = ''
        if payment.purpose == 'purchase':
            from .views import execute_listing_purchase

            if payment.listing_id:
                checkout_info = None
                raw_checkout = decrypt_sensitive_text(payment.checkout_payload)
                if raw_checkout:
                    try:
                        parsed = json.loads(raw_checkout)
                        if isinstance(parsed, dict):
                            checkout_info = parsed
                    except ValueError:
                        checkout_info = None
                order, purchase_error = execute_listing_purchase(
                    buyer=payment.user,
                    listing_id=payment.listing_id,
                    quantity=payment.listing_quantity,
                    checkout_info=checkout_info,
                )
            else:
                purchase_error = 'This listing is no longer available.'
            if order is not None:
                payment.order = order
            else:
                payment.note = (
                    f'Purchase could not be completed ({purchase_error}) — '
                    'the amount was added to your wallet instead.'
                )[:500]
        payment.save()

        if credited:
            if payment.purpose == 'topup':
                create_notification(
                    recipient=payment.user,
                    notification_type='topup_approved',
                    title=f'Wallet topped up — PKR {payment.amount}',
                    message=(
                        f'Your JazzCash payment of PKR {payment.amount} was received '
                        'and credited to your wallet.'
                    ),
                )
            elif order is None:
                create_notification(
                    recipient=payment.user,
                    notification_type='topup_approved',
                    title=f'JazzCash payment received — PKR {payment.amount}',
                    message=(
                        'Your JazzCash payment was received, but the purchase could not '
                        f'be completed: {purchase_error} '
                        'The payment has been added to your wallet instead.'
                    ),
                )

    logger.info('JazzCash payment %s completed (order=%s)',
                payment.txn_ref_no, payment.order_id)
    return payment


def mark_jazzcash_payment_failed(payment_id, *, response_code='', response_message='', note=''):
    """Mark a payment failed unless it already completed."""
    with transaction.atomic():
        payment = JazzCashPayment.objects.select_for_update().get(pk=payment_id)
        if payment.status in ('completed', 'failed'):
            return payment
        payment.status = 'failed'
        if response_code:
            payment.response_code = str(response_code)[:10]
        if response_message:
            payment.response_message = str(response_message)[:500]
        if note:
            payment.note = str(note)[:500]
        payment.save(update_fields=[
            'status', 'response_code', 'response_message', 'note', 'updated_at',
        ])
    logger.info('JazzCash payment %s marked failed (code=%s)',
                payment.txn_ref_no, payment.response_code)
    return payment


def run_status_inquiry(payment, timeout=None):
    """Query the Status Inquiry API for a payment and apply the verdict."""
    try:
        response = jazzcash.inquire_transaction_status(payment.txn_ref_no, timeout=timeout)
    except jazzcash.JazzCashError as exc:
        logger.warning('JazzCash status inquiry for %s failed: %s',
                       payment.txn_ref_no, exc)
        return payment

    now = timezone.now()
    JazzCashPayment.objects.filter(pk=payment.pk).update(last_status_inquiry_at=now)
    payment.last_status_inquiry_at = now

    api_code = str(response.get('pp_ResponseCode') or '').strip()
    if api_code != '000':
        # The inquiry operation itself failed (e.g., transaction not found
        # yet) — leave the payment as-is and retry later.
        logger.info('JazzCash status inquiry for %s returned API code %s: %s',
                    payment.txn_ref_no, api_code, response.get('pp_ResponseMessage'))
        return payment

    return apply_gateway_result(
        payment,
        response_code=response.get('pp_PaymentResponseCode'),
        response_message=(
            response.get('pp_PaymentResponseMessage')
            or response.get('pp_ResponseMessage')
        ),
        retrieval_reference_no=(
            response.get('pp_RetrievalReferenceNo')
            or response.get('pp_RetreivalReferenceNo')
        ),
        payment_status=response.get('pp_Status'),
        hash_verified=jazzcash.verify_secure_hash(response),
        source='status inquiry',
        gateway_amount=response.get('pp_Amount'),
    )


def maybe_refresh_payment_status(payment):
    """Run a status inquiry for a pending payment if it is due one.

    Used by the user-facing polling endpoint: inquiries only start 10 minutes
    after initiation (per the JazzCash guide) and repeat at most once per
    minute. IPN normally resolves payments long before this kicks in.
    """
    if payment.status != 'pending' or not jazzcash.is_configured():
        return payment
    now = timezone.now()
    if now - payment.created_at < STATUS_INQUIRY_MIN_AGE:
        return payment
    last = payment.last_status_inquiry_at
    if last is not None and (now - last).total_seconds() < STATUS_INQUIRY_REPOLL_SECONDS:
        return payment
    # Short (connect, read) timeout: this runs inside a user-facing GET, so a
    # hung gateway must not pin a worker for the full 65s reconciler budget.
    return run_status_inquiry(payment, timeout=(5, 15))


def reconcile_pending_jazzcash_payments(*, batch_size=50, min_age=STATUS_INQUIRY_MIN_AGE):
    """Settle pending payments via Status Inquiry; expire dead ones.

    Returns counters for reporting. Intended to run from the
    ``reconcile_jazzcash_payments`` management command on a schedule.
    """
    now = timezone.now()
    pending = list(
        JazzCashPayment.objects.filter(
            status='pending',
            created_at__lte=now - min_age,
        ).order_by('created_at')[:batch_size]
    )

    results = {'checked': 0, 'completed': 0, 'failed': 0, 'expired': 0, 'still_pending': 0}
    for payment in pending:
        results['checked'] += 1
        payment = run_status_inquiry(payment)
        if payment.status == 'pending' and payment.created_at <= now - PAYMENT_EXPIRY_AGE:
            payment = mark_jazzcash_payment_failed(
                payment.pk,
                response_message='Expired',
                note='Transaction expired without confirmation from JazzCash.',
            )
            if payment.status == 'failed':
                results['expired'] += 1
                continue
        if payment.status == 'completed':
            results['completed'] += 1
        elif payment.status == 'failed':
            results['failed'] += 1
        else:
            results['still_pending'] += 1
    return results
