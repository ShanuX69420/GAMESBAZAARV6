"""Buy-on-WhatsApp click tracking and sale recording.

The click endpoint must stash the browser's Meta attribution data before the
visitor leaves for WhatsApp, and completing the sale in admin must replay
that stash (plus the buyer's number) into a Meta Purchase event with
action_source 'chat'.
"""

import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from . import meta_capi
from .models import Listing, WhatsAppCheckout
from .services import complete_whatsapp_checkout
from .test_meta_capi import META_TEST_SETTINGS, PurchaseFixtureMixin, sha256

CLICK_URL = '/api/whatsapp/checkout/'


@override_settings(**META_TEST_SETTINGS)
class WhatsAppClickTests(PurchaseFixtureMixin, TestCase):
    def setUp(self):
        self._make_marketplace()

    def _click(self, body):
        self.client.cookies['_fbp'] = 'fb.1.1700000000.111'
        self.client.cookies['_fbc'] = 'fb.1.1700000000.AbCdEf'
        with patch('core.meta_capi._dispatch') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    CLICK_URL, body, format='json',
                    HTTP_ORIGIN='http://testserver',
                    HTTP_X_REAL_IP='39.50.1.2',
                    HTTP_USER_AGENT='TestBrowser/1.0',
                )
        return response, dispatch

    def test_guest_click_snapshots_tracking_and_sends_contact(self):
        response, dispatch = self._click(
            {'listing_id': self.listing.id, 'quantity': 2},
        )

        self.assertEqual(response.status_code, 201)
        checkout = WhatsAppCheckout.objects.get(ref=response.data['ref'])
        self.assertTrue(checkout.ref.startswith('WA-'))
        self.assertEqual(checkout.listing, self.listing)
        self.assertEqual(checkout.listing_title, 'CAPI item')
        self.assertEqual(checkout.quantity, 2)
        self.assertEqual(checkout.amount, Decimal('300.00'))
        self.assertEqual(checkout.status, 'clicked')
        self.assertIsNone(checkout.user)

        tracking = json.loads(checkout.meta_tracking)
        self.assertEqual(tracking['fbp'], 'fb.1.1700000000.111')
        self.assertEqual(tracking['fbc'], 'fb.1.1700000000.AbCdEf')
        self.assertEqual(tracking['client_ip_address'], '39.50.1.2')

        dispatch.assert_called_once()
        (event,) = dispatch.call_args.args[0]['data']
        self.assertEqual(event['event_name'], 'Contact')
        # Must match the browser pixel's eventID (wa-click-<ref>).
        self.assertEqual(event['event_id'], f'wa-click-{checkout.ref}')
        self.assertEqual(event['action_source'], 'website')
        self.assertIn(f'/listing/{self.listing.id}', event['event_source_url'])
        self.assertEqual(event['custom_data']['value'], 300.0)
        self.assertEqual(event['custom_data']['content_ids'], [str(self.listing.id)])
        self.assertEqual(event['user_data']['fbp'], 'fb.1.1700000000.111')
        self.assertEqual(event['user_data']['fbc'], 'fb.1.1700000000.AbCdEf')

    def test_float_icon_click_without_listing(self):
        response, dispatch = self._click({'page': '/steam'})

        self.assertEqual(response.status_code, 201)
        checkout = WhatsAppCheckout.objects.get(ref=response.data['ref'])
        self.assertIsNone(checkout.listing)
        self.assertEqual(checkout.listing_title, '')
        self.assertIsNone(checkout.amount)
        self.assertTrue(checkout.page_url.endswith('/steam'))

        (event,) = dispatch.call_args.args[0]['data']
        self.assertEqual(event['event_name'], 'Contact')
        self.assertEqual(event['custom_data'], {})
        self.assertTrue(event['event_source_url'].endswith('/steam'))

    def test_logged_in_click_records_user(self):
        self.client.force_authenticate(user=self.buyer)
        response, dispatch = self._click({'listing_id': self.listing.id})

        checkout = WhatsAppCheckout.objects.get(ref=response.data['ref'])
        self.assertEqual(checkout.user, self.buyer)
        (event,) = dispatch.call_args.args[0]['data']
        self.assertEqual(event['user_data']['em'], [sha256('buyer@example.com')])

    def test_unknown_listing_is_rejected(self):
        response, _ = self._click({'listing_id': 999999})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(WhatsAppCheckout.objects.count(), 0)

    def test_cross_site_post_is_rejected(self):
        response = self.client.post(CLICK_URL, {}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(WhatsAppCheckout.objects.count(), 0)


@override_settings(**META_TEST_SETTINGS)
class WhatsAppCompletionTests(PurchaseFixtureMixin, TestCase):
    def setUp(self):
        self._make_marketplace()

    def _make_checkout(self, **overrides):
        fields = dict(
            listing=self.listing,
            listing_title=self.listing.title,
            quantity=1,
            amount=Decimal('150.00'),
            buyer_phone='03001234567',
            meta_tracking=json.dumps({
                'client_ip_address': '39.50.1.2',
                'client_user_agent': 'TestBrowser/1.0',
                'fbp': 'fb.1.1700000000.111',
                'fbc': 'fb.1.1700000000.AbCdEf',
            }),
        )
        fields.update(overrides)
        return WhatsAppCheckout.objects.create(**fields)

    def _complete(self, checkout):
        with patch('core.meta_capi._dispatch') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                warnings = complete_whatsapp_checkout(checkout)
        return warnings, dispatch

    def test_completion_sends_chat_purchase_with_stash_and_phone(self):
        checkout = self._make_checkout()
        warnings, dispatch = self._complete(checkout)

        self.assertEqual(warnings, [])
        checkout.refresh_from_db()
        self.assertEqual(checkout.status, 'completed')
        self.assertIsNotNone(checkout.completed_at)

        dispatch.assert_called_once()
        (event,) = dispatch.call_args.args[0]['data']
        self.assertEqual(event['event_name'], 'Purchase')
        self.assertEqual(event['event_id'], f'wa-purchase-{checkout.ref}')
        self.assertEqual(event['action_source'], 'chat')
        self.assertNotIn('event_source_url', event)

        user_data = event['user_data']
        self.assertEqual(user_data['ph'], [sha256('923001234567')])
        self.assertEqual(user_data['fbp'], 'fb.1.1700000000.111')
        self.assertEqual(user_data['fbc'], 'fb.1.1700000000.AbCdEf')
        self.assertEqual(user_data['client_ip_address'], '39.50.1.2')

        custom = event['custom_data']
        self.assertEqual(custom['currency'], 'PKR')
        self.assertEqual(custom['value'], 150.0)
        self.assertEqual(custom['content_ids'], [str(self.listing.id)])
        self.assertEqual(custom['num_items'], 1)

    def test_completion_reduces_stock_and_marks_sold_at_zero(self):
        checkout = self._make_checkout(quantity=2, amount=Decimal('300.00'))
        warnings, _ = self._complete(checkout)

        self.assertEqual(warnings, [])
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.quantity, 0)
        self.assertEqual(self.listing.status, 'sold')

    def test_completion_clamps_oversold_stock_with_warning(self):
        checkout = self._make_checkout(quantity=5, amount=Decimal('750.00'))
        warnings, _ = self._complete(checkout)

        self.assertEqual(len(warnings), 1)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.quantity, 0)
        self.assertEqual(self.listing.status, 'sold')

    def test_auto_delivery_stock_is_left_alone_with_warning(self):
        self.listing.is_auto_delivery = True
        self.listing.save(update_fields=['is_auto_delivery'])
        checkout = self._make_checkout()
        warnings, dispatch = self._complete(checkout)

        self.assertEqual(len(warnings), 1)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.quantity, 2)
        self.assertEqual(self.listing.status, 'active')
        # The Meta event still goes out — only stock is manual.
        dispatch.assert_called_once()

    def test_completion_without_stash_still_matches_by_phone(self):
        # Hand-added row for a buyer who messaged directly (no site click).
        checkout = self._make_checkout(meta_tracking='')
        warnings, dispatch = self._complete(checkout)

        (event,) = dispatch.call_args.args[0]['data']
        self.assertEqual(event['user_data'], {
            'country': [sha256('pk')],
            'ph': [sha256('923001234567')],
        })

    def test_completion_reads_a_number_typed_without_the_leading_zero(self):
        # WA-4CUF5J (2026-09-07): hand-added row, number typed '327 5980619'.
        # The phone normalised to nothing and Meta rejected a Purchase that
        # carried only the country (error 2804050).
        checkout = self._make_checkout(meta_tracking='', buyer_phone='327 5980619')
        _, dispatch = self._complete(checkout)

        (event,) = dispatch.call_args.args[0]['data']
        self.assertEqual(event['user_data']['ph'], [sha256('923275980619')])

    def test_unmatchable_completion_records_the_sale_but_sends_nothing(self):
        checkout = self._make_checkout(meta_tracking='', buyer_phone='12345')
        with self.assertLogs('core.meta_capi', level='WARNING'):
            _, dispatch = self._complete(checkout)

        dispatch.assert_not_called()
        checkout.refresh_from_db()
        self.assertEqual(checkout.status, 'completed')

    def test_completed_sales_reach_the_admin_dashboard(self):
        # WhatsApp sales create no Order rows, so the dashboard reads them
        # from WhatsAppCheckout directly — clicked rows must not count.
        self._complete(self._make_checkout(amount=Decimal('500.00')))
        self._make_checkout(amount=Decimal('999.00'))  # clicked, never sold

        staff = User.objects.create_user(
            username='dashstaff', password='password123',
            is_staff=True, is_superuser=True,
        )
        web = Client()
        web.force_login(staff)
        kpis = web.get('/admin/dashboard/stats/').json()['kpis']

        self.assertEqual(kpis['whatsapp_sales'], 1)
        self.assertEqual(kpis['whatsapp_revenue'], 500.0)
        self.assertEqual(
            kpis['all_channels_revenue'],
            kpis['total_revenue'] + 500.0,
        )


@override_settings(**META_TEST_SETTINGS)
class WhatsAppAdminTests(PurchaseFixtureMixin, TestCase):
    """The admin change form is the only place a buyer number is typed, so it
    is where an unreadable one has to be caught."""

    def setUp(self):
        self._make_marketplace()
        staff = User.objects.create_user(
            username='wastaff', password='password123',
            is_staff=True, is_superuser=True,
        )
        self.web = Client()
        self.web.force_login(staff)
        self.checkout = WhatsAppCheckout.objects.create(
            listing=self.listing, listing_title=self.listing.title,
            quantity=1, amount=Decimal('150.00'),
        )

    def _save(self, **fields):
        data = {
            'status': 'clicked', 'listing': self.listing.pk, 'quantity': 1,
            'amount': '150.00', 'buyer_phone': '', '_save': 'Save',
        }
        data.update(fields)
        with patch('core.meta_capi._dispatch') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.web.post(
                    f'/admin/core/whatsappcheckout/{self.checkout.pk}/change/', data,
                )
        self.checkout.refresh_from_db()
        return response, dispatch

    def test_unreadable_number_is_refused_before_the_sale_completes(self):
        response, dispatch = self._save(status='completed', buyer_phone='12345')

        self.assertEqual(response.status_code, 200)  # form shown again
        self.assertContains(response, 'Enter the full WhatsApp number')
        self.assertEqual(self.checkout.status, 'clicked')
        self.assertEqual(self.checkout.buyer_phone, '')
        dispatch.assert_not_called()

    def test_number_without_leading_zero_completes_and_matches(self):
        response, dispatch = self._save(status='completed', buyer_phone='327 5980619')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.checkout.status, 'completed')
        (event,) = dispatch.call_args.args[0]['data']
        self.assertEqual(event['event_id'], f'wa-purchase-{self.checkout.ref}')
        self.assertEqual(event['user_data']['ph'], [sha256('923275980619')])

    def test_blank_number_is_still_allowed_while_the_row_is_open(self):
        response, dispatch = self._save(buyer_phone='', amount='175.00')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.checkout.amount, Decimal('175.00'))
        self.assertEqual(self.checkout.status, 'clicked')
        dispatch.assert_not_called()


@override_settings(**META_TEST_SETTINGS)
class ResendWhatsAppPurchaseCommandTests(PurchaseFixtureMixin, TestCase):
    def setUp(self):
        self._make_marketplace()
        self.checkout = WhatsAppCheckout.objects.create(
            listing=self.listing, listing_title=self.listing.title, quantity=1,
            amount=Decimal('1940.00'), buyer_phone='327 5980619',
            status='completed', completed_at=timezone.now() - timedelta(hours=3),
        )

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        with patch('core.meta_capi.deliver', return_value=True) as deliver:
            call_command('resend_whatsapp_purchase', *args, stdout=out, stderr=err)
        return deliver, out.getvalue(), err.getvalue()

    def test_resends_with_the_completion_time_and_readable_phone(self):
        deliver, out, _ = self._run(self.checkout.ref)

        deliver.assert_called_once()
        payload = deliver.call_args.args[0]
        self.assertEqual(payload['access_token'], 'test-access-token')
        (event,) = payload['data']
        self.assertEqual(event['event_id'], f'wa-purchase-{self.checkout.ref}')
        self.assertEqual(event['action_source'], 'chat')
        self.assertEqual(event['event_time'], int(self.checkout.completed_at.timestamp()))
        self.assertEqual(event['user_data']['ph'], [sha256('923275980619')])
        self.assertEqual(event['custom_data']['value'], 1940.0)
        self.assertIn('Sent', out)

    def test_dry_run_sends_nothing(self):
        deliver, out, _ = self._run(self.checkout.ref, '--dry-run')

        deliver.assert_not_called()
        self.assertIn('[dry-run]', out)
        self.assertIn('ph', out)

    def test_refuses_rows_meta_would_not_take(self):
        clicked = WhatsAppCheckout.objects.create(listing=self.listing, quantity=1)
        stale = WhatsAppCheckout.objects.create(
            listing=self.listing, quantity=1, amount=Decimal('10.00'),
            buyer_phone='03001234567', status='completed',
            completed_at=timezone.now() - timedelta(days=8),
        )
        unmatchable = WhatsAppCheckout.objects.create(
            listing=self.listing, quantity=1, amount=Decimal('10.00'),
            buyer_phone='12345', status='completed', completed_at=timezone.now(),
        )

        for ref in (clicked.ref, stale.ref, unmatchable.ref, 'WA-NOPE00'):
            with patch('core.meta_capi.deliver') as deliver:
                with self.assertRaises(CommandError, msg=ref):
                    call_command('resend_whatsapp_purchase', ref,
                                 stdout=StringIO(), stderr=StringIO())
            deliver.assert_not_called()
