"""Review-request emails: a completed order earns exactly one "How was your
order?" email with a no-login review link, delayed by what was bought —
top-ups a few hours after completion, keys/accounts a day after."""

from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Category, Game, GameCategory, Listing, Order, Review


class ReviewRequestFixture(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.buyer = User.objects.create_user(
            username='rrbuyer', email='rrbuyer@example.com',
            password='password123',
        )
        self.seller = User.objects.create_user(
            username='rrseller', password='password123',
        )
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])

        game = Game.objects.create(name='RR Game', slug='rr-game')
        topups = Category.objects.create(name='RR Top-ups', slug='top-ups')
        keys = Category.objects.create(name='RR Keys', slug='keys')
        self.topup_gc = GameCategory.objects.create(game=game, category=topups)
        self.keys_gc = GameCategory.objects.create(game=game, category=keys)

    def make_completed_order(self, game_category, hours_ago, buyer=None):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=game_category,
            title=f'{game_category.category.name} item',
            price=Decimal('100.00'),
            status='active',
        )
        return Order.objects.create(
            buyer=buyer or self.buyer,
            seller=self.seller,
            listing=listing,
            listing_title=listing.title,
            quantity=1,
            unit_price=Decimal('100.00'),
            total_amount=Decimal('100.00'),
            commission_rate=Decimal('10.00'),
            commission_amount=Decimal('10.00'),
            seller_amount=Decimal('90.00'),
            status='completed',
            completed_at=timezone.now() - timedelta(hours=hours_ago),
        )

    def run_command(self, *args):
        with self.captureOnCommitCallbacks(execute=True):
            call_command('send_review_requests', *args, stdout=StringIO())


class SendReviewRequestsCommandTests(ReviewRequestFixture):
    def test_topup_order_emailed_once_after_quick_delay(self):
        order = self.make_completed_order(self.topup_gc, hours_ago=4)

        self.run_command()

        order.refresh_from_db()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['rrbuyer@example.com'])
        self.assertIsNotNone(order.review_email_sent_at)
        self.assertTrue(order.review_token)
        self.assertIn(f'/review/{order.review_token}', mail.outbox[0].body)

        self.run_command()  # never emails the same order twice
        self.assertEqual(len(mail.outbox), 1)

    def test_topup_order_waits_out_the_quick_delay(self):
        self.make_completed_order(self.topup_gc, hours_ago=1)
        self.run_command()
        self.assertEqual(len(mail.outbox), 0)

    def test_keys_order_waits_a_full_day(self):
        self.make_completed_order(self.keys_gc, hours_ago=5)
        self.run_command()
        self.assertEqual(len(mail.outbox), 0)

        self.make_completed_order(self.keys_gc, hours_ago=25)
        self.run_command()
        self.assertEqual(len(mail.outbox), 1)

    def test_reviewed_old_and_emailless_orders_are_skipped(self):
        reviewed = self.make_completed_order(self.topup_gc, hours_ago=4)
        Review.objects.create(
            order=reviewed, reviewer=self.buyer, seller=self.seller, rating=5,
        )
        self.make_completed_order(self.topup_gc, hours_ago=24 * 8)  # too old
        no_email = User.objects.create_user(username='rrsilent', password='password123')
        self.make_completed_order(self.topup_gc, hours_ago=4, buyer=no_email)

        self.run_command()
        self.assertEqual(len(mail.outbox), 0)

    def test_dry_run_sends_nothing_and_stamps_nothing(self):
        order = self.make_completed_order(self.topup_gc, hours_ago=4)
        self.run_command('--dry-run')

        order.refresh_from_db()
        self.assertEqual(len(mail.outbox), 0)
        self.assertIsNone(order.review_email_sent_at)


class OrderReviewTokenEndpointTests(ReviewRequestFixture):
    """The /api/reviews/whatsapp/<token>/ page also serves order tokens."""

    def _tokened_order(self):
        order = self.make_completed_order(self.topup_gc, hours_ago=4)
        order.ensure_review_token()
        order.save(update_fields=['review_token', 'updated_at'])
        return order

    def test_get_returns_sale_context(self):
        order = self._tokened_order()
        response = self.client.get(f'/api/reviews/whatsapp/{order.review_token}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['listing_title'], order.listing_title)
        self.assertFalse(response.data['reviewed'])

    def test_post_creates_review_credited_to_the_buyer(self):
        order = self._tokened_order()
        response = self.client.post(
            f'/api/reviews/whatsapp/{order.review_token}/',
            {'rating': 5, 'comment': 'Arrived instantly.'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        review = Review.objects.get(order=order)
        self.assertEqual(review.reviewer, self.buyer)
        self.assertEqual(review.seller, self.seller)
        self.assertEqual(review.rating, 5)

        duplicate = self.client.post(
            f'/api/reviews/whatsapp/{order.review_token}/',
            {'rating': 4}, format='json',
        )
        self.assertEqual(duplicate.status_code, 400)

    def test_refunded_order_token_stops_working(self):
        order = self._tokened_order()
        order.status = 'cancelled'
        order.save(update_fields=['status', 'updated_at'])

        response = self.client.get(f'/api/reviews/whatsapp/{order.review_token}/')
        self.assertEqual(response.status_code, 404)
