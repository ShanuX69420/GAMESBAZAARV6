"""Meta (Facebook) Conversions API — server-side pixel events.

Sends Purchase and CompleteRegistration to the Meta dataset from the
backend, so conversions survive ad blockers, iOS tracking protection, and
— the reason this exists — JazzCash purchases that resolve via IPN or the
reconcile timer after the buyer already closed the tab. The browser pixel
never sees those; the server sees 100% of orders.

Deduplication: the browser pixel fires Purchase with the same event ID
(``purchase-<order id>``, see frontend/lib/analytics.js), so Meta keeps
exactly one of the browser/server pair. CompleteRegistration is sent
server-side ONLY — the browser fbq call was removed to avoid needing a
shared ID at signup time.

Events are registered with ``transaction.on_commit`` and delivered from a
short-lived daemon thread: a slow or down Graph API can never block or
fail a purchase. Delivery failures are logged at ERROR (→ Sentry) and the
event is dropped — losing an analytics event is acceptable, delaying an
order is not.

Disabled (every function is a no-op) until META_PIXEL_ID and
META_CAPI_ACCESS_TOKEN are both set in the environment.
"""

import hashlib
import logging
import threading
import time

import requests
from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

GRAPH_API_BASE = 'https://graph.facebook.com/v23.0'
CURRENCY = 'PKR'


def is_configured():
    return bool(settings.META_PIXEL_ID and settings.META_CAPI_ACCESS_TOKEN)


def _sha256(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def normalize_phone(raw):
    """Digits only, with the country code and no leading zero (Meta's ``ph``
    format): '0300 1234567' → '923001234567'. Returns '' if unusable."""
    digits = ''.join(ch for ch in str(raw or '') if ch.isdigit())
    if digits.startswith('00'):
        digits = digits[2:]
    elif digits.startswith('0'):
        digits = '92' + digits[1:]
    return digits if len(digits) >= 11 else ''


def tracking_from_request(request):
    """Snapshot browser attribution data from an API request.

    JSON-serializable on purpose — the JazzCash direct-buy flow stores it on
    the payment row at initiation and replays it hours later when IPN or the
    reconcile timer resolves the payment. ``_fbp``/``_fbc`` are the pixel's
    first-party cookies on .gamesbazaar.pk; API calls carry them because the
    frontend fetches with credentials included.
    """
    meta = request.META
    ip = (
        meta.get('HTTP_X_REAL_IP', '').strip()  # set by our nginx
        or meta.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
        or meta.get('REMOTE_ADDR', '').strip()
    )
    return {
        'client_ip_address': ip,
        'client_user_agent': meta.get('HTTP_USER_AGENT', '')[:512],
        'fbp': request.COOKIES.get('_fbp', '')[:200],
        'fbc': request.COOKIES.get('_fbc', '')[:500],
    }


def _user_data(*, user=None, tracking=None):
    """Build the hashed ``user_data`` match block.

    ``tracking`` is a dict from ``tracking_from_request`` (possibly loaded
    back from JSON), optionally with a raw ``phone`` entry added by the
    caller (JazzCash buys know the buyer's wallet MSISDN).
    """
    data = {}
    tracking = tracking or {}

    email = (user.email if user is not None else '').strip().lower()
    if email:
        data['em'] = [_sha256(email)]
    if user is not None:
        data['external_id'] = [_sha256(str(user.pk))]

    phone = normalize_phone(tracking.get('phone'))
    if phone:
        data['ph'] = [_sha256(phone)]

    for key in ('client_ip_address', 'client_user_agent', 'fbp', 'fbc'):
        value = str(tracking.get(key) or '').strip()
        if value:
            data[key] = value
    return data


def queue_purchase_event(order, *, buyer, tracking=None):
    """Register a server-side Purchase for delivery after the current
    transaction commits. Mirrors the browser event's value/contents and
    shares its event ID, so Meta deduplicates the pair."""
    event = {
        'event_name': 'Purchase',
        'event_time': int(time.time()),
        'event_id': f'purchase-{order.pk}',
        'action_source': 'website',
        'event_source_url': (
            f'{settings.PUBLIC_SITE_URL}/listing/{order.listing_id}'
            if order.listing_id else settings.PUBLIC_SITE_URL
        ),
        'user_data': _user_data(user=buyer, tracking=tracking),
        'custom_data': {
            'currency': CURRENCY,
            'value': float(order.total_amount),
            'content_ids': [str(order.listing_id)] if order.listing_id else [],
            'content_type': 'product',
            'content_name': order.listing_title[:200],
            'num_items': order.quantity,
        },
    }
    _queue(event)


def queue_registration_event(user, *, method, tracking=None):
    """Register a server-side CompleteRegistration (email or google signup).
    Server-side only — no browser counterpart, so no dedup needed."""
    event = {
        'event_name': 'CompleteRegistration',
        'event_time': int(time.time()),
        'event_id': f'signup-{user.pk}',
        'action_source': 'website',
        'event_source_url': f'{settings.PUBLIC_SITE_URL}/register',
        'user_data': _user_data(user=user, tracking=tracking),
        'custom_data': {'content_name': method},
    }
    _queue(event)


def _queue(event):
    if not is_configured():
        return
    payload = {
        'data': [event],
        'access_token': settings.META_CAPI_ACCESS_TOKEN,
    }
    if settings.META_CAPI_TEST_EVENT_CODE:
        payload['test_event_code'] = settings.META_CAPI_TEST_EVENT_CODE
    transaction.on_commit(lambda: _dispatch(payload))


def _dispatch(payload):
    """Deliver from a daemon thread so the request/timer never waits on Meta.
    Module-level seam — tests patch this to capture payloads synchronously."""
    threading.Thread(target=deliver, args=(payload,), daemon=True).start()


def deliver(payload):
    """Synchronous Graph API POST. Never raises; never logs the payload
    (it contains the access token and hashed PII) — event IDs only."""
    event_ids = ', '.join(e.get('event_id', '?') for e in payload.get('data', []))
    url = f'{GRAPH_API_BASE}/{settings.META_PIXEL_ID}/events'
    try:
        response = requests.post(url, json=payload, timeout=(5, 15))
    except requests.RequestException as exc:
        logger.error('Meta CAPI delivery failed for [%s]: %s', event_ids, exc)
        return False
    if response.status_code != 200:
        logger.error(
            'Meta CAPI rejected [%s] (HTTP %s): %s',
            event_ids, response.status_code, response.text[:500],
        )
        return False
    logger.info('Meta CAPI delivered [%s]', event_ids)
    return True
