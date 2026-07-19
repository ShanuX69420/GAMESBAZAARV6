"""JazzCash MWallet REST API v1.1 gateway client.

Implements the merchant-side calls from JazzCash's 2026 integration guides:

- MWallet payment initiation (v1.1, without CNIC)
- Status Inquiry (v1.1) — mandatory integration
- MWallet Refund (v1.1) — optional integration

Gateway rules this module encodes:

- Amounts are sent in paisa: multiply by 100 on request, divide on response.
- Every payload is signed with pp_SecureHash: all non-empty values sorted by
  parameter name, joined with '&', the integrity salt prepended, then
  HMAC-SHA256 with the salt as the secret key (uppercase hex digest).
- All date/time values are Pakistan Standard Time in YYYYMMDDHHMMSS format,
  and pp_TxnExpiryDateTime is one day after pp_TxnDateTime.
- pp_TxnRefNo is unique per transaction (20 alphanumeric chars max).
- Empty parameters must be sent as "" and must not be removed from payloads.
- pp_SubMerchantName is mandatory on initiation and must be letters only (no
  spaces or symbols). It is a signed parameter: leaving it out of the hash
  fails the transaction with "Hash Mismatch".

This module talks only to the gateway; persistence and wallet orchestration
live in core.payments.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PAKISTAN_TZ = ZoneInfo('Asia/Karachi')

MWALLET_PATH = '/api/payment/DoTransaction'
STATUS_INQUIRY_PATH = '/ApplicationAPI/API/PaymentInquiry/Inquire'
REFUND_PATH = '/api/Purchase/domwalletrefundtransaction'

GATEWAY_DATETIME_FORMAT = '%Y%m%d%H%M%S'

# '000' = successful operation on initiation; '121' = completed transaction
# (IPN and Status Inquiry). Anything else is pending or failed.
COMPLETED_RESPONSE_CODES = {'000', '121'}
# Codes JazzCash uses while a transaction awaits customer confirmation.
PENDING_RESPONSE_CODES = {'124', '157'}
COMPLETED_STATUS_VALUES = {'completed'}
PENDING_STATUS_VALUES = {'pending', 'initiated', 'in progress', 'inprogress', 'processing'}


class JazzCashError(Exception):
    """Base error for JazzCash gateway problems."""


class JazzCashNotConfigured(JazzCashError):
    """JazzCash credentials are missing from settings."""


class JazzCashUnavailable(JazzCashError):
    """The gateway could not be reached or answered garbage.

    The transaction outcome is unknown; callers must keep the payment
    pending and rely on IPN / Status Inquiry to learn the final state.
    """


def is_configured():
    return bool(
        settings.JAZZCASH_MERCHANT_ID
        and settings.JAZZCASH_PASSWORD
        and settings.JAZZCASH_INTEGRITY_SALT
        and settings.JAZZCASH_RETURN_URL
    )


def generate_secure_hash(payload, *, integrity_salt=None):
    """Calculate pp_SecureHash for a request or response payload."""
    salt = integrity_salt if integrity_salt is not None else settings.JAZZCASH_INTEGRITY_SALT
    if not salt:
        raise JazzCashNotConfigured('JAZZCASH_INTEGRITY_SALT is not set.')

    values = []
    for key in sorted(payload):
        if key == 'pp_SecureHash':
            continue
        value = payload[key]
        if value is None:
            continue
        value = str(value)
        if value == '':
            continue
        values.append(value)

    message = salt + '&' + '&'.join(values)
    digest = hmac.new(salt.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
    return digest.hexdigest().upper()


def verify_secure_hash(payload, *, integrity_salt=None):
    """Check the pp_SecureHash of an inbound payload (IPN or API response)."""
    if not isinstance(payload, dict):
        return False
    received = str(payload.get('pp_SecureHash') or '').strip()
    if not received:
        return False
    expected = generate_secure_hash(payload, integrity_salt=integrity_salt)
    return hmac.compare_digest(expected, received.upper())


def amount_to_paisa(amount):
    """PKR Decimal -> gateway integer string (last two digits are decimals)."""
    return str(int((Decimal(amount) * 100).quantize(Decimal('1'))))


def paisa_to_amount(value):
    """Gateway integer string -> PKR Decimal."""
    return (Decimal(str(value)) / Decimal('100')).quantize(Decimal('0.01'))


def pakistan_now():
    return datetime.now(PAKISTAN_TZ)


def format_gateway_datetime(value):
    return value.strftime(GATEWAY_DATETIME_FORMAT)


def generate_txn_ref_no(now=None):
    """Build a unique pp_TxnRefNo: <3-letter prefix><YmdHis><3 random digits>.

    20 characters total, which is the gateway's 20AN limit.
    """
    prefix = (settings.JAZZCASH_TXN_REF_PREFIX or 'Gam')[:3]
    now = now or pakistan_now()
    return f'{prefix}{format_gateway_datetime(now)}{secrets.randbelow(1000):03d}'


def _post(path, payload, timeout=None):
    if not is_configured():
        raise JazzCashNotConfigured('JazzCash gateway credentials are not configured.')

    url = settings.JAZZCASH_BASE_URL + path
    try:
        response = requests.post(
            url,
            json=payload,
            headers={'Accept': 'application/json'},
            timeout=timeout or settings.JAZZCASH_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning('JazzCash request to %s failed: %s', path, exc)
        raise JazzCashUnavailable(str(exc)) from exc

    try:
        data = response.json()
    except ValueError as exc:
        logger.warning(
            'JazzCash returned non-JSON response from %s (HTTP %s)',
            path, response.status_code,
        )
        raise JazzCashUnavailable(
            f'Gateway returned a non-JSON response (HTTP {response.status_code}).'
        ) from exc

    if not isinstance(data, dict):
        raise JazzCashUnavailable('Gateway returned an unexpected response shape.')
    return data


def initiate_mwallet_payment(*, amount, mobile_number, txn_ref_no, bill_reference,
                             description, txn_datetime=None):
    """Send the MWallet v1.1 payment request and return the gateway response."""
    txn_datetime = txn_datetime or pakistan_now()
    payload = {
        'pp_Amount': amount_to_paisa(amount),
        'pp_BankID': '',
        'pp_BillReference': bill_reference,
        'pp_Description': description,
        'pp_Language': 'EN',
        'pp_MerchantID': settings.JAZZCASH_MERCHANT_ID,
        'pp_Password': settings.JAZZCASH_PASSWORD,
        'pp_ProductID': '',
        'pp_ReturnURL': settings.JAZZCASH_RETURN_URL,
        'pp_SubMerchantID': '',
        'pp_SubMerchantName': settings.JAZZCASH_SUB_MERCHANT_NAME,
        'pp_TxnCurrency': 'PKR',
        'pp_TxnDateTime': format_gateway_datetime(txn_datetime),
        'pp_TxnExpiryDateTime': format_gateway_datetime(txn_datetime + timedelta(days=1)),
        'pp_TxnRefNo': txn_ref_no,
        'pp_TxnType': 'MWALLET',
        'pp_Version': '1.1',
        'ppmpf_1': mobile_number,
        'ppmpf_2': '',
        'ppmpf_3': '',
        'ppmpf_4': '',
        'ppmpf_5': '',
    }
    payload['pp_SecureHash'] = generate_secure_hash(payload)
    return _post(MWALLET_PATH, payload)


def inquire_transaction_status(txn_ref_no, timeout=None):
    """Call the mandatory Status Inquiry API (v1.1) for a transaction."""
    payload = {
        'pp_TxnRefNo': txn_ref_no,
        'pp_MerchantID': settings.JAZZCASH_MERCHANT_ID,
        'pp_Password': settings.JAZZCASH_PASSWORD,
    }
    payload['pp_SecureHash'] = generate_secure_hash(payload)
    return _post(
        STATUS_INQUIRY_PATH,
        payload,
        timeout=timeout or settings.JAZZCASH_INQUIRY_TIMEOUT_SECONDS,
    )


def refund_mwallet_payment(*, txn_ref_no, amount):
    """Call the optional MWallet Refund API for a completed transaction.

    Requires JAZZCASH_MERCHANT_MPIN. This only moves money on the gateway
    side — callers are responsible for adjusting the user's wallet balance.
    """
    if not settings.JAZZCASH_MERCHANT_MPIN:
        raise JazzCashNotConfigured('JAZZCASH_MERCHANT_MPIN is required for refunds.')

    payload = {
        'pp_MerchantID': settings.JAZZCASH_MERCHANT_ID,
        'pp_Password': settings.JAZZCASH_PASSWORD,
        'pp_TxnRefNo': txn_ref_no,
        'pp_Amount': amount_to_paisa(amount),
        'pp_TxnCurrency': 'PKR',
        'pp_MerchantMPIN': settings.JAZZCASH_MERCHANT_MPIN,
    }
    payload['pp_SecureHash'] = generate_secure_hash(payload)
    return _post(REFUND_PATH, payload)
