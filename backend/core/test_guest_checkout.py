"""Guest checkout: pay at the Buy button with no account.

The guest endpoint must create the silent account (active, unusable
password, terms accepted), sign the buyer in via the normal JWT cookies,
and start the same JazzCash direct-buy flow the logged-in checkout uses —
so the finalized payment produces a normal order owned by the new account.
"""

import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.conf import settings
from django.test import TestCase, override_settings

from . import jazzcash
from .models import JazzCashPayment
from .payments import _run_initiation, finalize_jazzcash_payment
from .test_meta_capi import (
    JAZZCASH_TEST_SETTINGS, META_TEST_SETTINGS, PurchaseFixtureMixin, sha256,
)

GUEST_BUY_URL = '/api/payments/jazzcash/guest-buy/'


@override_settings(**META_TEST_SETTINGS, **JAZZCASH_TEST_SETTINGS)
class GuestBuyTests(PurchaseFixtureMixin, TestCase):
    def setUp(self):
        self._make_marketplace()

    def _guest_buy(self, body=None):
        payload = {
            'listing_id': self.listing.id,
            'quantity': 1,
            'mobile_number': '03001234567',
            'email': 'Guest@Example.com',
        }
        payload.update(body or {})
        self.client.cookies['_fbp'] = 'fb.1.1700000000.444'
        with patch(
            'core.jazzcash._post',
            side_effect=jazzcash.JazzCashUnavailable('timeout'),
        ), patch(
            # Initiation runs on a background thread in production; inline
            # here so the payment is guaranteed pending when we return.
            'core.payments._dispatch_initiation',
            side_effect=_run_initiation,
        ), patch(
            'core.views.send_guest_account_email',
        ) as email_mock, patch('core.meta_capi._dispatch') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    GUEST_BUY_URL, payload, format='json',
                    HTTP_ORIGIN='http://testserver',
                    HTTP_USER_AGENT='GuestBrowser/1.0',
                )
        return response, email_mock, dispatch

    def test_guest_buy_creates_account_signs_in_and_starts_payment(self):
        response, email_mock, dispatch = self._guest_buy()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['payment']['status'], 'pending')

        guest = User.objects.get(email='guest@example.com')
        self.assertTrue(guest.is_active)
        self.assertFalse(guest.has_usable_password())
        self.assertEqual(guest.username, 'guest')
        self.assertTrue(guest.profile.has_accepted_terms)
        self.assertFalse(guest.profile.email_verification_pending)

        # The response signs the guest in — from here on it's a normal session.
        self.assertIn(settings.JWT_AUTH_COOKIE_ACCESS, response.cookies)
        self.assertIn(settings.JWT_AUTH_COOKIE_REFRESH, response.cookies)

        email_mock.assert_called_once_with(guest)

        # Server-side CompleteRegistration for the silent account.
        dispatch.assert_called_once()
        (event,) = dispatch.call_args.args[0]['data']
        self.assertEqual(event['event_name'], 'CompleteRegistration')
        self.assertEqual(event['event_id'], f'signup-{guest.pk}')
        self.assertEqual(event['custom_data']['content_name'], 'guest_checkout')
        self.assertEqual(event['user_data']['em'], [sha256('guest@example.com')])
        self.assertEqual(event['user_data']['fbp'], 'fb.1.1700000000.444')

        payment = JazzCashPayment.objects.get(pk=response.data['payment']['id'])
        self.assertEqual(payment.user, guest)
        self.assertEqual(payment.amount, Decimal('150.00'))

    def test_finalized_guest_payment_creates_order_for_the_guest(self):
        response, _, _ = self._guest_buy()
        payment_id = response.data['payment']['id']

        with patch('core.meta_capi._dispatch') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                payment = finalize_jazzcash_payment(payment_id, response_code='000')

        guest = User.objects.get(email='guest@example.com')
        self.assertEqual(payment.status, 'completed')
        self.assertIsNotNone(payment.order)
        self.assertEqual(payment.order.buyer, guest)

        # The Meta Purchase carries the guest's email, JazzCash number and
        # click-time cookies — full match quality despite no prior account.
        (event,) = dispatch.call_args.args[0]['data']
        self.assertEqual(event['event_name'], 'Purchase')
        user_data = event['user_data']
        self.assertEqual(user_data['em'], [sha256('guest@example.com')])
        self.assertEqual(user_data['ph'], [sha256('923001234567')])
        self.assertEqual(user_data['fbp'], 'fb.1.1700000000.444')

    def test_existing_email_is_refused_without_creating_anything(self):
        User.objects.create_user(
            username='existing', email='guest@example.com', password='password123',
        )
        response, email_mock, _ = self._guest_buy()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'account_exists')
        self.assertEqual(User.objects.filter(email__iexact='guest@example.com').count(), 1)
        self.assertEqual(JazzCashPayment.objects.count(), 0)
        email_mock.assert_not_called()

    def test_authenticated_caller_is_refused(self):
        self.client.force_authenticate(user=self.buyer)
        response, _, _ = self._guest_buy()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email__iexact='guest@example.com').exists())

    def test_validation_failure_creates_no_account(self):
        response, email_mock, _ = self._guest_buy({'quantity': 99})

        self.assertEqual(response.status_code, 400)
        self.assertIn('available', response.data['error'])
        self.assertFalse(User.objects.filter(email__iexact='guest@example.com').exists())
        email_mock.assert_not_called()

    def test_username_collision_gets_a_suffix(self):
        User.objects.create_user(
            username='guest', email='other@example.com', password='password123',
        )
        response, _, _ = self._guest_buy()

        self.assertEqual(response.status_code, 201)
        guest = User.objects.get(email='guest@example.com')
        self.assertTrue(guest.username.startswith('guest_'))


@override_settings(**JAZZCASH_TEST_SETTINGS)
class CheckoutConfigTests(TestCase):
    def test_config_is_public_and_mirrors_the_wallet_fields(self):
        response = self.client.get('/api/checkout/config/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['jazzcash_enabled'])
        self.assertEqual(
            response.data['checkout_service_fee'],
            str(settings.CHECKOUT_SERVICE_FEE_PKR),
        )
