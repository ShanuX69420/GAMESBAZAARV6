import json
import os
import tempfile
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import fazer, fulfillment
from .models import (
    Category, FazerFulfillmentTask, FazerProductLink, Game, GameCategory,
    JazzCashPayment, Listing, Message, Notification, Order, Wallet,
)
from .payments import finalize_jazzcash_payment
from .services import (
    decrypt_sensitive_text,
    encrypt_sensitive_text,
    set_platform_setting,
)
from .views import execute_listing_purchase

FAZER_TEST_SETTINGS = dict(
    FAZER_API_KEY='fc_test_key',
    FAZER_API_BASE_URL='https://api.fzr.cards/api/v2',
    FAZER_REQUEST_TIMEOUT_SECONDS=5,
    FAZER_MAX_ORDER_USD=Decimal('30'),
    FAZER_PRICE_TOLERANCE_PCT=10,
    FAZER_LOW_BALANCE_USD=10,
)


class FakeFazer:
    """Stands in for core.fazer._request. Dispatches on (method, path) and
    honors idempotency keys the way the real API documents: replaying a
    create with the same key returns the original order."""

    def __init__(self):
        self.balance = '100.0000'
        self.giftcard_offers = [
            {'card_id': 'card_10', 'name': '10 USD', 'price_usd': '8.5000', 'stock': 5},
        ]
        self.gamekey_offers = [
            {'key_id': 'key_std', 'name': 'Standard Edition',
             'price_usd': '5.0000', 'stock': 3},
        ]
        self.topup_response = {
            'ok': True, 'kind': 'topup', 'category_id': 'yalla_ludo',
            'offers': [{'offer_id': 'off_830', 'name': '830 Diamonds',
                        'price_usd': '1.8670'}],
            'fields': [{'key': 'user_id', 'label': 'User ID', 'type': 'text'}],
        }
        self.validate_response = {'ok': True, 'valid': True, 'player_name': 'Nick'}
        # What GET /orders/:id returns once an order exists. Tests mutate
        # completed_payload/status to steer the poll outcome. Default shape
        # mirrors a REAL completed gift-card order (verified 2026-07-11:
        # snake_case fields, codes in 'cards').
        self.order_status = 'completed'
        self.completed_payload = {'cards': ['CODE-AAA-111']}
        self.fail_reason = None
        self.created = []          # (path, body, idempotency_key)
        self.orders_by_key = {}    # idempotency_key -> order id
        self.fail_post_with = None  # exception raised on create-order POSTs

    def __call__(self, method, path, *, params=None, json_body=None,
                 idempotency_key=None, timeout=None):
        if method == 'GET':
            if path == '/balance':
                return {'ok': True, 'balance': self.balance, 'currency': 'USD'}
            if path == '/giftcards/cards':
                return {'ok': True, 'offers': self.giftcard_offers}
            if path == '/gamekeys/keys':
                return {'ok': True, 'keys': self.gamekey_offers}
            if path == '/topups/offers':
                return self.topup_response
            if path.startswith('/orders/'):
                order_id = path.rsplit('/', 1)[1]
                order = {'id': order_id, 'kind': 'gift_card',
                         'status': self.order_status,
                         'fail_reason': self.fail_reason,
                         'total_usd': '8.5000'}
                if self.order_status == 'completed':
                    order.update(self.completed_payload)
                return {'ok': True, 'order': order}
        if method == 'POST':
            if path == '/topups/validate-id':
                return self.validate_response
            if self.fail_post_with is not None:
                raise self.fail_post_with
            self.created.append((path, json_body, idempotency_key))
            order_id = self.orders_by_key.setdefault(
                idempotency_key, f'ord-{idempotency_key}',
            )
            return {'ok': True,
                    'order': {'id': order_id, 'kind': 'x', 'status': 'processing'}}
        raise AssertionError(f'unexpected request {method} {path}')


@override_settings(**FAZER_TEST_SETTINGS)
class FazerTestBase(TestCase):
    def setUp(self):
        cache.clear()  # platform-setting cache must not leak between tests
        self.client = APIClient()
        self.buyer = User.objects.create_user(username='fzbuyer', password='pw12345678')
        self.seller = User.objects.create_user(username='fzseller', password='pw12345678')
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])
        Wallet.objects.filter(user=self.buyer).update(balance=Decimal('50000.00'))

        game = Game.objects.create(name='FZ Game', slug='fz-game')
        self.category = Category.objects.create(name='FZ Gift Cards', slug='gift-cards')
        self.game_category = GameCategory.objects.create(game=game, category=self.category)

        self.listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='10 USD (India)',
            description='How it works: after purchase I send you the code in '
                        'the order chat — usually within 10–15 minutes.',
            price=Decimal('3000.00'),
            quantity=None,
            status='active',
        )
        self.link = FazerProductLink.objects.create(
            listing=self.listing,
            kind='giftcard',
            fazer_category_id='steam_wallet_in',
            offer_name='10 USD',
            last_cost_usd=Decimal('8.5'),
        )
        set_platform_setting(fulfillment.AUTOFULFILL_SETTING_KEY, '1')

        self.fake = FakeFazer()
        patcher = patch('core.fazer._request', new=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.force_authenticate(user=self.buyer)

    def buy(self, listing=None, quantity=1, checkout_info=None):
        order, error = execute_listing_purchase(
            buyer=self.buyer,
            listing_id=(listing or self.listing).pk,
            quantity=quantity,
            checkout_info=checkout_info,
        )
        self.assertIsNone(error)
        return order

    def make_topup_listing(self):
        topup_gc = GameCategory.objects.create(
            game=Game.objects.create(name='Yalla', slug='yalla-ludo'),
            category=Category.objects.create(name='Top Ups', slug='top-ups'),
        )
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=topup_gc,
            title='830 Diamonds',
            price=Decimal('620.00'),
            quantity=None,
            status='active',
        )
        FazerProductLink.objects.create(
            listing=listing,
            kind='topup',
            fazer_category_id='yalla_ludo',
            offer_name='830 Diamonds',
            last_cost_usd=Decimal('1.867'),
            checkout_fields=[{'key': 'user_id', 'label': 'User ID'}],
        )
        return listing


class PurchaseHookTests(FazerTestBase):
    def test_linked_purchase_queues_task_and_stays_pending(self):
        order = self.buy()
        self.assertEqual(order.status, 'pending')
        task = order.fazer_task
        self.assertEqual(task.status, 'queued')
        self.assertEqual(task.idempotency_key, f'gb-{order.pk}')
        self.assertEqual(task.kind, 'giftcard')
        notice = Message.objects.filter(
            order=order, content__contains='delivered automatically',
        )
        self.assertTrue(notice.exists())

    def test_toggle_off_means_no_task(self):
        set_platform_setting(fulfillment.AUTOFULFILL_SETTING_KEY, '0')
        order = self.buy()
        self.assertFalse(FazerFulfillmentTask.objects.filter(order=order).exists())
        self.assertTrue(Message.objects.filter(
            order=order, content__contains='please deliver',
        ).exists())

    def test_disabled_link_means_no_task(self):
        self.link.enabled = False
        self.link.save(update_fields=['enabled'])
        order = self.buy()
        self.assertFalse(FazerFulfillmentTask.objects.filter(order=order).exists())

    def test_no_api_key_means_no_task(self):
        with override_settings(FAZER_API_KEY=''):
            order = self.buy()
        self.assertFalse(FazerFulfillmentTask.objects.filter(order=order).exists())

    def test_prestocked_auto_delivery_unaffected(self):
        self.listing.is_auto_delivery = True
        self.listing.auto_delivery_data = encrypt_sensitive_text('OLDSTOCK-1')
        self.listing.quantity = 1
        self.listing.save()
        order = self.buy()
        self.assertEqual(order.status, 'delivered')
        self.assertFalse(FazerFulfillmentTask.objects.filter(order=order).exists())

    def test_topup_buy_api_requires_player_id(self):
        listing = self.make_topup_listing()
        response = self.client.post('/api/orders/buy/', {
            'listing_id': listing.pk, 'quantity': 1,
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('User ID is required', response.data['error'])

    def test_topup_buy_api_rejects_invalid_id(self):
        listing = self.make_topup_listing()
        self.fake.validate_response = {'ok': True, 'valid': False}
        response = self.client.post('/api/orders/buy/', {
            'listing_id': listing.pk, 'quantity': 1,
            'checkout_fields': {'user_id': '999'},
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('not found', response.data['error'])

    def test_topup_buy_succeeds_when_validation_unsupported(self):
        # Real behavior 2026-07-11: most categories answer HTTP 400 "ID
        # validation is not available" — that must never block a purchase.
        listing = self.make_topup_listing()

        def rejecting(method, path, **kwargs):
            if path == '/topups/validate-id':
                raise fazer.FazerRejected(
                    'HTTP 400: ID validation is not available for this category_id.'
                )
            return FakeFazer.__call__(self.fake, method, path, **kwargs)

        with patch('core.fazer._request', new=rejecting):
            response = self.client.post('/api/orders/buy/', {
                'listing_id': listing.pk, 'quantity': 1,
                'checkout_fields': {'user_id': '12345678'},
            }, format='json')
        self.assertEqual(response.status_code, 201)
        order = Order.objects.get(pk=response.data['id'])
        payload = json.loads(decrypt_sensitive_text(order.checkout_payload))
        self.assertEqual(payload['fields'], {'user_id': '12345678'})
        self.assertEqual(payload['player_name'], '')

    def test_validate_endpoint_fails_open_when_unsupported(self):
        listing = self.make_topup_listing()

        def rejecting(method, path, **kwargs):
            raise fazer.FazerRejected('HTTP 400: ID validation is not available.')

        with patch('core.fazer._request', new=rejecting):
            response = self.client.post(
                f'/api/listings/{listing.pk}/validate-topup-id/',
                {'user_id': '12345678'}, format='json',
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['valid'])
        self.assertTrue(response.data['unverified'])

    def test_topup_buy_api_stores_checkout_payload_and_chat_note(self):
        listing = self.make_topup_listing()
        response = self.client.post('/api/orders/buy/', {
            'listing_id': listing.pk, 'quantity': 1,
            'checkout_fields': {'user_id': '12345678'},
        }, format='json')
        self.assertEqual(response.status_code, 201)
        order = Order.objects.get(pk=response.data['id'])
        payload = json.loads(decrypt_sensitive_text(order.checkout_payload))
        self.assertEqual(payload['fields'], {'user_id': '12345678'})
        self.assertEqual(payload['player_name'], 'Nick')
        self.assertTrue(Message.objects.filter(
            order=order, content__contains='12345678',
        ).exists())

    def test_validate_topup_id_endpoint(self):
        listing = self.make_topup_listing()
        response = self.client.post(
            f'/api/listings/{listing.pk}/validate-topup-id/',
            {'user_id': '12345678'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['valid'])
        self.assertEqual(response.data['player_name'], 'Nick')
        # Non-topup listings 404 (no checkout info needed).
        response = self.client.post(
            f'/api/listings/{self.listing.pk}/validate-topup-id/',
            {'user_id': 'x'}, format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_listing_detail_exposes_checkout_fields_and_instant_flag(self):
        listing = self.make_topup_listing()
        listing.delivery_time = 'Instant'
        listing.save(update_fields=['delivery_time'])
        response = self.client.get(f'/api/listings/{listing.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['instant_delivery'])
        self.assertEqual(response.data['required_checkout_fields'],
                         [{'key': 'user_id', 'label': 'User ID'}])


class EngineTests(FazerTestBase):
    def process(self, task, budget=5):
        fulfillment.process_fulfillment_task(task.pk, poll_budget_seconds=budget)
        task.refresh_from_db()
        return task

    def test_giftcard_happy_path_delivers_order(self):
        order = self.buy()
        task = self.process(order.fazer_task)
        order.refresh_from_db()

        self.assertEqual(task.status, 'delivered')
        self.assertEqual(order.status, 'delivered')
        self.assertTrue(order.was_auto_delivery)
        self.assertIsNotNone(order.delivered_at)
        self.assertEqual(decrypt_sensitive_text(order.delivery_note), 'CODE-AAA-111')
        self.assertEqual(task.charged_usd, Decimal('8.5000'))
        # Delivery chat message + buyer notification, mirroring auto-delivery.
        self.assertTrue(Message.objects.filter(
            order=order, message_type='delivery',
        ).exists())
        self.assertTrue(Notification.objects.filter(
            recipient=self.buyer, notification_type='order_delivered', order=order,
        ).exists())
        # Idempotency key used on the wire is the task's.
        self.assertEqual(self.fake.created[0][2], f'gb-{order.pk}')

    def test_quantity_two_delivers_two_codes(self):
        self.fake.completed_payload = {'payload': {'codes': ['AAA-1', 'BBB-2']}}
        order = self.buy(quantity=2)
        task = self.process(order.fazer_task)
        order.refresh_from_db()
        self.assertEqual(task.status, 'delivered')
        self.assertEqual(decrypt_sensitive_text(order.delivery_note), 'AAA-1\nBBB-2')
        self.assertEqual(self.fake.created[0][1]['quantity'], 2)

    def test_short_codes_goes_to_attention(self):
        self.fake.completed_payload = {'payload': {'codes': ['ONLY-ONE']}}
        order = self.buy(quantity=2)
        task = self.process(order.fazer_task)
        order.refresh_from_db()
        self.assertEqual(task.status, 'attention')
        self.assertEqual(order.status, 'pending')  # manual flow takes over
        self.assertTrue(Notification.objects.filter(
            recipient=self.seller, notification_type='fulfillment_alert',
        ).exists())

    def test_no_codes_found_goes_to_attention_not_guessing(self):
        self.fake.completed_payload = {}  # completed but nothing recognizable
        order = self.buy()
        task = self.process(order.fazer_task)
        order.refresh_from_db()
        self.assertEqual(task.status, 'attention')
        self.assertEqual(order.status, 'pending')

    def test_supplier_failed_order_falls_back_to_manual(self):
        self.fake.order_status = 'failed'
        self.fake.fail_reason = 'sold out upstream'
        order = self.buy()
        task = self.process(order.fazer_task)
        order.refresh_from_db()
        self.assertEqual(task.status, 'manual')
        self.assertIn('sold out upstream', task.fail_reason)
        self.assertEqual(order.status, 'pending')
        self.assertTrue(Notification.objects.filter(
            recipient=self.seller, notification_type='fulfillment_alert',
        ).exists())
        # Buyer sees a gentle delay note in chat.
        self.assertTrue(Message.objects.filter(
            order=order, content=fulfillment.BUYER_DELAY_NOTE,
        ).exists())

    def test_out_of_stock_on_fazer_goes_manual_before_spending(self):
        self.fake.giftcard_offers[0]['stock'] = 0
        order = self.buy()
        task = self.process(order.fazer_task)
        self.assertEqual(task.status, 'manual')
        self.assertEqual(self.fake.created, [])  # nothing was purchased

    def test_price_sanity_guard(self):
        self.link.last_cost_usd = Decimal('5.0')  # live is 8.50 → +70%
        self.link.save(update_fields=['last_cost_usd'])
        order = self.buy()
        task = self.process(order.fazer_task)
        self.assertEqual(task.status, 'manual')
        self.assertIn('price sanity', task.fail_reason)
        self.assertEqual(self.fake.created, [])

    def test_max_order_usd_cap(self):
        with override_settings(FAZER_MAX_ORDER_USD=Decimal('5')):
            order = self.buy()
            task = self.process(order.fazer_task)
        self.assertEqual(task.status, 'manual')
        self.assertIn('FAZER_MAX_ORDER_USD', task.fail_reason)
        self.assertEqual(self.fake.created, [])

    def test_insufficient_supplier_balance_goes_manual(self):
        self.fake.balance = '1.00'
        order = self.buy()
        task = self.process(order.fazer_task)
        self.assertEqual(task.status, 'manual')
        self.assertIn('balance', task.fail_reason)
        self.assertEqual(self.fake.created, [])

    def test_topup_happy_path_delivers_confirmation(self):
        listing = self.make_topup_listing()
        order = self.buy(listing=listing, checkout_info={
            'fields': {'user_id': '12345678'}, 'player_name': 'Nick',
        })
        task = self.process(order.fazer_task)
        order.refresh_from_db()
        self.assertEqual(task.status, 'delivered')
        self.assertEqual(order.status, 'delivered')
        note = decrypt_sensitive_text(order.delivery_note)
        self.assertIn('Top-up delivered', note)
        self.assertIn('12345678', note)
        path, body, _key = self.fake.created[0]
        self.assertEqual(path, '/topups/order')
        self.assertEqual(body['fields'], {'user_id': '12345678'})
        self.assertEqual(body['offer_id'], 'off_830')

    def test_topup_missing_player_id_goes_manual(self):
        listing = self.make_topup_listing()
        order = self.buy(listing=listing)  # no checkout_info
        task = self.process(order.fazer_task)
        self.assertEqual(task.status, 'manual')
        self.assertIn('ID missing', task.fail_reason)
        self.assertEqual(self.fake.created, [])

    def test_topup_quantity_two_places_two_orders_with_distinct_keys(self):
        listing = self.make_topup_listing()
        order = self.buy(listing=listing, quantity=2, checkout_info={
            'fields': {'user_id': '12345678'},
        })
        task = self.process(order.fazer_task)
        self.assertEqual(task.status, 'delivered')
        keys = [key for _p, _b, key in self.fake.created]
        self.assertEqual(keys, [f'gb-{order.pk}-1', f'gb-{order.pk}-2'])
        self.assertEqual(len(task.sub_orders), 2)

    def test_claim_is_exclusive_and_stale_placing_replays_same_key(self):
        self.fake.fail_post_with = fazer.FazerUnavailable('network blip')
        order = self.buy()
        task = self.process(order.fazer_task)
        # POST outcome unknown → stays 'placing'; a fresh claim is refused.
        self.assertEqual(task.status, 'placing')
        fulfillment.process_fulfillment_task(task.pk)
        task.refresh_from_db()
        self.assertEqual(task.status, 'placing')  # recent claim → untouched
        self.assertEqual(task.attempts, 1)

        # After the stale window the timer reclaims and replays the SAME key.
        self.fake.fail_post_with = None
        FazerFulfillmentTask.objects.filter(pk=task.pk).update(
            claimed_at=timezone.now() - timedelta(minutes=5),
        )
        task = self.process(task)
        order.refresh_from_db()
        self.assertEqual(task.status, 'delivered')
        self.assertEqual(order.status, 'delivered')
        self.assertEqual(self.fake.created[-1][2], f'gb-{order.pk}')

    def test_dispute_before_placement_goes_quietly_manual(self):
        # No money spent yet — the task steps aside without alerting anyone.
        order = self.buy()
        Order.objects.filter(pk=order.pk).update(status='disputed')
        task = self.process(order.fazer_task)
        order.refresh_from_db()
        self.assertEqual(task.status, 'manual')
        self.assertEqual(order.status, 'disputed')
        self.assertEqual(self.fake.created, [])  # nothing purchased

    def test_delivery_blocked_when_order_disputed_mid_flight(self):
        # Supplier order placed, then the buyer disputes before completion:
        # money may be spent, so the codes are held on the task for a human.
        self.fake.order_status = 'processing'
        order = self.buy()
        task = self.process(order.fazer_task, budget=0)
        self.assertEqual(task.status, 'processing')

        Order.objects.filter(pk=order.pk).update(status='disputed')
        self.fake.order_status = 'completed'
        FazerFulfillmentTask.objects.filter(pk=task.pk).update(
            next_poll_at=timezone.now() - timedelta(seconds=1),
        )
        task = self.process(task)
        order.refresh_from_db()
        self.assertEqual(task.status, 'attention')
        self.assertEqual(order.status, 'disputed')  # never clobbered
        self.assertEqual(order.delivery_note, '')
        # Codes were preserved on the task for the human to recover.
        self.assertIn('CODE-AAA-111', decrypt_sensitive_text(task.raw_response))

    def test_still_processing_hands_over_to_timer(self):
        self.fake.order_status = 'processing'
        order = self.buy()
        task = self.process(order.fazer_task, budget=0)
        self.assertEqual(task.status, 'processing')
        self.assertIsNotNone(task.next_poll_at)
        self.assertEqual(order.fazer_task.fazer_order_id, f'ord-gb-{order.pk}')

    def test_jazzcash_finalize_forwards_checkout_info(self):
        listing = self.make_topup_listing()
        payment = JazzCashPayment.objects.create(
            user=self.buyer,
            purpose='purchase',
            amount=Decimal('620.00'),
            mobile_number='03001234567',
            txn_ref_no='Gam20260711120000123',
            listing=listing,
            listing_quantity=1,
            checkout_payload=encrypt_sensitive_text(json.dumps({
                'fields': {'user_id': '12345678'}, 'player_name': 'Nick',
            })),
        )
        finalize_jazzcash_payment(payment.pk)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'completed')
        order = payment.order
        self.assertIsNotNone(order)
        task = order.fazer_task
        self.assertEqual(task.status, 'queued')
        payload = json.loads(decrypt_sensitive_text(order.checkout_payload))
        self.assertEqual(payload['fields'], {'user_id': '12345678'})


class ParseDeliveredCodesTests(TestCase):
    def test_common_shapes(self):
        cases = [
            ({'payload': {'codes': ['A', 'B']}}, ['A', 'B']),
            ({'payload': {'keys': [{'code': 'K-1'}]}}, ['K-1']),
            ({'code': 'SINGLE'}, ['SINGLE']),
            ({'payload': {'items': [{'key': 'X'}, {'key': 'Y'}]}}, ['X', 'Y']),
            ({'payload': {'card_code': 'CC', 'pin': '1234'}}, ['CC', '1234']),
            ({'status': 'completed', 'title': 'Not a code'}, []),
        ]
        for supplier_order, expected in cases:
            self.assertEqual(
                fulfillment.parse_delivered_codes(supplier_order), expected,
                msg=f'for {supplier_order}',
            )

    def test_deduplicates_replayed_codes(self):
        supplier_order = {'code': 'SAME', 'payload': {'codes': ['SAME']}}
        self.assertEqual(fulfillment.parse_delivered_codes(supplier_order), ['SAME'])


# Real template prose (tools/listing_templates.py) — the flip must round-trip
# these exactly.
GC_DESC = ('How it works: after purchase I send you the code in the order '
           'chat — usually within 10–15 minutes. You redeem it yourself, '
           'funds appear instantly.')
GC_INSTR = ('After purchase, message me in the order chat. I will send your '
            '10 USD (India) Steam Wallet code with redemption steps. '
            'Usually delivered within 10–15 minutes.')
TOPUP_DESC = ('✅ Average delivery: 10–15 minutes after purchase\n\n'
              'How it works: after purchase, send your Free Fire Player ID in '
              'the order chat (find it in your in-game profile). I process '
              'the top-up and confirm here — usually within 10–15 minutes.')
TOPUP_INSTR = ('After purchase, send your Free Fire Player ID in the order '
               'chat (find it in your in-game profile). I will top up 830 '
               'Diamonds directly to your account and confirm here — usually '
               'within 10–15 minutes. Please double-check the ID before '
               'sending — top-ups to a wrong ID cannot be reversed.')


class InstantTextFlipTests(TestCase):
    def test_round_trip_restores_original_prose(self):
        for original in (GC_DESC, GC_INSTR, TOPUP_DESC, TOPUP_INSTR):
            flipped = fulfillment.apply_instant_texts(original, True)
            self.assertNotEqual(flipped, original)
            self.assertNotIn('10–15 minutes', flipped)
            restored = fulfillment.apply_instant_texts(flipped, False)
            self.assertEqual(restored, original)

    def test_topup_prose_moves_id_to_checkout(self):
        flipped = fulfillment.apply_instant_texts(TOPUP_DESC, True)
        self.assertIn('enter your Free Fire Player ID at checkout', flipped)
        self.assertIn('(find it in your in-game profile)', flipped)
        flipped_instr = fulfillment.apply_instant_texts(TOPUP_INSTR, True)
        self.assertIn('Enter your Free Fire Player ID at checkout', flipped_instr)
        self.assertIn('no need to send it in chat', flipped_instr)


@override_settings(**FAZER_TEST_SETTINGS)
class AutofulfillCommandTests(FazerTestBase):
    def setUp(self):
        super().setUp()
        self.listing.description = GC_DESC
        self.listing.delivery_instructions = GC_INSTR
        self.listing.save()
        # An unlinked listing that must never be touched by the flip.
        self.unlinked = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Manual card',
            description=GC_DESC,
            price=Decimal('1000.00'),
            status='active',
        )

    def test_on_off_round_trip(self):
        call_command('fazer_autofulfill', 'on', verbosity=0)
        self.listing.refresh_from_db()
        self.unlinked.refresh_from_db()
        self.assertEqual(self.listing.delivery_time, 'Instant')
        self.assertNotIn('10–15 minutes', self.listing.description)
        self.assertIn('instantly', self.listing.description)
        # Unlinked listing untouched.
        self.assertEqual(self.unlinked.delivery_time, '10-15 Minutes')
        self.assertEqual(self.unlinked.description, GC_DESC)
        self.assertTrue(fulfillment.autofulfill_enabled())

        call_command('fazer_autofulfill', 'off', verbosity=0)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.delivery_time, '10-15 Minutes')
        self.assertEqual(self.listing.description, GC_DESC)
        self.assertEqual(self.listing.delivery_instructions, GC_INSTR)
        self.assertFalse(fulfillment.autofulfill_enabled())

    def test_dry_run_changes_nothing(self):
        set_platform_setting(fulfillment.AUTOFULFILL_SETTING_KEY, '0')
        call_command('fazer_autofulfill', 'on', '--dry-run', verbosity=0)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.delivery_time, '10-15 Minutes')
        self.assertFalse(fulfillment.autofulfill_enabled())


@override_settings(**FAZER_TEST_SETTINGS)
class ApplyFazerLinksTests(FazerTestBase):
    def _run(self, rows, *args):
        fd, path = tempfile.mkstemp(suffix='.json')
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump({'links': rows}, fh)
        try:
            call_command('apply_fazer_links', path, *args, verbosity=0)
        finally:
            os.unlink(path)

    def test_creates_link_and_applies_toggle_state_to_new_listing(self):
        new_listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='20 USD (India)',
            description=GC_DESC,
            price=Decimal('6000.00'),
            status='active',
        )
        self._run([
            {'listing_id': self.listing.pk, 'kind': 'giftcard',
             'fazer_category_id': 'steam_wallet_in', 'offer_name': '10 USD',
             'sku_id': 'card_10', 'cost_usd': '8.5'},
            {'listing_id': new_listing.pk, 'kind': 'giftcard',
             'fazer_category_id': 'steam_wallet_in', 'offer_name': '20 USD',
             'sku_id': 'card_20', 'cost_usd': '17.0'},
        ])
        link = FazerProductLink.objects.get(listing=new_listing)
        self.assertEqual(link.offer_name, '20 USD')
        self.assertEqual(link.last_cost_usd, Decimal('17.0'))
        # Toggle is ON in setUp → the new listing flips to Instant + prose.
        new_listing.refresh_from_db()
        self.assertEqual(new_listing.delivery_time, 'Instant')
        self.assertNotIn('10–15 minutes', new_listing.description)

    def test_prune_disables_missing_links_and_reverts_listing(self):
        self.listing.delivery_time = 'Instant'
        self.listing.save(update_fields=['delivery_time'])
        other = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='5 USD (India)',
            price=Decimal('1500.00'),
            status='active',
        )
        self._run([
            {'listing_id': other.pk, 'kind': 'giftcard',
             'fazer_category_id': 'steam_wallet_in', 'offer_name': '5 USD'},
        ], '--prune')
        self.link.refresh_from_db()
        self.listing.refresh_from_db()
        self.assertFalse(self.link.enabled)
        self.assertEqual(self.listing.delivery_time, '10-15 Minutes')

    def test_missing_cost_keeps_previous_baseline(self):
        self._run([
            {'listing_id': self.listing.pk, 'kind': 'giftcard',
             'fazer_category_id': 'steam_wallet_in', 'offer_name': '10 USD'},
        ])
        self.link.refresh_from_db()
        self.assertEqual(self.link.last_cost_usd, Decimal('8.5'))


@override_settings(**FAZER_TEST_SETTINGS)
class ProcessTimerCommandTests(FazerTestBase):
    def test_timer_drives_queued_task_to_delivered(self):
        order = self.buy()
        # Make the task old enough for the timer to pick up.
        FazerFulfillmentTask.objects.filter(order=order).update(
            created_at=timezone.now() - timedelta(minutes=2),
        )
        call_command('process_fazer_fulfillments', verbosity=0)
        order.refresh_from_db()
        self.assertEqual(order.status, 'delivered')
        self.assertEqual(order.fazer_task.status, 'delivered')

    def test_fresh_queued_task_left_for_the_worker_thread(self):
        order = self.buy()
        call_command('process_fazer_fulfillments', verbosity=0)
        order.refresh_from_db()
        self.assertEqual(order.fazer_task.status, 'queued')
