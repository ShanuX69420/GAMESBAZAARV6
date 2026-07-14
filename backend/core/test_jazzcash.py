import hashlib
import hmac
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import requests
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import jazzcash
from .models import (
    Category, Game, GameCategory, JazzCashPayment, Listing, Order,
    Wallet, WalletTransaction,
)
from .payments import (
    finalize_jazzcash_payment,
    reconcile_pending_jazzcash_payments,
    start_jazzcash_payment,
)

JAZZCASH_TEST_SETTINGS = dict(
    JAZZCASH_ENABLED=True,
    JAZZCASH_BASE_URL='https://pgw.jazzcash.com.pk',
    JAZZCASH_MERCHANT_ID='MC25041',
    JAZZCASH_PASSWORD='sz1v4agvyf',
    JAZZCASH_INTEGRITY_SALT='3vv9wu3a18',
    JAZZCASH_RETURN_URL='https://www.gamesbazaar.pk/wallet',
    JAZZCASH_SUB_MERCHANT_NAME='GamesBazaar',
    JAZZCASH_TXN_REF_PREFIX='Gam',
    JAZZCASH_REQUEST_TIMEOUT_SECONDS=5,
)


@override_settings(**JAZZCASH_TEST_SETTINGS)
class JazzCashHashTests(TestCase):
    def test_secure_hash_matches_documented_construction(self):
        """Mirror the worked example from the HMAC-SHA256 guide (2026)."""
        payload = {
            'pp_TxnRefNo': 'T20220518150213',
            'pp_Amount': '25000',
            'pp_MerchantID': 'MC25041',
            'pp_MerchantMPIN': '1234',
            'pp_Password': 'sz1v4agvyf',
            'pp_TxnCurrency': 'PKR',
        }

        salt = '3vv9wu3a18'
        message = salt + '&' + '25000&MC25041&1234&sz1v4agvyf&PKR&T20220518150213'
        expected = hmac.new(
            salt.encode(), message.encode(), hashlib.sha256
        ).hexdigest().upper()

        self.assertEqual(jazzcash.generate_secure_hash(payload), expected)

    def test_secure_hash_skips_empty_values_and_existing_hash(self):
        base = {'pp_Amount': '100', 'pp_TxnRefNo': 'Gam123'}
        padded = {
            **base,
            'ppmpf_2': '',
            'pp_BankID': None,
            'pp_SecureHash': 'SHOULD-BE-IGNORED',
        }
        self.assertEqual(
            jazzcash.generate_secure_hash(base),
            jazzcash.generate_secure_hash(padded),
        )

    def test_verify_secure_hash_round_trip_and_tamper_detection(self):
        payload = {'pp_ResponseCode': '121', 'pp_TxnRefNo': 'Gam20260610120000123'}
        payload['pp_SecureHash'] = jazzcash.generate_secure_hash(payload)
        self.assertTrue(jazzcash.verify_secure_hash(payload))

        payload['pp_ResponseCode'] = '199'
        self.assertFalse(jazzcash.verify_secure_hash(payload))

        self.assertFalse(jazzcash.verify_secure_hash({'pp_ResponseCode': '121'}))

    def test_amount_conversion_uses_paisa(self):
        self.assertEqual(jazzcash.amount_to_paisa(Decimal('100.00')), '10000')
        self.assertEqual(jazzcash.amount_to_paisa(Decimal('2.00')), '200')
        self.assertEqual(jazzcash.paisa_to_amount('10000'), Decimal('100.00'))

    def test_txn_ref_no_is_20_alphanumeric_chars(self):
        ref = jazzcash.generate_txn_ref_no()
        self.assertEqual(len(ref), 20)
        self.assertTrue(ref.isalnum())
        self.assertTrue(ref.startswith('Gam'))


@override_settings(**JAZZCASH_TEST_SETTINGS)
class JazzCashInitiationRequestTests(TestCase):
    """Lock the wire format of the MWallet v1.1 request to the 2026 guides."""

    def _capture_request(self):
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured['url'] = url
            captured['payload'] = json
            raise requests.RequestException('captured')

        with patch('core.jazzcash.requests.post', side_effect=fake_post):
            with self.assertRaises(jazzcash.JazzCashUnavailable):
                jazzcash.initiate_mwallet_payment(
                    amount=Decimal('500.00'),
                    mobile_number='03001234567',
                    txn_ref_no='Gam20260610120000123',
                    bill_reference='GBTOPUP1',
                    description='GamesBazaar wallet top-up',
                )
        return captured

    def test_initiation_posts_to_the_production_dotransaction_endpoint(self):
        self.assertEqual(
            self._capture_request()['url'],
            'https://pgw.jazzcash.com.pk/api/payment/DoTransaction',
        )

    def test_initiation_sends_exactly_the_documented_fields(self):
        payload = self._capture_request()['payload']
        self.assertEqual(set(payload), {
            'pp_Amount', 'pp_BankID', 'pp_BillReference', 'pp_Description',
            'pp_Language', 'pp_MerchantID', 'pp_Password', 'pp_ProductID',
            'pp_ReturnURL', 'pp_SecureHash', 'pp_SubMerchantID',
            'pp_SubMerchantName', 'pp_TxnCurrency', 'pp_TxnDateTime',
            'pp_TxnExpiryDateTime', 'pp_TxnRefNo', 'pp_TxnType', 'pp_Version',
            'ppmpf_1', 'ppmpf_2', 'ppmpf_3', 'ppmpf_4', 'ppmpf_5',
        })
        # Unused fields travel as "" — never null, never dropped.
        for key in ('pp_BankID', 'pp_ProductID', 'pp_SubMerchantID', 'ppmpf_5'):
            self.assertEqual(payload[key], '')

    def test_sub_merchant_name_is_letters_only_and_signed(self):
        payload = self._capture_request()['payload']
        self.assertEqual(payload['pp_SubMerchantName'], 'GamesBazaar')
        self.assertTrue(payload['pp_SubMerchantName'].isalpha())

        # A hash computed without pp_SubMerchantName is what JazzCash rejects
        # as "Hash Mismatch" — ours must not match that.
        without = {k: v for k, v in payload.items() if k != 'pp_SubMerchantName'}
        self.assertTrue(jazzcash.verify_secure_hash(payload))
        self.assertNotEqual(
            payload['pp_SecureHash'], jazzcash.generate_secure_hash(without),
        )


@override_settings(**JAZZCASH_TEST_SETTINGS)
class JazzCashPaymentFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.buyer = User.objects.create_user(username='jcbuyer', password='password123')
        self.seller = User.objects.create_user(username='jcseller', password='password123')
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])

        self.buyer_wallet = Wallet.objects.get(user=self.buyer)

        game = Game.objects.create(name='JC Game', slug='jc-game')
        self.category = Category.objects.create(name='JC Accounts', slug='jc-accounts')
        self.game_category = GameCategory.objects.create(game=game, category=self.category)

        self.listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='JazzCash item',
            price=Decimal('150.00'),
            quantity=2,
            status='active',
        )

        self.client.force_authenticate(user=self.buyer)

    def _gateway_response(self, code='000', txn_ref_no='Gam20260610120000123', **extra):
        # pp_Amount is only included when the test passes one (or fake_post
        # echoes it from the request, like the real gateway does).
        payload = {
            'pp_ResponseCode': code,
            'pp_ResponseMessage': 'Test response',
            'pp_TxnRefNo': txn_ref_no,
            'pp_RetreivalReferenceNo': '202606101200001',
            **extra,
        }
        payload['pp_SecureHash'] = jazzcash.generate_secure_hash(payload)
        return payload

    def _start_pending_payment(self, purpose='topup', amount=Decimal('300.00'), **kwargs):
        with patch(
            'core.jazzcash._post',
            side_effect=jazzcash.JazzCashUnavailable('timeout'),
        ):
            return start_jazzcash_payment(
                user=self.buyer,
                purpose=purpose,
                amount=amount,
                mobile_number='03001234567',
                description='GamesBazaar payment',
                **kwargs,
            )

    def test_topup_initiation_success_credits_wallet(self):
        def fake_post(path, payload):
            return self._gateway_response(
                code='000', txn_ref_no=payload['pp_TxnRefNo'],
                pp_Amount=payload['pp_Amount'],
            )

        with patch('core.jazzcash._post', side_effect=fake_post):
            response = self.client.post(
                '/api/payments/jazzcash/top-up/',
                {'amount': '500.00', 'mobile_number': '03001234567'},
                format='json',
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'completed')

        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('500.00'))
        self.assertTrue(
            WalletTransaction.objects.filter(
                wallet=self.buyer_wallet, transaction_type='jazzcash_topup',
            ).exists()
        )

    def test_topup_initiation_failure_does_not_credit(self):
        def fake_post(path, payload):
            return self._gateway_response(code='199', txn_ref_no=payload['pp_TxnRefNo'])

        with patch('core.jazzcash._post', side_effect=fake_post):
            response = self.client.post(
                '/api/payments/jazzcash/top-up/',
                {'amount': '500.00', 'mobile_number': '03001234567'},
                format='json',
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'failed')
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('0.00'))

    def test_topup_gateway_timeout_keeps_payment_pending(self):
        payment = self._start_pending_payment()
        self.assertEqual(payment.status, 'pending')
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('0.00'))

    def test_direct_buy_lifts_a_tiny_shortfall_to_the_minimum_charge(self):
        self.buyer_wallet.balance = Decimal('145.00')
        self.buyer_wallet.save(update_fields=['balance'])

        def fake_post(path, payload):
            return self._gateway_response(
                code='000', txn_ref_no=payload['pp_TxnRefNo'],
                pp_Amount=payload['pp_Amount'],
            )

        with patch('core.jazzcash._post', side_effect=fake_post):
            response = self.client.post(
                '/api/payments/jazzcash/buy/',
                {'listing_id': self.listing.id, 'quantity': 1,
                 'mobile_number': '03001234567'},
                format='json',
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'completed')
        self.assertIsNotNone(response.data['order_id'])
        self.assertTrue(response.data['order_number'])

        payment = JazzCashPayment.objects.get(pk=response.data['id'])
        # The 5.00 shortfall is below the gateway minimum, so 20.00 is charged.
        self.assertEqual(payment.amount, Decimal('20.00'))
        order = Order.objects.get(pk=payment.order_id)
        self.assertEqual(order.buyer, self.buyer)
        self.assertEqual(order.total_amount, Decimal('150.00'))

        # 145 wallet + 20 JazzCash - 150 purchase — the change stays in wallet.
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('15.00'))

        self.listing.refresh_from_db()
        self.assertEqual(self.listing.quantity, 1)

    def test_direct_buy_tops_up_only_the_shortfall(self):
        self.buyer_wallet.balance = Decimal('750.00')
        self.buyer_wallet.save(update_fields=['balance'])
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Pricey JazzCash item',
            price=Decimal('1000.00'),
            quantity=1,
            status='active',
        )

        def fake_post(path, payload):
            return self._gateway_response(
                code='000', txn_ref_no=payload['pp_TxnRefNo'],
                pp_Amount=payload['pp_Amount'],
            )

        with patch('core.jazzcash._post', side_effect=fake_post):
            response = self.client.post(
                '/api/payments/jazzcash/buy/',
                {'listing_id': listing.id, 'quantity': 1,
                 'mobile_number': '03001234567'},
                format='json',
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'completed')

        payment = JazzCashPayment.objects.get(pk=response.data['id'])
        # Shortfall is 250.00, well above the minimum — charge exactly that.
        self.assertEqual(payment.amount, Decimal('250.00'))
        order = Order.objects.get(pk=payment.order_id)
        self.assertEqual(order.total_amount, Decimal('1000.00'))

        # 750 wallet + 250 JazzCash - 1000 purchase = nothing left over.
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('0.00'))

    def test_direct_buy_charges_full_shortfall_when_above_min_topup(self):
        self.buyer_wallet.balance = Decimal('200.00')
        self.buyer_wallet.save(update_fields=['balance'])
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Expensive JazzCash item',
            price=Decimal('1000.00'),
            quantity=1,
            status='active',
        )

        def fake_post(path, payload):
            return self._gateway_response(
                code='000', txn_ref_no=payload['pp_TxnRefNo'],
                pp_Amount=payload['pp_Amount'],
            )

        with patch('core.jazzcash._post', side_effect=fake_post):
            response = self.client.post(
                '/api/payments/jazzcash/buy/',
                {'listing_id': listing.id, 'quantity': 1,
                 'mobile_number': '03001234567'},
                format='json',
            )

        self.assertEqual(response.status_code, 201)
        payment = JazzCashPayment.objects.get(pk=response.data['id'])
        self.assertEqual(payment.amount, Decimal('800.00'))

        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('0.00'))

    def test_direct_buy_rejected_when_wallet_covers_total(self):
        self.buyer_wallet.balance = Decimal('150.00')
        self.buyer_wallet.save(update_fields=['balance'])

        response = self.client.post(
            '/api/payments/jazzcash/buy/',
            {'listing_id': self.listing.id, 'quantity': 1,
             'mobile_number': '03001234567'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('wallet balance', response.data['error'])
        self.assertFalse(JazzCashPayment.objects.exists())

    def test_direct_buy_rejected_when_charge_exceeds_jazzcash_limit(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Above gateway limit item',
            price=Decimal('2000000.00'),
            quantity=1,
            status='active',
        )

        response = self.client.post(
            '/api/payments/jazzcash/buy/',
            {'listing_id': listing.id, 'quantity': 1,
             'mobile_number': '03001234567'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('limited to PKR 1,000,000', response.data['error'])
        self.assertFalse(JazzCashPayment.objects.exists())

    def test_direct_buy_rejects_quantity_above_maximum(self):
        response = self.client.post(
            '/api/payments/jazzcash/buy/',
            {'listing_id': self.listing.id, 'quantity': 999_999_999,
             'mobile_number': '03001234567'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('quantity', response.data)
        self.assertFalse(JazzCashPayment.objects.exists())

    def test_topup_rejects_amount_below_minimum(self):
        response = self.client.post(
            '/api/payments/jazzcash/top-up/',
            {'amount': '499.99', 'mobile_number': '03001234567'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('Minimum top-up is PKR 500.', str(response.data['amount']))
        self.assertFalse(JazzCashPayment.objects.exists())

    def test_direct_buy_falls_back_to_wallet_credit_when_listing_sold_out(self):
        payment = self._start_pending_payment(
            purpose='purchase',
            amount=Decimal('150.00'),
            listing=self.listing,
            listing_quantity=1,
        )
        self.assertEqual(payment.status, 'pending')

        # Listing sells out while the customer is paying.
        self.listing.status = 'sold'
        self.listing.quantity = 0
        self.listing.save(update_fields=['status', 'quantity'])

        payment = finalize_jazzcash_payment(payment.pk, response_code='121')

        self.assertEqual(payment.status, 'completed')
        self.assertIsNone(payment.order)
        self.assertIn('added to your wallet', payment.note)

        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('150.00'))

    def test_finalize_is_idempotent(self):
        payment = self._start_pending_payment(amount=Decimal('250.00'))

        finalize_jazzcash_payment(payment.pk, response_code='121')
        finalize_jazzcash_payment(payment.pk, response_code='121')

        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('250.00'))
        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.buyer_wallet, transaction_type='jazzcash_topup',
            ).count(),
            1,
        )

    def test_ipn_with_valid_hash_completes_pending_payment(self):
        payment = self._start_pending_payment()

        ipn_client = APIClient()  # unauthenticated, like the gateway
        ipn_payload = self._gateway_response(code='121', txn_ref_no=payment.txn_ref_no)

        first = ipn_client.post('/api/payments/jazzcash/ipn/', ipn_payload, format='json')
        second = ipn_client.post('/api/payments/jazzcash/ipn/', ipn_payload, format='json')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data['pp_ResponseCode'], '000')
        self.assertTrue(first.data['pp_SecureHash'])
        self.assertEqual(second.status_code, 200)

        payment.refresh_from_db()
        self.assertEqual(payment.status, 'completed')
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('300.00'))
        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.buyer_wallet, transaction_type='jazzcash_topup',
            ).count(),
            1,
        )

    def test_ipn_with_invalid_hash_is_rejected(self):
        payment = self._start_pending_payment()

        ipn_payload = self._gateway_response(code='121', txn_ref_no=payment.txn_ref_no)
        ipn_payload['pp_SecureHash'] = 'F' * 64

        response = APIClient().post('/api/payments/jazzcash/ipn/', ipn_payload, format='json')

        self.assertEqual(response.status_code, 400)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('0.00'))

    def test_ipn_with_matching_amount_completes_payment(self):
        payment = self._start_pending_payment()  # PKR 300.00

        ipn_payload = self._gateway_response(
            code='121', txn_ref_no=payment.txn_ref_no, pp_Amount='30000',
        )
        response = APIClient().post('/api/payments/jazzcash/ipn/', ipn_payload, format='json')

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'completed')
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('300.00'))

    def test_ipn_with_mismatched_amount_is_quarantined(self):
        payment = self._start_pending_payment()  # PKR 300.00

        ipn_payload = self._gateway_response(
            code='121', txn_ref_no=payment.txn_ref_no, pp_Amount='15000',
        )
        response = APIClient().post('/api/payments/jazzcash/ipn/', ipn_payload, format='json')

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertIn('Amount mismatch', payment.note)
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('0.00'))
        self.assertFalse(
            WalletTransaction.objects.filter(
                wallet=self.buyer_wallet, transaction_type='jazzcash_topup',
            ).exists()
        )

    def test_ipn_failure_code_marks_payment_failed(self):
        payment = self._start_pending_payment()

        ipn_payload = self._gateway_response(code='199', txn_ref_no=payment.txn_ref_no)
        response = APIClient().post('/api/payments/jazzcash/ipn/', ipn_payload, format='json')

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'failed')
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('0.00'))

    def test_status_inquiry_reconciles_pending_payment(self):
        payment = self._start_pending_payment(amount=Decimal('400.00'))

        JazzCashPayment.objects.filter(pk=payment.pk).update(
            created_at=timezone.now() - timedelta(minutes=20),
        )

        def fake_inquiry(path, payload, timeout=None):
            response = {
                'pp_ResponseCode': '000',
                'pp_ResponseMessage': 'Operation processed successfully.',
                'pp_PaymentResponseCode': '121',
                'pp_PaymentResponseMessage': 'Transaction processed successfully.',
                'pp_Status': 'Completed',
                'pp_RetrievalReferenceNo': '202606101200001',
            }
            response['pp_SecureHash'] = jazzcash.generate_secure_hash(response)
            return response

        with patch('core.jazzcash._post', side_effect=fake_inquiry):
            result = reconcile_pending_jazzcash_payments(batch_size=10)

        self.assertEqual(result['completed'], 1)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'completed')
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('400.00'))

    def test_reconcile_expires_old_unconfirmed_payment(self):
        payment = self._start_pending_payment()
        JazzCashPayment.objects.filter(pk=payment.pk).update(
            created_at=timezone.now() - timedelta(hours=26),
        )

        def fake_inquiry(path, payload, timeout=None):
            response = {
                'pp_ResponseCode': '000',
                'pp_ResponseMessage': 'Operation processed successfully.',
                'pp_PaymentResponseCode': '124',
                'pp_Status': 'Pending',
            }
            response['pp_SecureHash'] = jazzcash.generate_secure_hash(response)
            return response

        with patch('core.jazzcash._post', side_effect=fake_inquiry):
            result = reconcile_pending_jazzcash_payments(batch_size=10)

        self.assertEqual(result['expired'], 1)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'failed')

    def test_buy_endpoint_rejects_own_listing_and_invalid_mobile(self):
        self.client.force_authenticate(user=self.seller)
        response = self.client.post(
            '/api/payments/jazzcash/buy/',
            {'listing_id': self.listing.id, 'quantity': 1,
             'mobile_number': '03001234567'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('own listing', response.data['error'])

        self.client.force_authenticate(user=self.buyer)
        response = self.client.post(
            '/api/payments/jazzcash/top-up/',
            {'amount': '500.00', 'mobile_number': '1234'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(JAZZCASH_ENABLED=False)
    def test_endpoints_unavailable_when_not_configured(self):
        response = self.client.post(
            '/api/payments/jazzcash/top-up/',
            {'amount': '500.00', 'mobile_number': '03001234567'},
            format='json',
        )
        self.assertEqual(response.status_code, 503)

    def test_payment_status_endpoint_scoped_to_owner(self):
        payment = self._start_pending_payment(amount=Decimal('100.00'))

        response = self.client.get(f'/api/payments/jazzcash/{payment.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'pending')

        self.client.force_authenticate(user=self.seller)
        response = self.client.get(f'/api/payments/jazzcash/{payment.pk}/')
        self.assertEqual(response.status_code, 404)
