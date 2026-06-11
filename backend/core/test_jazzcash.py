import hashlib
import hmac
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

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
    JAZZCASH_BASE_URL='https://onlinepayments.jazzcash.com.pk',
    JAZZCASH_MERCHANT_ID='MC25041',
    JAZZCASH_PASSWORD='sz1v4agvyf',
    JAZZCASH_INTEGRITY_SALT='3vv9wu3a18',
    JAZZCASH_RETURN_URL='https://www.gamesbazaar.pk/wallet',
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
        payload = {
            'pp_Amount': '15000',
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
            return self._gateway_response(code='000', txn_ref_no=payload['pp_TxnRefNo'])

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

    def test_direct_buy_success_creates_order_with_net_zero_wallet(self):
        def fake_post(path, payload):
            return self._gateway_response(code='000', txn_ref_no=payload['pp_TxnRefNo'])

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
        order = Order.objects.get(pk=payment.order_id)
        self.assertEqual(order.buyer, self.buyer)
        self.assertEqual(order.total_amount, Decimal('150.00'))

        # JazzCash credit then purchase debit — wallet nets to zero.
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('0.00'))

        self.listing.refresh_from_db()
        self.assertEqual(self.listing.quantity, 1)

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

        def fake_inquiry(path, payload):
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

        def fake_inquiry(path, payload):
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
