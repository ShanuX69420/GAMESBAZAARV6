"""FazerCards reseller API v2 client (server-side).

Talks to the supplier API used for automatic fulfillment of Fazer-sourced
listings (Steam keys, gift cards, game top-ups). Endpoint reference:
https://reseller.fazercards.com/en/docs — base https://api.fzr.cards/api/v2.

Rules this module encodes:

- Auth is the X-API-Key header (FAZER_API_KEY in the environment).
- Every order-creation POST accepts an Idempotency-Key header: replaying the
  same request with the same key returns the ORIGINAL order instead of
  charging or fulfilling again. Callers mint one key per purchase intent and
  never rotate it — that is the money-safety invariant of the whole engine.
- Order fulfillment is asynchronous: create returns status 'processing';
  poll get_order() until 'completed' / 'failed' / 'refunded'.
- HTTP 429 carries Retry-After (seconds).

This module only talks to the supplier; task orchestration and delivery live
in core.fulfillment.
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BALANCE_PATH = '/balance'
GAMEKEY_OFFERS_PATH = '/gamekeys/keys'
GIFTCARD_OFFERS_PATH = '/giftcards/cards'
TOPUP_OFFERS_PATH = '/topups/offers'
GIFT_OFFERS_PATH = '/steam-gifts/games/{app_id}'
ORDER_PATH = '/orders/{order_id}'
CREATE_GAMEKEY_ORDER_PATH = '/gamekeys/order'
CREATE_GIFTCARD_ORDER_PATH = '/giftcards/order'
CREATE_TOPUP_ORDER_PATH = '/topups/order'
CREATE_GIFT_ORDER_PATH = '/steam-gifts/order'
VALIDATE_TOPUP_ID_PATH = '/topups/validate-id'

# Terminal supplier order statuses. Anything else ('created', 'processing',
# …) means keep polling.
COMPLETED_STATUSES = {'completed'}
FAILED_STATUSES = {'failed', 'refunded', 'cancelled'}

MAX_RETRY_AFTER_SECONDS = 30


class FazerError(Exception):
    """Base error for Fazer supplier problems."""


class FazerNotConfigured(FazerError):
    """FAZER_API_KEY is missing from settings."""


class FazerUnavailable(FazerError):
    """The supplier could not be reached or answered garbage.

    The outcome of a create-order call is unknown; callers must retry later
    with the SAME idempotency key to learn what happened.
    """


class FazerRateLimited(FazerUnavailable):
    """HTTP 429 — retry after ``retry_after`` seconds."""

    def __init__(self, message, retry_after=10):
        super().__init__(message)
        self.retry_after = retry_after


class FazerRejected(FazerError):
    """The supplier definitively rejected the request (HTTP 4xx).

    Nothing was charged; retrying the same request will not help.
    """


def is_configured():
    return bool(settings.FAZER_API_KEY)


def _request(method, path, *, params=None, json_body=None, idempotency_key=None,
             timeout=None):
    if not is_configured():
        raise FazerNotConfigured('FAZER_API_KEY is not configured.')

    url = settings.FAZER_API_BASE_URL + path
    headers = {
        'X-API-Key': settings.FAZER_API_KEY,
        'Accept': 'application/json',
    }
    if idempotency_key:
        headers['Idempotency-Key'] = idempotency_key

    try:
        response = requests.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=headers,
            timeout=timeout or settings.FAZER_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning('Fazer request %s %s failed: %s', method, path, exc)
        raise FazerUnavailable(str(exc)) from exc

    if response.status_code == 429:
        try:
            retry_after = int(response.headers.get('Retry-After') or 10)
        except (TypeError, ValueError):
            retry_after = 10
        raise FazerRateLimited(
            f'Fazer rate limit on {path}.',
            retry_after=min(retry_after, MAX_RETRY_AFTER_SECONDS),
        )

    try:
        data = response.json()
    except ValueError as exc:
        logger.warning('Fazer returned non-JSON from %s (HTTP %s)',
                       path, response.status_code)
        raise FazerUnavailable(
            f'Supplier returned a non-JSON response (HTTP {response.status_code}).'
        ) from exc

    if not isinstance(data, dict):
        raise FazerUnavailable('Supplier returned an unexpected response shape.')

    if response.status_code >= 500:
        raise FazerUnavailable(
            f'Supplier error HTTP {response.status_code}: '
            f'{str(data.get("error", ""))[:200]}'
        )
    if response.status_code >= 400 or data.get('ok') is False:
        # 4xx / ok:false = validation or business-rule failure; nothing was
        # charged and a retry of the same request cannot succeed.
        raise FazerRejected(
            f'HTTP {response.status_code}: {str(data.get("error", "rejected"))[:200]}'
        )
    return data


# ── Reads ────────────────────────────────────────────────────────────────────

def get_balance():
    """Return the reseller USD balance as a string, e.g. '3.3532'."""
    return _request('GET', BALANCE_PATH).get('balance', '0')


def list_gamekey_offers(game_id):
    """Offers for one gamekeys category: [{key_id, name, price_usd, stock, …}]."""
    data = _request('GET', GAMEKEY_OFFERS_PATH, params={'game_id': game_id})
    return data.get('keys') or []


def list_giftcard_offers(category_id):
    """Offers for one gift-card category: [{card_id, name, price_usd, stock, …}]."""
    data = _request('GET', GIFTCARD_OFFERS_PATH, params={'category_id': category_id})
    return data.get('offers') or []


def list_topup_offers(category_id):
    """Full /topups/offers response — offers plus the checkout ``fields`` spec."""
    return _request('GET', TOPUP_OFFERS_PATH, params={'category_id': category_id})


def list_gift_offers(app_id):
    """Giftable editions for one Steam app:
    [{sub_id, name, regions: [{region, price}]}] — prices are USD strings."""
    data = _request('GET', GIFT_OFFERS_PATH.format(app_id=app_id))
    return data.get('offers') or []


def get_order(order_id):
    """Fetch one supplier order: {id, kind, status, failReason, …}."""
    data = _request('GET', ORDER_PATH.format(order_id=order_id))
    order = data.get('order')
    if not isinstance(order, dict):
        raise FazerUnavailable('Supplier order response had no order object.')
    return order


# ── Writes ───────────────────────────────────────────────────────────────────

def validate_topup_id(category_id, fields):
    """Ask Fazer whether a player/user ID exists. Returns the raw response
    ({ok, valid, player_name?, …})."""
    return _request('POST', VALIDATE_TOPUP_ID_PATH,
                    json_body={'category_id': category_id, 'fields': fields})


def _extract_order(data):
    order = data.get('order')
    if not isinstance(order, dict) or not order.get('id'):
        raise FazerUnavailable('Supplier create-order response had no order id.')
    return order


def create_gamekey_order(*, game_id, key_id, quantity, idempotency_key):
    return _extract_order(_request(
        'POST', CREATE_GAMEKEY_ORDER_PATH,
        json_body={'game_id': game_id, 'key_id': key_id, 'quantity': quantity},
        idempotency_key=idempotency_key,
    ))


def create_giftcard_order(*, category_id, card_id, quantity, idempotency_key):
    return _extract_order(_request(
        'POST', CREATE_GIFTCARD_ORDER_PATH,
        json_body={'category_id': category_id, 'card_id': card_id,
                   'quantity': quantity},
        idempotency_key=idempotency_key,
    ))


def create_topup_order(*, category_id, offer_id, fields, idempotency_key):
    return _extract_order(_request(
        'POST', CREATE_TOPUP_ORDER_PATH,
        json_body={'category_id': category_id, 'offer_id': offer_id,
                   'fields': fields},
        idempotency_key=idempotency_key,
    ))


def create_gift_order(*, app_id, sub_id, region, invite_url, idempotency_key):
    """Buy one Steam gift: Fazer's bot friends the buyer via their invite
    link and sends the game to that account. One gift per order — an account
    cannot own the same game twice."""
    def as_int(value):
        return int(value) if str(value).isdigit() else value
    return _extract_order(_request(
        'POST', CREATE_GIFT_ORDER_PATH,
        json_body={'app_id': as_int(app_id), 'sub_id': as_int(sub_id),
                   'region': region, 'invite_url': invite_url},
        idempotency_key=idempotency_key,
    ))
