"""Automatic fulfillment engine for Fazer-sourced orders.

When a buyer pays for a listing that has an enabled FazerProductLink and the
'fazer_autofulfill_enabled' platform setting is on, the purchase flow creates
a FazerFulfillmentTask (order stays 'pending') and schedules
process_fulfillment_task after the transaction commits. A daemon thread gives
instant fulfillment; the process_fazer_fulfillments management command
(1-minute systemd timer) re-drives any task the thread didn't finish, so a
restart or crash never strands a paid order.

Money-safety invariants:

- One Idempotency-Key per purchase intent, minted at task creation and NEVER
  rotated. Replaying the create-order call (thread + timer race, restart,
  network blip after POST) returns the original supplier order — it can never
  charge twice.
- No HTTP request is ever made while a database transaction/row lock is held.
- Every failure path converges on 'manual' (nothing charged — fulfill by
  hand, today's flow) or 'attention' (supplier money possibly spent — human
  must look). The buyer's order stays 'pending' either way and the seller is
  alerted in-app + by email.
"""

import json
import logging
import re
import threading
import time
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from . import fazer
from .models import FazerFulfillmentTask, FazerProductLink, Order
from .services import (
    create_notification,
    decrypt_sensitive_text,
    encrypt_sensitive_text,
    get_platform_setting,
    post_order_chat_message,
    send_transactional_email,
)

logger = logging.getLogger(__name__)

AUTOFULFILL_SETTING_KEY = 'fazer_autofulfill_enabled'
MANUAL_DELIVERY_TIME = '10-15 Minutes'

# How long a task may sit in 'placing' before the timer assumes the worker
# died mid-call and replays the create-order request (same idempotency key).
PLACING_STALE_AFTER = timedelta(minutes=2)
# Give the on-commit thread a head start before the timer touches new tasks.
QUEUED_PICKUP_DELAY = timedelta(seconds=30)
# Supplier order still not terminal this long after purchase -> attention.
FULFILLMENT_DEADLINE = timedelta(minutes=15)
# In-thread polling: check every POLL_INTERVAL for up to THREAD_POLL_BUDGET,
# then hand the task to the timer (poll due every TIMER_POLL_INTERVAL).
POLL_INTERVAL_SECONDS = 3
THREAD_POLL_BUDGET_SECONDS = 90
TIMER_POLL_INTERVAL = timedelta(seconds=30)

BUYER_DELAY_NOTE = (
    'Automatic delivery is taking a little longer than usual — the seller '
    'will complete this order for you shortly. Thanks for your patience!'
)


def autofulfill_enabled():
    return fazer.is_configured() and get_platform_setting(AUTOFULFILL_SETTING_KEY) == '1'


def get_active_link(listing):
    """The enabled Fazer link for a listing, fetched OUTSIDE any FOR UPDATE
    join (a nullable reverse OneToOne cannot ride along in select_for_update)."""
    return FazerProductLink.objects.filter(listing_id=listing.pk, enabled=True).first()


def build_task_for_order(order, link):
    """Create the fulfillment task inside the purchase transaction."""
    return FazerFulfillmentTask.objects.create(
        order=order,
        link=link,
        kind=link.kind,
        fazer_category_id=link.fazer_category_id,
        offer_name=link.offer_name,
        quantity=order.quantity,
        idempotency_key=f'gb-{order.pk}',
        deadline_at=timezone.now() + FULFILLMENT_DEADLINE,
    )


def schedule_fulfillment_after_commit(task_id):
    """Fire-and-forget fulfillment once the purchase transaction commits."""
    if getattr(settings, 'IS_TESTING', False):
        return  # tests drive process_fulfillment_task explicitly
    transaction.on_commit(lambda: _spawn_worker(task_id))


def _spawn_worker(task_id):
    thread = threading.Thread(
        target=_worker, args=(task_id,), name=f'fazer-fulfill-{task_id}', daemon=True,
    )
    thread.start()


def _worker(task_id):
    try:
        process_fulfillment_task(task_id)
    except Exception:  # noqa: BLE001 — never let a worker thread die loudly
        logger.exception('Fazer fulfillment worker crashed for task %s', task_id)
    finally:
        connection.close()


# ── Task processing ──────────────────────────────────────────────────────────

def process_fulfillment_task(task_id, *, poll_budget_seconds=THREAD_POLL_BUDGET_SECONDS):
    """Advance one task as far as possible. Entry point for both the
    on-commit thread and the timer; claims are atomic so the two can race
    safely."""
    now = timezone.now()

    claimed_new = FazerFulfillmentTask.objects.filter(
        pk=task_id, status='queued',
    ).update(status='placing', claimed_at=now, attempts=F('attempts') + 1)

    claimed_stale = 0
    if not claimed_new:
        claimed_stale = FazerFulfillmentTask.objects.filter(
            pk=task_id, status='placing', claimed_at__lt=now - PLACING_STALE_AFTER,
        ).update(claimed_at=now, attempts=F('attempts') + 1)

    if claimed_new or claimed_stale:
        task = FazerFulfillmentTask.objects.select_related(
            'order__buyer', 'order__seller', 'link',
        ).get(pk=task_id)
        if not _place_supplier_orders(task):
            return
        _poll_until_done(task, poll_budget_seconds)
        return

    # Not ours to place — maybe a processing task whose poll is due.
    claimed_poll = FazerFulfillmentTask.objects.filter(
        pk=task_id, status='processing', next_poll_at__lte=now,
    ).update(next_poll_at=now + TIMER_POLL_INTERVAL)
    if claimed_poll:
        task = FazerFulfillmentTask.objects.select_related(
            'order__buyer', 'order__seller', 'link',
        ).get(pk=task_id)
        _poll_once(task)


def _norm(value):
    """Offer-name normalization — mirrors the daily price sync's matcher."""
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', str(value).lower()).split())


def _match_offer(offers, offer_name, *, sku_field):
    exact = [o for o in offers if str(o.get('name', '')) == offer_name]
    if exact:
        return exact[0]
    wanted = _norm(offer_name)
    matched = [o for o in offers if _norm(o.get('name', '')) == wanted]
    return matched[0] if matched else None


def _checkout_info(order):
    raw = decrypt_sensitive_text(order.checkout_payload)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _place_supplier_orders(task):
    """Preflight + create the supplier order(s). Returns True when the task
    reached 'processing' (poll next); False when it went manual."""
    order = task.order
    qty = task.quantity

    if order.status != 'pending':
        _fail_to_manual(task, 'order is no longer pending', notify=False)
        return False

    # Resolve the live offer (fresh price + stock + sku id) by name.
    try:
        if task.kind == 'gamekey':
            offers = fazer.list_gamekey_offers(task.fazer_category_id)
            sku_field, has_stock = 'key_id', True
        elif task.kind == 'giftcard':
            offers = fazer.list_giftcard_offers(task.fazer_category_id)
            sku_field, has_stock = 'card_id', True
        else:
            topup_data = fazer.list_topup_offers(task.fazer_category_id)
            offers = topup_data.get('offers') or []
            sku_field, has_stock = 'offer_id', False
    except fazer.FazerRejected as exc:
        _fail_to_manual(task, f'supplier rejected catalog lookup: {exc}')
        return False
    except fazer.FazerError as exc:
        _release_for_retry(task, f'supplier unreachable: {exc}')
        return False

    offer = _match_offer(offers, task.offer_name, sku_field=sku_field)
    if offer is None:
        _fail_to_manual(task, f'offer "{task.offer_name}" not found on Fazer')
        return False
    if has_stock and int(offer.get('stock') or 0) < qty:
        _fail_to_manual(task, f'out of stock on Fazer (stock={offer.get("stock")})')
        return False

    try:
        unit_cost = Decimal(str(offer.get('price_usd', '0')))
    except InvalidOperation:
        unit_cost = Decimal('0')
    if unit_cost <= 0:
        _fail_to_manual(task, 'supplier offer has no valid price')
        return False

    total_cost = unit_cost * qty
    link_cost = task.link.last_cost_usd if task.link else None
    if link_cost:
        ceiling = link_cost * (Decimal('100') + settings.FAZER_PRICE_TOLERANCE_PCT) / Decimal('100')
        if unit_cost > ceiling:
            _fail_to_manual(
                task,
                f'price sanity: live ${unit_cost} exceeds last-synced ${link_cost} '
                f'by more than {settings.FAZER_PRICE_TOLERANCE_PCT}%',
            )
            return False
    if total_cost > settings.FAZER_MAX_ORDER_USD:
        _fail_to_manual(
            task, f'cost ${total_cost} exceeds FAZER_MAX_ORDER_USD ${settings.FAZER_MAX_ORDER_USD}',
        )
        return False

    checkout_fields = {}
    if task.kind == 'topup':
        checkout_fields = _checkout_info(order).get('fields') or {}
        if not any(str(v).strip() for v in checkout_fields.values()):
            _fail_to_manual(task, 'buyer player/user ID missing from checkout data')
            return False

    try:
        balance = Decimal(str(fazer.get_balance()))
    except fazer.FazerError:
        balance = None  # balance check is best-effort; the order call decides
    if balance is not None and balance < total_cost:
        _fail_to_manual(
            task, f'Fazer balance ${balance} is below the ${total_cost} needed',
            low_balance=True,
        )
        return False

    # Place the order(s). From here on money may move: any uncertainty keeps
    # the task in 'placing' so a retry replays the SAME idempotency key.
    try:
        if task.kind == 'topup':
            sub_orders = list(task.sub_orders or [])
            existing = {s.get('i'): s for s in sub_orders if isinstance(s, dict)}
            for i in range(1, qty + 1):
                if existing.get(i, {}).get('fazer_order_id'):
                    continue  # already placed on a previous attempt
                key = task.idempotency_key if qty == 1 else f'{task.idempotency_key}-{i}'
                supplier_order = fazer.create_topup_order(
                    category_id=task.fazer_category_id,
                    offer_id=offer['offer_id'],
                    fields=checkout_fields,
                    idempotency_key=key,
                )
                entry = {'i': i, 'idempotency_key': key,
                         'fazer_order_id': supplier_order['id'],
                         'status': supplier_order.get('status', '')}
                existing[i] = entry
                task.sub_orders = [existing[n] for n in sorted(existing)]
                task.save(update_fields=['sub_orders', 'updated_at'])
            task.fazer_order_id = task.sub_orders[0]['fazer_order_id']
        elif task.kind == 'gamekey':
            supplier_order = fazer.create_gamekey_order(
                game_id=task.fazer_category_id,
                key_id=offer['key_id'],
                quantity=qty,
                idempotency_key=task.idempotency_key,
            )
            task.fazer_order_id = supplier_order['id']
        else:
            supplier_order = fazer.create_giftcard_order(
                category_id=task.fazer_category_id,
                card_id=offer['card_id'],
                quantity=qty,
                idempotency_key=task.idempotency_key,
            )
            task.fazer_order_id = supplier_order['id']
    except fazer.FazerRejected as exc:
        _fail_to_manual(task, f'supplier rejected the order: {exc}')
        return False
    except fazer.FazerError as exc:
        # Outcome unknown — stay in 'placing'; the timer replays with the
        # same idempotency key after PLACING_STALE_AFTER.
        logger.warning('Fazer create-order outcome unknown for task %s: %s',
                       task.pk, exc)
        return False

    task.status = 'processing'
    task.next_poll_at = timezone.now() + TIMER_POLL_INTERVAL
    task.save(update_fields=['status', 'fazer_order_id', 'sub_orders',
                             'next_poll_at', 'updated_at'])
    return True


def _poll_until_done(task, poll_budget_seconds):
    deadline = time.monotonic() + poll_budget_seconds
    while time.monotonic() < deadline:
        if _poll_once(task):
            return
        if task.status != 'processing':
            return
        time.sleep(POLL_INTERVAL_SECONDS)
    # Hand over to the timer.
    FazerFulfillmentTask.objects.filter(pk=task.pk, status='processing').update(
        next_poll_at=timezone.now() + TIMER_POLL_INTERVAL,
    )


def _poll_once(task):
    """Check supplier order state; deliver / fail as appropriate.
    Returns True when the task reached a terminal state."""
    order_ids = [s['fazer_order_id'] for s in (task.sub_orders or [])
                 if isinstance(s, dict) and s.get('fazer_order_id')]
    if not order_ids:
        order_ids = [task.fazer_order_id]

    supplier_orders = []
    for order_id in order_ids:
        try:
            supplier_orders.append(fazer.get_order(order_id))
        except fazer.FazerError as exc:
            logger.warning('Fazer poll failed for task %s (%s): %s',
                           task.pk, order_id, exc)
            return False  # try again next round

    statuses = {str(o.get('status', '')) for o in supplier_orders}
    failed = statuses & fazer.FAILED_STATUSES
    completed = statuses <= fazer.COMPLETED_STATUSES

    if failed:
        # Field casing varies by order kind (steam gifts: failReason,
        # gift cards/keys: fail_reason) — read both.
        reasons = '; '.join(
            str(o.get('failReason') or o.get('fail_reason') or o.get('status'))
            for o in supplier_orders if str(o.get('status')) in fazer.FAILED_STATUSES
        )
        any_completed = any(
            str(o.get('status')) in fazer.COMPLETED_STATUSES for o in supplier_orders
        )
        _store_raw(task, supplier_orders)
        if any_completed:
            _needs_attention(task, f'some supplier orders failed: {reasons[:200]}')
        else:
            _fail_to_manual(task, f'supplier order failed: {reasons[:200]}')
        return True

    if completed:
        _deliver(task, supplier_orders)
        return True

    if task.deadline_at and timezone.now() > task.deadline_at:
        _store_raw(task, supplier_orders)
        _needs_attention(
            task,
            f'supplier order still processing after '
            f'{int(FULFILLMENT_DEADLINE.total_seconds() // 60)} minutes',
        )
        return True

    return False


# ── Delivery ─────────────────────────────────────────────────────────────────

# Keys whose values may carry the delivered secret. The completed-order
# payload is not documented, so parsing is deliberately defensive and
# calibrated with a real probe order (manage.py fazer_probe_order).
CODE_VALUE_KEYS = (
    'keys', 'codes', 'code', 'key', 'cards', 'pins', 'pin', 'vouchers',
    'voucher', 'serials', 'serial', 'card_code', 'key_code', 'redeem_code',
    'gift_code',
)
CODE_CONTAINER_KEYS = ('payload', 'items', 'delivery', 'data', 'result', 'order')


def parse_delivered_codes(supplier_order):
    """Extract delivered code lines from one completed supplier order."""
    lines = []

    def harvest(value):
        if isinstance(value, str):
            text = value.strip()
            if text:
                lines.append(text)
        elif isinstance(value, (int, float)):
            lines.append(str(value))
        elif isinstance(value, list):
            for item in value:
                harvest(item)
        elif isinstance(value, dict):
            picked = False
            for key in CODE_VALUE_KEYS:
                if key in value:
                    harvest(value[key])
                    picked = True
            if not picked:
                # A dict of unknown shape inside a code field — keep it
                # verbatim rather than guessing.
                lines.append(json.dumps(value, ensure_ascii=False))

    def walk(node):
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key in CODE_VALUE_KEYS:
                harvest(value)
            elif key in CODE_CONTAINER_KEYS and isinstance(value, (dict, list)):
                if isinstance(value, list):
                    for item in value:
                        walk(item)
                else:
                    walk(value)

    walk(supplier_order)
    # De-duplicate while keeping order (idempotent replays may repeat codes).
    seen = set()
    unique = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return unique


def _store_raw(task, supplier_orders):
    task.raw_response = encrypt_sensitive_text(
        json.dumps(supplier_orders, ensure_ascii=False)
    )
    task.charged_usd = _total_charged(supplier_orders)
    task.save(update_fields=['raw_response', 'charged_usd', 'updated_at'])


def _total_charged(supplier_orders):
    # Cost field varies by order kind: steam gifts say chargedUsd, gift
    # cards/keys say total_usd (verified against real orders 2026-07-11).
    total = Decimal('0')
    found = False
    for supplier_order in supplier_orders:
        value = (supplier_order.get('chargedUsd')
                 or supplier_order.get('total_usd')
                 or supplier_order.get('charged_usd'))
        try:
            total += Decimal(str(value))
            found = True
        except (InvalidOperation, TypeError):
            continue
    return total if found else None


def _deliver(task, supplier_orders):
    order = task.order
    _store_raw(task, supplier_orders)

    if task.kind == 'topup':
        info = _checkout_info(order).get('fields') or {}
        id_bits = ', '.join(str(v) for v in info.values() if str(v).strip())
        player_name = _checkout_info(order).get('player_name', '')
        name_part = f' ({player_name})' if player_name else ''
        delivery_text = (
            f'✅ Top-up delivered directly to your account'
            f'{f" — ID {id_bits}" if id_bits else ""}{name_part}. '
            'Please check in-game and press «Confirm order» on the order page.'
        )
    else:
        codes = []
        for supplier_order in supplier_orders:
            codes.extend(parse_delivered_codes(supplier_order))
        if len(codes) < task.quantity:
            _needs_attention(
                task,
                f'supplier order completed but only {len(codes)} of '
                f'{task.quantity} codes could be extracted — see raw response',
            )
            return
        delivery_text = '\n'.join(codes)

    encrypted_note = encrypt_sensitive_text(delivery_text)
    now = timezone.now()

    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.status != 'pending':
            _needs_attention(
                task,
                f'order became {locked.status} while fulfilling — '
                'delivered content kept on the task, not the order',
            )
            return
        locked.delivery_note = encrypted_note
        locked.status = 'delivered'
        locked.delivered_at = now
        locked.was_auto_delivery = True
        locked.save(update_fields=['delivery_note', 'status', 'delivered_at',
                                   'was_auto_delivery', 'updated_at'])

        post_order_chat_message(
            locked,
            message_type='delivery',
            sender=locked.seller,
            content=encrypted_note,
        )
        post_order_chat_message(
            locked,
            event='order_delivered',
            sender=locked.seller,
            content=(
                f'Order #{locked.order_number} was delivered automatically. '
                f'{locked.buyer.username}, please check the delivery details and '
                'press the «Confirm order» button on the order page once '
                'everything works.'
            ),
        )
        create_notification(
            recipient=locked.buyer,
            notification_type='order_delivered',
            title='Your order has been automatically delivered!',
            message=(
                f'Your order "{locked.listing_title}" has been delivered '
                'automatically. Check your order for the delivery details.'
            ),
            order=locked,
        )

        FazerFulfillmentTask.objects.filter(pk=task.pk).update(
            status='delivered', delivered_at=now, fail_reason='',
            updated_at=now,
        )
    task.status = 'delivered'
    logger.info('Fazer task %s delivered order #%s', task.pk, order.order_number)


# ── Failure paths ────────────────────────────────────────────────────────────

def _release_for_retry(task, reason):
    """Transient problem before any money moved — back to 'queued' for the
    timer to retry."""
    FazerFulfillmentTask.objects.filter(pk=task.pk, status='placing').update(
        status='queued', fail_reason=str(reason)[:300], updated_at=timezone.now(),
    )
    task.status = 'queued'
    logger.warning('Fazer task %s released for retry: %s', task.pk, reason)


def _fail_to_manual(task, reason, *, notify=True, low_balance=False):
    """Nothing was charged — hand the order to the manual flow."""
    _finish_failed(task, 'manual', reason, notify=notify, low_balance=low_balance)


def _needs_attention(task, reason):
    """Supplier money may have moved — a human must reconcile."""
    _finish_failed(task, 'attention', reason, notify=True)


def _finish_failed(task, status, reason, *, notify=True, low_balance=False):
    FazerFulfillmentTask.objects.filter(pk=task.pk).update(
        status=status, fail_reason=str(reason)[:300], updated_at=timezone.now(),
    )
    task.status = status
    task.fail_reason = str(reason)[:300]
    logger.warning('Fazer task %s -> %s: %s', task.pk, status, reason)
    if notify:
        _alert_owner(task, reason, low_balance=low_balance)
        _post_buyer_delay_note(task)


def _post_buyer_delay_note(task):
    try:
        order = task.order
        if order.status == 'pending':
            post_order_chat_message(order, content=BUYER_DELAY_NOTE, sender=None)
    except Exception:  # noqa: BLE001 — the alert flow must never crash
        logger.exception('Could not post buyer delay note for task %s', task.pk)


def _alert_owner(task, reason, *, low_balance=False):
    """Tell the seller (Shayan) in-app and by email that this order needs
    manual fulfillment."""
    try:
        order = task.order
        balance_text = ''
        try:
            balance_text = f'${fazer.get_balance()}'
        except fazer.FazerError:
            balance_text = 'unavailable'

        title = ('Fazer balance too low — order needs manual delivery'
                 if low_balance else 'Auto-fulfillment needs you')
        create_notification(
            recipient=order.seller,
            notification_type='fulfillment_alert',
            title=title,
            message=(
                f'Order #{order.order_number} ({order.listing_title} x{task.quantity}) '
                f'could not be fulfilled automatically: {reason}. '
                'Please deliver it manually.'
            ),
            order=order,
        )
        send_transactional_email(
            order.seller,
            subject='GamesBazaar — Auto-fulfillment needs you',
            message_body=(
                'An order could not be delivered automatically and is waiting '
                'for manual fulfillment.'
            ),
            detail_rows=[
                ('Order', order.order_number or f'#{order.pk}'),
                ('Listing', order.listing_title),
                ('Quantity', str(task.quantity)),
                ('Reason', str(reason)[:200]),
                ('Task status', task.status),
                ('Fazer balance', balance_text),
            ],
            status_text='Action Needed',
            status_class='warning',
        )
    except Exception:  # noqa: BLE001 — the alert flow must never crash
        logger.exception('Could not alert owner for task %s', task.pk)


# ── Instant listing texts (toggle ON/OFF) ────────────────────────────────────

# Exact-substring pairs (manual ↔ instant). Longest patterns first in each
# direction; en-dash forms are canonical (what the templates generate), the
# hyphen forms are one-way fallbacks that normalize to the same instant text.
INSTANT_TEXT_PAIRS = [
    ('Average delivery: 10–15 minutes after purchase',
     'Average delivery: Instant — automatic delivery'),
    ('Usually delivered within 10–15 minutes',
     'Delivered instantly (automatic delivery)'),
    ('— usually within 10–15 minutes',
     '— instantly (automatic delivery)'),
]
INSTANT_TEXT_FALLBACKS = [
    ('Average delivery: 10-15 minutes after purchase',
     'Average delivery: Instant — automatic delivery'),
    ('Usually delivered within 10-15 minutes',
     'Delivered instantly (automatic delivery)'),
    ('— usually within 10-15 minutes',
     '— instantly (automatic delivery)'),
]

# Top-up chat instructions carry a variable ID label/hint, so they swap via
# regex with capture groups (reversible: label and hint are preserved).
TOPUP_TEXT_REGEX_PAIRS = [
    (
        re.compile(r'after purchase, send your ([^()\n]+?) in the order chat '
                   r'\(([^()\n]*?)\)\. I process the top-up and confirm here'),
        r'enter your \1 at checkout (\2) — the top-up is processed '
        r'automatically and confirmed here',
        re.compile(r'enter your ([^()\n]+?) at checkout \(([^()\n]*?)\) — the '
                   r'top-up is processed automatically and confirmed here'),
        r'after purchase, send your \1 in the order chat (\2). I process the '
        r'top-up and confirm here',
    ),
    (
        re.compile(r'After purchase, send your ([^()\n]+?) in the order chat '
                   r'\(([^()\n]*?)\)\.'),
        r'Enter your \1 at checkout (\2) — no need to send it in chat.',
        re.compile(r'Enter your ([^()\n]+?) at checkout \(([^()\n]*?)\) — no '
                   r'need to send it in chat\.'),
        r'After purchase, send your \1 in the order chat (\2).',
    ),
]


def apply_instant_texts(text, enable):
    """Swap delivery prose in one text blob. Returns the new text."""
    if not text:
        return text
    if enable:
        for pattern_on, repl_on, _p, _r in TOPUP_TEXT_REGEX_PAIRS:
            text = pattern_on.sub(repl_on, text)
        for manual, instant in INSTANT_TEXT_PAIRS + INSTANT_TEXT_FALLBACKS:
            text = text.replace(manual, instant)
    else:
        for _p, _r, pattern_off, repl_off in TOPUP_TEXT_REGEX_PAIRS:
            text = pattern_off.sub(repl_off, text)
        for manual, instant in INSTANT_TEXT_PAIRS:
            text = text.replace(instant, manual)
    return text


def flip_listing_instant(listing, enable):
    """Apply/revert instant delivery_time + prose on one listing (in memory).
    Returns the list of changed field names (empty when nothing changed)."""
    changed = []
    target_time = 'Instant' if enable else MANUAL_DELIVERY_TIME
    if listing.delivery_time != target_time:
        listing.delivery_time = target_time
        changed.append('delivery_time')
    new_description = apply_instant_texts(listing.description, enable)
    if new_description != listing.description:
        listing.description = new_description
        changed.append('description')
    new_instructions = apply_instant_texts(listing.delivery_instructions, enable)
    if new_instructions != listing.delivery_instructions:
        listing.delivery_instructions = new_instructions
        changed.append('delivery_instructions')
    return changed
