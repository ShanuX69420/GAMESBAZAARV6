"""Rental expiry reminders: a delivered rental earns one "ends in 3 days"
email and one "ends in 24 hours" email, timed from delivery + the listing's
Rental Period, each sent at most once and never after the rental ended."""

from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import (
    Category, Filter, FilterOption, Game, GameCategory, GameCategoryFilter,
    Listing, Order,
)
from .rentals import format_pakistan_time, rental_period_days


@override_settings(PUBLIC_SITE_URL='https://www.gamesbazaar.pk')
class RentalExpiryFixture(TestCase):
    def setUp(self):
        cache.clear()
        self.buyer = User.objects.create_user(
            username='rentbuyer', email='rentbuyer@example.com',
            password='password123',
        )
        self.seller = User.objects.create_user(
            username='rentseller', password='password123',
        )
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])

        self.game = Game.objects.create(name='Elden Ring', slug='elden-ring')
        rentals = Category.objects.create(name='Rentals', slug='rentals')
        keys = Category.objects.create(name='Keys', slug='keys')
        self.rentals_gc = GameCategory.objects.create(game=self.game, category=rentals)
        self.keys_gc = GameCategory.objects.create(game=self.game, category=keys)

        self.period_filter = Filter.objects.create(
            name='Rental Period', admin_label='Rental Period', filter_type='button',
        )
        for idx, label in enumerate(['7 Days', '14 Days', '30 Days']):
            FilterOption.objects.create(filter=self.period_filter, label=label,
                                        value=label.lower().replace(' ', '-'), order=idx)
        GameCategoryFilter.objects.create(
            game_category=self.rentals_gc, filter=self.period_filter, order=0,
        )

    def make_rental_order(self, *, days=7, remaining_hours, game_category=None,
                          buyer=None, status='completed', filter_values=None,
                          title=None):
        """A rental delivered so that `remaining_hours` are left on it."""
        game_category = game_category or self.rentals_gc
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=game_category,
            title=title if title is not None else f'Elden Ring (PS4/PS5) — Rent {days} Days',
            price=Decimal('900.00'),
            status='active',
            filter_values=(
                {str(self.period_filter.id): f'{days}-days'}
                if filter_values is None else filter_values
            ),
        )
        delivered_at = timezone.now() - timedelta(days=days) + timedelta(hours=remaining_hours)
        return Order.objects.create(
            buyer=buyer or self.buyer,
            seller=self.seller,
            listing=listing,
            listing_title=listing.title,
            quantity=1,
            unit_price=Decimal('900.00'),
            total_amount=Decimal('900.00'),
            commission_rate=Decimal('0.00'),
            commission_amount=Decimal('0.00'),
            seller_amount=Decimal('900.00'),
            status=status,
            delivered_at=delivered_at if status == 'completed' else None,
            completed_at=delivered_at if status == 'completed' else None,
        )

    def run_command(self, *args):
        out = StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command('send_rental_expiry_emails', *args, stdout=out)
        return out.getvalue()


class RentalPeriodParsingTests(RentalExpiryFixture):
    def test_reads_rental_period_filter_value(self):
        order = self.make_rental_order(days=14, remaining_hours=100)
        self.assertEqual(
            rental_period_days(order.listing, order.listing_title, {self.period_filter.id}),
            14,
        )

    def test_falls_back_to_any_days_value_then_title(self):
        order = self.make_rental_order(days=30, remaining_hours=100,
                                       filter_values={'999': '30-days'})
        self.assertEqual(rental_period_days(order.listing, order.listing_title, set()), 30)

        order = self.make_rental_order(days=10, remaining_hours=100, filter_values={},
                                       title='Elden Ring (PS4/PS5) — Rent 10 Days')
        self.assertEqual(rental_period_days(order.listing, order.listing_title, set()), 10)

    def test_unknown_period_is_none(self):
        order = self.make_rental_order(days=7, remaining_hours=100, filter_values={},
                                       title='Elden Ring (PS4/PS5)')
        self.assertIsNone(rental_period_days(order.listing, order.listing_title, set()))

    def test_pakistan_time_format(self):
        moment = datetime(2026, 9, 16, 16, 30, tzinfo=dt_timezone.utc)
        self.assertEqual(format_pakistan_time(moment), 'Wed 16 Sep 2026, 9:30 PM PKT')


class SendRentalExpiryEmailsCommandTests(RentalExpiryFixture):
    def test_three_day_reminder_sent_once(self):
        order = self.make_rental_order(remaining_hours=70)

        self.run_command()

        order.refresh_from_db()
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ['rentbuyer@example.com'])
        self.assertEqual(email.subject, 'Your Elden Ring rental ends in 3 days')
        self.assertIn('7-day rental', email.body)
        self.assertIn(format_pakistan_time(order.delivered_at + timedelta(days=7)), email.body)
        self.assertIn(f'https://www.gamesbazaar.pk/listing/{order.listing_id}', email.body)
        self.assertIsNotNone(order.rental_expiry_email_72h_sent_at)
        self.assertIsNone(order.rental_expiry_email_24h_sent_at)

        self.run_command()
        self.assertEqual(len(mail.outbox), 1)

    def test_one_day_reminder_follows_three_day_reminder(self):
        order = self.make_rental_order(remaining_hours=70)
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)

        # Two days pass: 22 hours left.
        Order.objects.filter(pk=order.pk).update(
            delivered_at=order.delivered_at - timedelta(hours=48),
            completed_at=order.completed_at - timedelta(hours=48),
        )
        self.run_command()

        order.refresh_from_db()
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].subject, 'Your Elden Ring rental ends in 24 hours')
        self.assertIsNotNone(order.rental_expiry_email_24h_sent_at)

        self.run_command()
        self.assertEqual(len(mail.outbox), 2)

    def test_rental_first_seen_in_last_day_gets_only_the_one_day_reminder(self):
        order = self.make_rental_order(remaining_hours=20)

        self.run_command()

        order.refresh_from_db()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, 'Your Elden Ring rental ends in 24 hours')
        self.assertIsNone(order.rental_expiry_email_72h_sent_at)
        self.assertIsNotNone(order.rental_expiry_email_24h_sent_at)

        self.run_command()
        self.assertEqual(len(mail.outbox), 1)

    def test_nothing_before_the_window_or_after_expiry(self):
        self.make_rental_order(remaining_hours=100)
        self.make_rental_order(remaining_hours=-1)
        self.make_rental_order(days=30, remaining_hours=-24 * 20)

        self.run_command()

        self.assertEqual(len(mail.outbox), 0)

    def test_skips_non_rentals_pending_orders_and_buyers_without_email(self):
        self.make_rental_order(remaining_hours=70, game_category=self.keys_gc)
        self.make_rental_order(remaining_hours=70, status='pending')
        no_email = User.objects.create_user(username='noemail', password='password123')
        self.make_rental_order(remaining_hours=70, buyer=no_email)

        self.run_command()

        self.assertEqual(len(mail.outbox), 0)

    def test_skips_rental_whose_period_cannot_be_told(self):
        self.make_rental_order(remaining_hours=70, filter_values={},
                               title='Elden Ring (PS4/PS5)')

        self.run_command()

        self.assertEqual(len(mail.outbox), 0)

    def test_period_from_title_when_filter_values_missing(self):
        self.make_rental_order(days=14, remaining_hours=70, filter_values={})

        self.run_command()

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('14-day rental', mail.outbox[0].body)

    def test_rent_again_link_falls_back_to_game_rentals_page(self):
        order = self.make_rental_order(remaining_hours=70)
        order.listing.status = 'inactive'
        order.listing.save(update_fields=['status'])

        self.run_command()

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('https://www.gamesbazaar.pk/games/elden-ring/rentals', mail.outbox[0].body)
        self.assertNotIn(f'/listing/{order.listing_id}', mail.outbox[0].body)

    def test_dry_run_reports_without_sending_or_stamping(self):
        order = self.make_rental_order(remaining_hours=70)

        output = self.run_command('--dry-run')

        order.refresh_from_db()
        self.assertEqual(len(mail.outbox), 0)
        self.assertIsNone(order.rental_expiry_email_72h_sent_at)
        self.assertIn('Would email rentbuyer@example.com (72h reminder)', output)
        self.assertIn('Would email 1 rental reminder(s).', output)

    def test_batch_size_caps_a_run(self):
        self.make_rental_order(remaining_hours=70)
        self.make_rental_order(remaining_hours=60)

        self.run_command('--batch-size', '1')
        self.assertEqual(len(mail.outbox), 1)

        self.run_command('--batch-size', '1')
        self.assertEqual(len(mail.outbox), 2)

    def test_emails_off_switch_respected(self):
        self.make_rental_order(remaining_hours=70)

        with override_settings(TRANSACTIONAL_EMAILS_ENABLED=False):
            self.run_command()

        self.assertEqual(len(mail.outbox), 0)
