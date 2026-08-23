"""First-touch acquisition attribution.

The browser stashes the first visit's referrer + landing page and sends
it when an account gets created; core/attribution.py derives a stable
source label, writes it onto the profile exactly once, and every order
snapshots the label at purchase time. These tests pin the derivation
table, the write-once rule, the payload hygiene (attribution must never
break a signup), and the wiring through all three account-creation doors.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from . import jazzcash
from .attribution import apply_first_touch, derive_source
from .payments import _run_initiation
from .test_meta_capi import (
    JAZZCASH_TEST_SETTINGS, META_TEST_SETTINGS, PurchaseFixtureMixin,
)
from .views import execute_listing_purchase

CHATGPT_LANDING = '/listing/28402?utm_source=chatgpt.com'


class DeriveSourceTests(SimpleTestCase):
    def test_utm_source_beats_the_referrer(self):
        self.assertEqual(
            derive_source('https://www.google.com/', CHATGPT_LANDING),
            'chatgpt',
        )

    def test_known_referrer_hosts(self):
        cases = {
            'https://www.google.com/': 'google',
            'https://google.com.pk/url?q=x': 'google',
            'https://images.google.com/': 'google',
            'https://gemini.google.com/': 'gemini',
            'https://www.googleadservices.com/pagead/aclk': 'google-ads',
            'https://chatgpt.com/': 'chatgpt',
            'https://chat.openai.com/': 'chatgpt',
            'https://m.facebook.com/': 'facebook',
            'https://l.instagram.com/': 'instagram',
            'https://www.youtube.com/': 'youtube',
            'https://t.co/abc': 'twitter',
            'https://www.bing.com/search?q=x': 'bing',
        }
        for referrer, expected in cases.items():
            with self.subTest(referrer=referrer):
                self.assertEqual(derive_source(referrer, '/'), expected)

    def test_click_ids_identify_paid_and_social_traffic(self):
        self.assertEqual(derive_source('', '/?gclid=abc'), 'google-ads')
        self.assertEqual(derive_source('', '/?fbclid=xyz'), 'facebook')

    def test_no_referrer_is_direct_unknown_is_other(self):
        self.assertEqual(derive_source('', '/'), 'direct')
        self.assertEqual(derive_source('https://someblog.example/', '/'), 'other')

    def test_lookalike_hosts_do_not_match(self):
        self.assertEqual(derive_source('https://notgoogle.com/', '/'), 'other')

    def test_unknown_utm_source_is_kept_sanitized(self):
        self.assertEqual(
            derive_source('', '/?utm_source=My Newsletter!'),
            'mynewsletter',
        )


class ApplyFirstTouchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='attribuser', email='attrib@example.com', password='password123',
        )

    def _payload(self, **overrides):
        payload = {
            'referrer': 'https://www.google.com/',
            'landing_page': CHATGPT_LANDING,
            'first_seen_at': '2026-08-23T13:50:00Z',
        }
        payload.update(overrides)
        return payload

    def test_applies_once_and_never_overwrites(self):
        apply_first_touch(self.user, self._payload())
        profile = self.user.profile
        profile.refresh_from_db()
        self.assertEqual(profile.acquisition_source, 'chatgpt')
        self.assertEqual(profile.acquisition_referrer, 'https://www.google.com/')
        self.assertEqual(profile.acquisition_landing_page, CHATGPT_LANDING)
        self.assertEqual(
            profile.acquisition_first_seen_at.isoformat(),
            '2026-08-23T13:50:00+00:00',
        )

        apply_first_touch(self.user, self._payload(referrer='https://x.com/'))
        profile.refresh_from_db()
        self.assertEqual(profile.acquisition_source, 'chatgpt')
        self.assertEqual(profile.acquisition_referrer, 'https://www.google.com/')

    def test_malformed_payloads_leave_the_profile_blank(self):
        for bad in (None, 'utm_source=x', 42, [], {}, {'referrer': '', 'landing_page': ''}):
            with self.subTest(bad=bad):
                apply_first_touch(self.user, bad)
        profile = self.user.profile
        profile.refresh_from_db()
        self.assertEqual(profile.acquisition_source, '')
        self.assertIsNone(profile.acquisition_first_seen_at)

    def test_landing_page_must_be_a_site_path(self):
        apply_first_touch(self.user, self._payload(landing_page='https://evil.example/x'))
        profile = self.user.profile
        profile.refresh_from_db()
        # The referrer still counts; the untrusted landing URL is dropped.
        self.assertEqual(profile.acquisition_source, 'google')
        self.assertEqual(profile.acquisition_landing_page, '')

    def test_implausible_timestamps_are_clamped_to_now(self):
        future = (timezone.now() + timedelta(days=2)).isoformat()
        apply_first_touch(self.user, self._payload(first_seen_at=future))
        profile = self.user.profile
        profile.refresh_from_db()
        self.assertLessEqual(profile.acquisition_first_seen_at, timezone.now())

    def test_overlong_values_are_truncated(self):
        apply_first_touch(self.user, self._payload(referrer='https://spam.example/' + 'a' * 900))
        profile = self.user.profile
        profile.refresh_from_db()
        self.assertEqual(len(profile.acquisition_referrer), 500)


class RegisterAttributionTests(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _register(self, extra=None):
        payload = {
            'username': 'newbuyer',
            'email': 'newbuyer@example.com',
            'password': 'S3cure!Passphrase42',
            'password2': 'S3cure!Passphrase42',
            'accepted_terms': True,
        }
        payload.update(extra or {})
        return self.client.post(
            '/api/auth/register/', payload, format='json',
            HTTP_ORIGIN='http://testserver',
        )

    def test_register_stores_first_touch(self):
        response = self._register({'attribution': {
            'referrer': '',
            'landing_page': CHATGPT_LANDING,
            'first_seen_at': '2026-08-23T13:50:00Z',
        }})
        self.assertEqual(response.status_code, 201)
        profile = User.objects.get(username='newbuyer').profile
        self.assertEqual(profile.acquisition_source, 'chatgpt')
        self.assertEqual(profile.acquisition_landing_page, CHATGPT_LANDING)

    def test_register_without_attribution_stays_blank(self):
        response = self._register()
        self.assertEqual(response.status_code, 201)
        profile = User.objects.get(username='newbuyer').profile
        self.assertEqual(profile.acquisition_source, '')
        self.assertIsNone(profile.acquisition_first_seen_at)

    def test_garbage_attribution_never_blocks_the_signup(self):
        response = self._register({'attribution': 'not-a-dict'})
        self.assertEqual(response.status_code, 201)


@override_settings(**META_TEST_SETTINGS, **JAZZCASH_TEST_SETTINGS)
class GuestCheckoutAttributionTests(PurchaseFixtureMixin, TestCase):
    def setUp(self):
        self._make_marketplace()
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_guest_checkout_stores_first_touch(self):
        payload = {
            'listing_id': self.listing.id,
            'quantity': 1,
            'mobile_number': '03001234567',
            'email': 'guest@example.com',
            'attribution': {
                'referrer': 'https://www.google.com/',
                'landing_page': '/listing/5',
                'first_seen_at': '2026-08-23T13:50:00Z',
            },
        }
        with patch(
            'core.jazzcash._post',
            side_effect=jazzcash.JazzCashUnavailable('timeout'),
        ), patch(
            'core.payments._dispatch_initiation', side_effect=_run_initiation,
        ), patch('core.views.send_guest_account_email'), patch(
            'core.meta_capi._dispatch',
        ):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    '/api/payments/jazzcash/guest-buy/', payload, format='json',
                    HTTP_ORIGIN='http://testserver',
                )
        self.assertEqual(response.status_code, 201)
        profile = User.objects.get(email='guest@example.com').profile
        self.assertEqual(profile.acquisition_source, 'google')


class OrderSnapshotTests(PurchaseFixtureMixin, TestCase):
    def setUp(self):
        self._make_marketplace()
        self.buyer_wallet.balance = Decimal('500.00')
        self.buyer_wallet.save(update_fields=['balance'])

    def test_order_snapshots_the_buyer_source(self):
        profile = self.buyer.profile
        profile.acquisition_source = 'chatgpt'
        profile.acquisition_first_seen_at = timezone.now()
        profile.save(update_fields=['acquisition_source', 'acquisition_first_seen_at'])

        order, error = execute_listing_purchase(
            buyer=self.buyer, listing_id=self.listing.id, quantity=1,
        )
        self.assertIsNone(error)
        self.assertEqual(order.buyer_source, 'chatgpt')

    def test_pre_attribution_buyers_stamp_blank(self):
        order, error = execute_listing_purchase(
            buyer=self.buyer, listing_id=self.listing.id, quantity=1,
        )
        self.assertIsNone(error)
        self.assertEqual(order.buyer_source, '')
