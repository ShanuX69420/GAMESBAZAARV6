"""Listing lifecycle (SEO fix #1, 2026-09-02): what a listing's URL does once
the listing stops selling — out-of-stock page, redirect to the heir, or 404.
See core/listing_lifecycle.py for the rules under test."""

import json
import tempfile
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .listing_lifecycle import PAUSE_DAYS
from .models import Category, CategoryOption, Game, GameCategory, Listing, RetiredListing


class ListingLifecycleTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.seller = User.objects.create_user(username='lifeseller', password='password123')
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])
        self.buyer = User.objects.create_user(username='lifebuyer', password='password123')
        self.staff = User.objects.create_user(
            username='lifestaff', password='password123', is_staff=True,
        )

        self.game = Game.objects.create(name='Lifecycle Game', slug='lifecycle-game')
        self.keys = Category.objects.create(name='Keys', slug='keys')
        self.gift_cards = Category.objects.create(name='Gift Cards', slug='gift-cards')
        self.keys_page = GameCategory.objects.create(game=self.game, category=self.keys)
        self.cards_page = GameCategory.objects.create(
            game=self.game, category=self.gift_cards, listing_mode='offer',
        )
        self.option_small = CategoryOption.objects.create(
            game_category=self.cards_page, name='5 USD', order=0,
        )
        self.option_big = CategoryOption.objects.create(
            game_category=self.cards_page, name='10 USD', order=1,
        )

    def make_listing(self, title='Lifecycle Game (PC) | Steam Key | Global', *,
                     status='active', page=None, option=None, price='100.00',
                     created_days_ago=0, off_days_ago=None, **fields):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=page or self.keys_page,
            option=option,
            title=title,
            price=Decimal(price),
            status=status,
            **fields,
        )
        # created_at is auto_now_add and unavailable_since is stamped by
        # save(); backdate both behind the model's back.
        now = timezone.now()
        backdate = {}
        if created_days_ago:
            backdate['created_at'] = now - timedelta(days=created_days_ago)
        if off_days_ago is not None:
            backdate['unavailable_since'] = now - timedelta(days=off_days_ago)
        if backdate:
            Listing.objects.filter(pk=listing.pk).update(**backdate)
            listing.refresh_from_db()
        return listing

    def get(self, listing_id, user=None):
        if user is not None:
            self.client.force_authenticate(user=user)
        else:
            self.client.force_authenticate(user=None)
        return self.client.get(f'/api/listings/{listing_id}/')


class ListingDetailLifecycleTests(ListingLifecycleTestCase):
    def test_active_listing_carries_the_active_state(self):
        listing = self.make_listing()

        response = self.get(listing.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'active')
        self.assertEqual(response.data['lifecycle'], {'state': 'active'})
        self.assertEqual(response.data['title'], listing.title)

    def test_recently_switched_off_listing_is_paused_and_lists_its_siblings(self):
        sibling = self.make_listing('Lifecycle Game Deluxe (PC) | Steam Key | Global', price='150.00')
        listing = self.make_listing(status='inactive', created_days_ago=20, off_days_ago=5)

        for user in (None, self.buyer):
            response = self.get(listing.pk, user=user)

            self.assertEqual(response.status_code, 200)
            # Same page, same title, same schema inputs — only the stock changed.
            self.assertEqual(response.data['title'], listing.title)
            self.assertEqual(response.data['status'], 'inactive')
            lifecycle = response.data['lifecycle']
            self.assertEqual(lifecycle['state'], 'paused')
            self.assertEqual(lifecycle['browse_path'], '/games/lifecycle-game/keys')
            self.assertIn('pause_ends_at', lifecycle)
            self.assertEqual(
                [alt['id'] for alt in lifecycle['alternatives']], [sibling.pk],
            )
            self.assertEqual(lifecycle['alternatives'][0]['price'], '150.00')

    def test_offer_mode_pause_shows_one_alternative_per_option_cheapest_first(self):
        listing = self.make_listing(
            '5 USD', page=self.cards_page, option=self.option_small,
            status='inactive', created_days_ago=20, off_days_ago=2,
        )
        self.make_listing('10 USD', page=self.cards_page, option=self.option_big, price='2000.00')
        cheaper = self.make_listing(
            '10 USD', page=self.cards_page, option=self.option_big, price='1800.00',
        )

        response = self.get(listing.pk)

        self.assertEqual(response.data['lifecycle']['state'], 'paused')
        self.assertEqual(response.data['lifecycle']['alternatives'], [{
            'id': cheaper.pk, 'title': '10 USD', 'price': '1800.00', 'option_name': '10 USD',
        }])

    def test_pause_runs_out_into_a_redirect_to_the_category_page(self):
        self.make_listing('Lifecycle Game Deluxe (PC) | Steam Key | Global')
        listing = self.make_listing(
            status='inactive', created_days_ago=90, off_days_ago=PAUSE_DAYS + 1,
        )

        response = self.get(listing.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {
            'id': listing.pk,
            'status': 'retired',
            'lifecycle': {
                'state': 'gone', 'reason': 'expired',
                'redirect_to': '/games/lifecycle-game/keys',
            },
        })

    def test_expired_listing_falls_back_to_busiest_page_then_section(self):
        listing = self.make_listing(
            status='inactive', created_days_ago=90, off_days_ago=PAUSE_DAYS + 5,
        )
        card = self.make_listing('5 USD', page=self.cards_page, option=self.option_small)

        # Its own page is empty; the game's only stocked page is gift cards.
        response = self.get(listing.pk)
        self.assertEqual(response.data['lifecycle']['redirect_to'], '/games/lifecycle-game/gift-cards')

        # Nothing left on the game at all: the keys section page.
        card.status = 'inactive'
        card.save(update_fields=['status'])
        response = self.get(listing.pk)
        self.assertEqual(response.data['lifecycle']['redirect_to'], '/keys')

    def test_permanent_reason_skips_the_pause(self):
        self.make_listing('Lifecycle Game Deluxe (PC) | Steam Key | Global')
        listing = self.make_listing(
            status='inactive', created_days_ago=30, off_days_ago=1, retire_reason='region_gone',
        )

        response = self.get(listing.pk)

        self.assertEqual(response.data['lifecycle'], {
            'state': 'gone', 'reason': 'region_gone',
            'redirect_to': '/games/lifecycle-game/keys',
        })

    def test_an_active_twin_takes_over_the_url_immediately(self):
        listing = self.make_listing(status='inactive', created_days_ago=30, off_days_ago=1)
        twin = self.make_listing(title=listing.title.upper(), price='90.00')

        response = self.get(listing.pk)
        self.assertEqual(response.data['lifecycle'], {
            'state': 'gone', 'reason': 'superseded', 'redirect_to': f'/listing/{twin.pk}',
        })

        # Offer mode: the twin is whoever sells the same option.
        card = self.make_listing(
            '5 USD', page=self.cards_page, option=self.option_small,
            status='inactive', created_days_ago=30, off_days_ago=1,
        )
        card_twin = self.make_listing('5 USD', page=self.cards_page, option=self.option_small)
        response = self.get(card.pk)
        self.assertEqual(response.data['lifecycle']['redirect_to'], f'/listing/{card_twin.pk}')

    def test_listing_off_within_a_day_of_creation_was_never_indexed(self):
        listing = self.make_listing(status='inactive')

        response = self.get(listing.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'retired')
        self.assertEqual(response.data['lifecycle']['state'], 'unindexed')
        self.assertIsNone(response.data['lifecycle']['redirect_to'])
        self.assertNotIn('title', response.data)

    def test_owner_and_staff_always_get_the_full_listing(self):
        listing = self.make_listing(
            status='inactive', created_days_ago=90, off_days_ago=PAUSE_DAYS + 1,
        )

        for user in (self.seller, self.staff):
            response = self.get(listing.pk, user=user)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['title'], listing.title)
            self.assertEqual(response.data['status'], 'inactive')
            self.assertEqual(response.data['lifecycle']['state'], 'gone')

    def test_unstamped_off_listing_is_stamped_on_first_view(self):
        listing = self.make_listing(created_days_ago=10)
        # A bulk update (what the price syncs do) skips save() and the stamp.
        Listing.objects.filter(pk=listing.pk).update(status='inactive')

        before = timezone.now()
        response = self.get(listing.pk)

        self.assertEqual(response.data['lifecycle']['state'], 'paused')
        listing.refresh_from_db()
        self.assertIsNotNone(listing.unavailable_since)
        self.assertGreaterEqual(listing.unavailable_since, before)

    def test_stale_stamp_on_a_revived_listing_is_cleared_on_view(self):
        listing = self.make_listing(
            status='inactive', created_days_ago=60, off_days_ago=40, retire_reason='game_gone',
        )
        Listing.objects.filter(pk=listing.pk).update(status='active')

        response = self.get(listing.pk)

        self.assertEqual(response.data['lifecycle'], {'state': 'active'})
        listing.refresh_from_db()
        self.assertIsNone(listing.unavailable_since)
        self.assertEqual(listing.retire_reason, '')

    def test_unknown_id_is_a_plain_404(self):
        response = self.get(987654321)
        self.assertEqual(response.status_code, 404)


class ListingAvailabilityStampTests(ListingLifecycleTestCase):
    def test_switching_off_stamps_even_with_update_fields(self):
        listing = self.make_listing()
        self.assertIsNone(listing.unavailable_since)

        listing.status = 'inactive'
        listing.save(update_fields=['status'])

        listing.refresh_from_db()
        self.assertEqual(listing.status, 'inactive')
        self.assertIsNotNone(listing.unavailable_since)

    def test_going_active_again_clears_stamp_and_reason(self):
        listing = self.make_listing(
            status='inactive', created_days_ago=30, off_days_ago=3, retire_reason='hand_retired',
        )

        listing.status = 'active'
        listing.save(update_fields=['status'])

        listing.refresh_from_db()
        self.assertIsNone(listing.unavailable_since)
        self.assertEqual(listing.retire_reason, '')

    def test_an_existing_stamp_is_kept_while_the_listing_stays_off(self):
        listing = self.make_listing(status='inactive', created_days_ago=30, off_days_ago=10)
        stamp = listing.unavailable_since

        listing.price = Decimal('120.00')
        listing.save()

        listing.refresh_from_db()
        self.assertEqual(listing.unavailable_since, stamp)


class RetiredListingTests(ListingLifecycleTestCase):
    def test_deleting_a_listing_leaves_a_redirect_behind(self):
        listing = self.make_listing(created_days_ago=10, filter_values={'7': 'global'})
        self.make_listing('Lifecycle Game Deluxe (PC) | Steam Key | Global')

        self.client.force_authenticate(user=self.seller)
        self.assertEqual(self.client.delete(f'/api/listings/{listing.pk}/').status_code, 204)

        record = RetiredListing.objects.get(pk=listing.pk)
        self.assertEqual(record.title, listing.title)
        self.assertEqual(record.game_slug, 'lifecycle-game')
        self.assertEqual(record.category_slug, 'keys')
        self.assertEqual(record.category_kind, 'keys')
        self.assertEqual(record.filter_values, {'7': 'global'})
        self.assertEqual(record.reason, 'deleted')
        self.assertEqual(record.heir_path, '')
        self.assertEqual(record.listing_created_at, listing.created_at)

        response = self.get(listing.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {
            'id': listing.pk,
            'status': 'retired',
            'lifecycle': {
                'state': 'gone', 'reason': 'deleted',
                'redirect_to': '/games/lifecycle-game/keys',
            },
        })

    def test_deleted_listing_redirect_is_worked_out_live(self):
        listing = self.make_listing(created_days_ago=10)
        listing_id, title = listing.pk, listing.title  # delete() blanks the pk
        sibling = self.make_listing('Lifecycle Game Deluxe (PC) | Steam Key | Global')
        listing.delete()

        # A twin seeded after the deletion takes the URL.
        twin = self.make_listing(title=title)
        self.assertEqual(self.get(listing_id).data['lifecycle']['redirect_to'], f'/listing/{twin.pk}')

        # With the twin gone the category page, and once that empties the section.
        twin.delete()
        self.assertEqual(self.get(listing_id).data['lifecycle']['redirect_to'], '/games/lifecycle-game/keys')
        sibling.delete()
        self.assertEqual(self.get(listing_id).data['lifecycle']['redirect_to'], '/keys')

        # A pinned heir wins over the live lookup.
        RetiredListing.objects.filter(pk=listing_id).update(heir_path='/gift-cards')
        self.assertEqual(self.get(listing_id).data['lifecycle']['redirect_to'], '/gift-cards')

    def test_deleting_the_whole_category_page_still_redirects_somewhere_live(self):
        listing = self.make_listing(created_days_ago=10)
        self.make_listing('5 USD', page=self.cards_page, option=self.option_small)

        self.keys_page.delete()

        response = self.get(listing.pk)
        self.assertEqual(response.data['lifecycle']['state'], 'gone')
        self.assertEqual(response.data['lifecycle']['redirect_to'], '/games/lifecycle-game/gift-cards')

    def test_bulk_delete_records_every_listing(self):
        ids = [self.make_listing(f'Bulk {n} (PC) | Steam Key | Global', created_days_ago=5).pk
               for n in range(3)]

        Listing.objects.filter(pk__in=ids).delete()

        self.assertEqual(
            set(RetiredListing.objects.filter(pk__in=ids).values_list('pk', flat=True)),
            set(ids),
        )

    def test_a_listing_deleted_within_a_day_of_creation_is_a_404_not_a_redirect(self):
        listing = self.make_listing()
        listing_id = listing.pk
        self.make_listing('Lifecycle Game Deluxe (PC) | Steam Key | Global')
        listing.delete()

        response = self.get(listing_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['lifecycle']['state'], 'unindexed')
        self.assertIsNone(response.data['lifecycle']['redirect_to'])

    def test_deleted_listing_keeps_its_permanent_reason(self):
        listing = self.make_listing(
            status='inactive', created_days_ago=30, off_days_ago=2, retire_reason='region_gone',
        )
        off_at = listing.unavailable_since
        listing_id = listing.pk

        listing.delete()

        record = RetiredListing.objects.get(pk=listing_id)
        self.assertEqual(record.reason, 'region_gone')
        self.assertEqual(record.active_until, off_at)


class LifecycleCommandTests(ListingLifecycleTestCase):
    def test_import_loads_the_map_and_skips_live_listings(self):
        live = self.make_listing()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'map.json'
            path.write_text(json.dumps({
                '/gift-cards': [900001, 900002],
                '/games/lifecycle-game/keys': [900003, live.pk],
            }), encoding='utf-8')

            out = StringIO()
            call_command('import_retired_listings', str(path),
                         '--retired-at', '2026-09-02T16:44:00+00:00', stdout=out)
            self.assertIn('3 record(s) created, 0 updated, 1 skipped', out.getvalue())

            out = StringIO()
            call_command('import_retired_listings', str(path), stdout=out)
            self.assertIn('0 record(s) created, 3 updated', out.getvalue())

        self.assertFalse(RetiredListing.objects.filter(pk=live.pk).exists())
        record = RetiredListing.objects.get(pk=900001)
        self.assertEqual(record.heir_path, '/gift-cards')
        self.assertEqual(record.reason, 'catalog_retired')
        self.assertEqual(record.retired_at.isoformat(), '2026-09-02T16:44:00+00:00')

        response = self.get(900003)
        self.assertEqual(response.data['lifecycle'], {
            'state': 'gone', 'reason': 'catalog_retired',
            'redirect_to': '/games/lifecycle-game/keys',
        })
        # The live listing was skipped, so its page is untouched.
        self.assertEqual(self.get(live.pk).data['lifecycle'], {'state': 'active'})

    def test_import_rejects_a_bad_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'map.json'
            path.write_text(json.dumps({'gift-cards': [1]}), encoding='utf-8')
            with self.assertRaises(CommandError):
                call_command('import_retired_listings', str(path))
            path.write_text(json.dumps({'/a': [1], '/b': [1]}), encoding='utf-8')
            with self.assertRaises(CommandError):
                call_command('import_retired_listings', str(path))

    def test_backfill_stamps_from_updated_at_and_clears_active_strays(self):
        off = self.make_listing(created_days_ago=40)
        stale = self.make_listing('Stale (PC) | Steam Key | Global', created_days_ago=40)
        Listing.objects.filter(pk=off.pk).update(
            status='inactive', updated_at=timezone.now() - timedelta(days=12),
        )
        Listing.objects.filter(pk=stale.pk).update(
            unavailable_since=timezone.now(), retire_reason='game_gone',
        )

        out = StringIO()
        call_command('listing_lifecycle', '--backfill', stdout=out)

        self.assertIn('Stamped 1 off listing(s)', out.getvalue())
        self.assertIn('cleared stale stamps on 1 active listing(s)', out.getvalue())
        off.refresh_from_db()
        stale.refresh_from_db()
        self.assertEqual(off.unavailable_since, off.updated_at)
        self.assertIsNone(stale.unavailable_since)
        self.assertEqual(stale.retire_reason, '')

    def test_set_reason_tags_off_listings_only(self):
        off = self.make_listing(status='inactive', created_days_ago=20, off_days_ago=3)
        live = self.make_listing('Live (PC) | Steam Key | Global')

        with self.assertRaises(CommandError):
            call_command('listing_lifecycle', '--set-reason', 'region_gone',
                         '--ids', f'{off.pk},{live.pk}')
        with self.assertRaises(CommandError):
            call_command('listing_lifecycle', '--set-reason', 'bogus', '--ids', str(off.pk))

        out = StringIO()
        call_command('listing_lifecycle', '--set-reason', 'region_gone',
                     '--ids', str(off.pk), stdout=out)

        self.assertIn('Tagged 1 listing(s) as region_gone', out.getvalue())
        off.refresh_from_db()
        self.assertEqual(off.retire_reason, 'region_gone')

    def test_report_lists_the_redirecting_pages(self):
        self.make_listing('Live (PC) | Steam Key | Global')
        paused = self.make_listing(status='inactive', created_days_ago=20, off_days_ago=3)
        expired = self.make_listing(
            'Old (PC) | Steam Key | Global', status='inactive',
            created_days_ago=90, off_days_ago=PAUSE_DAYS + 1,
        )
        never = self.make_listing('Never (PC) | Steam Key | Global', status='inactive')

        out = StringIO()
        call_command('listing_lifecycle', '--report', stdout=out)
        text = out.getvalue()
        self.assertIn('active 1  paused 1  gone 1  unindexed 1', text)
        self.assertIn(f'#{expired.pk}', text)
        self.assertIn('/games/lifecycle-game/keys', text)
        self.assertNotIn(f'#{paused.pk}', text)

        out = StringIO()
        call_command('listing_lifecycle', '--report', '--paths', stdout=out)
        self.assertEqual(
            out.getvalue().split(),
            [f'/listing/{expired.pk}', f'/listing/{never.pk}'],
        )

    def test_command_needs_an_action(self):
        with self.assertRaises(CommandError):
            call_command('listing_lifecycle')


class SitemapLifecycleTests(ListingLifecycleTestCase):
    def test_paused_listings_stay_out_of_the_sitemap(self):
        live = self.make_listing()
        paused = self.make_listing(
            'Paused (PC) | Steam Key | Global', status='inactive',
            created_days_ago=20, off_days_ago=3,
        )

        response = self.client.get('/api/sitemap/listings/')

        ids = [row['id'] for row in response.data['results']]
        self.assertIn(live.pk, ids)
        self.assertNotIn(paused.pk, ids)
