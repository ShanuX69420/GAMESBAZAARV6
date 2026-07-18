import hashlib
import json
from decimal import Decimal
from unittest.mock import patch

import requests
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from . import jazzcash, meta_capi
from .models import Category, Game, GameCategory, Listing, Wallet
from .payments import _run_initiation, finalize_jazzcash_payment, start_jazzcash_payment

META_TEST_SETTINGS = dict(
    META_PIXEL_ID='1234567890',
    META_CAPI_ACCESS_TOKEN='test-access-token',
    META_CAPI_TEST_EVENT_CODE='',
)


def sha256(value):
    return hashlib.sha256(value.encode()).hexdigest()


class NormalizePhoneTests(TestCase):
    def test_pakistani_local_format_gains_country_code(self):
        self.assertEqual(meta_capi.normalize_phone('03001234567'), '923001234567')

    def test_spaces_plus_and_dashes_are_stripped(self):
        self.assertEqual(meta_capi.normalize_phone('+92 300-123 4567'), '923001234567')

    def test_double_zero_prefix_is_dropped(self):
        self.assertEqual(meta_capi.normalize_phone('00923001234567'), '923001234567')

    def test_garbage_and_short_numbers_are_rejected(self):
        self.assertEqual(meta_capi.normalize_phone('not a phone'), '')
        self.assertEqual(meta_capi.normalize_phone('12345'), '')
        self.assertEqual(meta_capi.normalize_phone(None), '')


@override_settings(**META_TEST_SETTINGS)
class UserDataTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='matchuser', email='Match@Example.COM', password='password123',
        )

    def test_email_and_external_id_are_normalized_and_hashed(self):
        data = meta_capi._user_data(user=self.user)
        self.assertEqual(data['em'], [sha256('match@example.com')])
        self.assertEqual(data['external_id'], [sha256(str(self.user.pk))])

    def test_tracking_fields_pass_through_unhashed_and_phone_is_hashed(self):
        data = meta_capi._user_data(user=self.user, tracking={
            'client_ip_address': '39.50.1.2',
            'client_user_agent': 'TestBrowser/1.0',
            'fbp': 'fb.1.1700000000.111',
            'fbc': 'fb.1.1700000000.AbCdEf',
            'phone': '03001234567',
        })
        self.assertEqual(data['client_ip_address'], '39.50.1.2')
        self.assertEqual(data['client_user_agent'], 'TestBrowser/1.0')
        self.assertEqual(data['fbp'], 'fb.1.1700000000.111')
        self.assertEqual(data['fbc'], 'fb.1.1700000000.AbCdEf')
        self.assertEqual(data['ph'], [sha256('923001234567')])

    def test_empty_values_are_omitted(self):
        self.user.email = ''
        data = meta_capi._user_data(user=self.user, tracking={'fbp': '', 'phone': ''})
        self.assertNotIn('em', data)
        self.assertNotIn('fbp', data)
        self.assertNotIn('ph', data)


class PurchaseFixtureMixin:
    def _make_marketplace(self):
        self.client = APIClient()
        self.buyer = User.objects.create_user(
            username='capibuyer', email='buyer@example.com', password='password123',
        )
        self.seller = User.objects.create_user(
            username='capiseller', password='password123',
        )
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])

        self.buyer_wallet = Wallet.objects.get(user=self.buyer)

        game = Game.objects.create(name='CAPI Game', slug='capi-game')
        category = Category.objects.create(name='CAPI Accounts', slug='capi-accounts')
        self.game_category = GameCategory.objects.create(game=game, category=category)

        self.listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='CAPI item',
            price=Decimal('150.00'),
            quantity=2,
            status='active',
        )


@override_settings(**META_TEST_SETTINGS)
class WalletBuyPurchaseEventTests(PurchaseFixtureMixin, TestCase):
    def setUp(self):
        self._make_marketplace()
        self.buyer_wallet.balance = Decimal('500.00')
        self.buyer_wallet.save(update_fields=['balance'])
        self.client.force_authenticate(user=self.buyer)

    def _buy(self):
        self.client.cookies['_fbp'] = 'fb.1.1700000000.111'
        self.client.cookies['_fbc'] = 'fb.1.1700000000.AbCdEf'
        with patch('core.meta_capi._dispatch') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    '/api/orders/buy/',
                    {'listing_id': self.listing.id, 'quantity': 1},
                    format='json',
                    HTTP_X_REAL_IP='39.50.1.2',
                    HTTP_USER_AGENT='TestBrowser/1.0',
                )
        return response, dispatch

    def test_wallet_buy_sends_deduplicated_purchase_event(self):
        response, dispatch = self._buy()

        self.assertEqual(response.status_code, 201)
        dispatch.assert_called_once()
        payload = dispatch.call_args.args[0]

        self.assertEqual(payload['access_token'], 'test-access-token')
        self.assertNotIn('test_event_code', payload)
        (event,) = payload['data']
        self.assertEqual(event['event_name'], 'Purchase')
        # Must match the browser pixel's eventID (purchase-<order id>).
        self.assertEqual(event['event_id'], f"purchase-{response.data['id']}")
        self.assertEqual(event['action_source'], 'website')
        self.assertIn(f'/listing/{self.listing.id}', event['event_source_url'])

        self.assertEqual(event['custom_data']['currency'], 'PKR')
        self.assertEqual(event['custom_data']['value'], 150.0)
        self.assertEqual(event['custom_data']['content_ids'], [str(self.listing.id)])
        self.assertEqual(event['custom_data']['num_items'], 1)

        user_data = event['user_data']
        self.assertEqual(user_data['em'], [sha256('buyer@example.com')])
        self.assertEqual(user_data['external_id'], [sha256(str(self.buyer.pk))])
        self.assertEqual(user_data['client_ip_address'], '39.50.1.2')
        self.assertEqual(user_data['client_user_agent'], 'TestBrowser/1.0')
        self.assertEqual(user_data['fbp'], 'fb.1.1700000000.111')
        self.assertEqual(user_data['fbc'], 'fb.1.1700000000.AbCdEf')

    def test_test_event_code_is_forwarded_when_configured(self):
        with override_settings(META_CAPI_TEST_EVENT_CODE='TEST123'):
            response, dispatch = self._buy()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(dispatch.call_args.args[0]['test_event_code'], 'TEST123')

    def test_no_event_when_capi_not_configured(self):
        with override_settings(META_PIXEL_ID='', META_CAPI_ACCESS_TOKEN=''):
            response, dispatch = self._buy()
        self.assertEqual(response.status_code, 201)
        dispatch.assert_not_called()


JAZZCASH_TEST_SETTINGS = dict(
    JAZZCASH_ENABLED=True,
    JAZZCASH_MERCHANT_ID='MC25041',
    JAZZCASH_PASSWORD='sz1v4agvyf',
    JAZZCASH_INTEGRITY_SALT='3vv9wu3a18',
    JAZZCASH_RETURN_URL='https://www.gamesbazaar.pk/wallet',
)


@override_settings(**META_TEST_SETTINGS, **JAZZCASH_TEST_SETTINGS)
class JazzCashPurchaseEventTests(PurchaseFixtureMixin, TestCase):
    """The reason CAPI exists: purchases resolved by IPN or the reconcile
    timer, with no buyer request anywhere in sight, must still reach Meta
    with the attribution data snapshotted at initiation."""

    def setUp(self):
        self._make_marketplace()

    def _pending_direct_buy(self):
        tracking = meta_capi.tracking_from_request(
            type('Req', (), {
                'META': {
                    'HTTP_X_REAL_IP': '39.50.9.9',
                    'HTTP_USER_AGENT': 'BuyerPhone/2.0',
                },
                'COOKIES': {'_fbp': 'fb.1.1700000000.222', '_fbc': ''},
            })(),
        )
        with patch(
            'core.jazzcash._post',
            side_effect=jazzcash.JazzCashUnavailable('timeout'),
        ), patch(
            # Initiation runs on a background thread in production; inline
            # here so the payment is guaranteed pending when we return.
            'core.payments._dispatch_initiation',
            side_effect=_run_initiation,
        ):
            return start_jazzcash_payment(
                user=self.buyer,
                purpose='purchase',
                amount=Decimal('150.00'),
                mobile_number='03001234567',
                description='GamesBazaar order payment',
                listing=self.listing,
                listing_quantity=1,
                meta_tracking=json.dumps(tracking),
            )

    def test_ipn_resolved_purchase_replays_stored_tracking(self):
        payment = self._pending_direct_buy()

        # Simulate a late IPN/reconcile verdict: no request context at all.
        with patch('core.meta_capi._dispatch') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                payment = finalize_jazzcash_payment(payment.pk, response_code='000')

        self.assertEqual(payment.status, 'completed')
        self.assertIsNotNone(payment.order)

        dispatch.assert_called_once()
        (event,) = dispatch.call_args.args[0]['data']
        self.assertEqual(event['event_name'], 'Purchase')
        self.assertEqual(event['event_id'], f'purchase-{payment.order_id}')
        self.assertEqual(event['custom_data']['value'], 150.0)

        user_data = event['user_data']
        self.assertEqual(user_data['fbp'], 'fb.1.1700000000.222')
        self.assertEqual(user_data['client_ip_address'], '39.50.9.9')
        self.assertEqual(user_data['client_user_agent'], 'BuyerPhone/2.0')
        # The JazzCash wallet MSISDN rides along as a hashed match key.
        self.assertEqual(user_data['ph'], [sha256('923001234567')])

    def test_finalize_survives_missing_or_corrupt_tracking(self):
        payment = self._pending_direct_buy()
        payment.meta_tracking = '{not json'
        payment.save(update_fields=['meta_tracking'])

        with patch('core.meta_capi._dispatch') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                payment = finalize_jazzcash_payment(payment.pk, response_code='000')

        self.assertEqual(payment.status, 'completed')
        self.assertIsNotNone(payment.order)
        (event,) = dispatch.call_args.args[0]['data']
        self.assertEqual(event['user_data']['ph'], [sha256('923001234567')])
        self.assertNotIn('fbp', event['user_data'])


@override_settings(**META_TEST_SETTINGS)
class RegistrationEventTests(TestCase):
    def test_email_signup_sends_complete_registration(self):
        client = APIClient()
        client.cookies['_fbp'] = 'fb.1.1700000000.333'
        with patch('core.meta_capi._dispatch') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                response = client.post(
                    '/api/auth/register/',
                    {
                        'username': 'newsignup',
                        'email': 'newsignup@example.com',
                        'password': 'S3cure!Passphrase42',
                        'password2': 'S3cure!Passphrase42',
                        'accepted_terms': True,
                    },
                    format='json',
                    HTTP_ORIGIN='http://testserver',
                )

        self.assertEqual(response.status_code, 201)
        dispatch.assert_called_once()
        (event,) = dispatch.call_args.args[0]['data']
        user = User.objects.get(username='newsignup')
        self.assertEqual(event['event_name'], 'CompleteRegistration')
        self.assertEqual(event['event_id'], f'signup-{user.pk}')
        self.assertEqual(event['custom_data']['content_name'], 'email')
        self.assertEqual(event['user_data']['em'], [sha256('newsignup@example.com')])
        self.assertEqual(event['user_data']['fbp'], 'fb.1.1700000000.333')

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_google_signup_sends_event_only_for_new_users(self, verify_google_token):
        verify_google_token.return_value = {
            'email': 'googler@example.com',
            'email_verified': True,
            'sub': 'google-sub-123',
            'name': 'Googler',
        }
        client = APIClient()

        with patch('core.meta_capi._dispatch') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                first = client.post(
                    '/api/auth/google/',
                    {'credential': 'fake-token'},
                    format='json',
                    HTTP_ORIGIN='http://testserver',
                )
        self.assertEqual(first.status_code, 200)
        dispatch.assert_called_once()
        (event,) = dispatch.call_args.args[0]['data']
        self.assertEqual(event['event_name'], 'CompleteRegistration')
        self.assertEqual(event['custom_data']['content_name'], 'google')

        # Same Google account signing in again is a login, not a signup.
        with patch('core.meta_capi._dispatch') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                second = client.post(
                    '/api/auth/google/',
                    {'credential': 'fake-token'},
                    format='json',
                    HTTP_ORIGIN='http://testserver',
                )
        self.assertEqual(second.status_code, 200)
        dispatch.assert_not_called()


@override_settings(**META_TEST_SETTINGS)
class DeliverTests(TestCase):
    """deliver() must never raise — it runs on a fire-and-forget thread."""

    PAYLOAD = {'data': [{'event_id': 'purchase-1'}], 'access_token': 'test-access-token'}

    def test_successful_delivery(self):
        with patch('core.meta_capi.requests.post') as post:
            post.return_value.status_code = 200
            self.assertTrue(meta_capi.deliver(self.PAYLOAD))
        url = post.call_args.args[0]
        self.assertIn('/1234567890/events', url)
        self.assertEqual(post.call_args.kwargs['json'], self.PAYLOAD)

    def test_network_error_is_swallowed_and_logged(self):
        with patch(
            'core.meta_capi.requests.post',
            side_effect=requests.ConnectionError('boom'),
        ):
            with self.assertLogs('core.meta_capi', level='ERROR'):
                self.assertFalse(meta_capi.deliver(self.PAYLOAD))

    def test_rejection_is_logged_without_leaking_the_payload(self):
        with patch('core.meta_capi.requests.post') as post:
            post.return_value.status_code = 400
            post.return_value.text = '{"error": "bad event"}'
            with self.assertLogs('core.meta_capi', level='ERROR') as logs:
                self.assertFalse(meta_capi.deliver(self.PAYLOAD))
        self.assertNotIn('test-access-token', '\n'.join(logs.output))
