import json
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Category, Game, GameCategory, Listing


def write_copy_file(directory, pages):
    path = Path(directory) / 'seo_copy.json'
    path.write_text(json.dumps({'pages': pages}), encoding='utf-8')
    return str(path)


class SeedSeoTextTests(TestCase):
    """seed_seo_text command + the SEO fields riding the category endpoint."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.game = Game.objects.create(name='PUBG Mobile', slug='pubg-mobile')
        self.category = Category.objects.create(name='UC', slug='uc')
        self.game_category = GameCategory.objects.create(
            game=self.game, category=self.category,
        )
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def run_command(self, pages, **options):
        out = StringIO()
        call_command(
            'seed_seo_text',
            file=write_copy_file(self.tmpdir.name, pages),
            stdout=out,
            **options,
        )
        return out.getvalue()

    def test_seeds_fields_and_api_returns_them(self):
        self.run_command([{
            'game': 'pubg-mobile',
            'category': 'uc',
            'seo_title': 'Buy PUBG Mobile UC in Pakistan',
            'seo_description': 'UC top-ups with JazzCash at PKR prices.',
            'seo_body': '## Heading\n\nParagraph one.',
        }])

        self.game_category.refresh_from_db()
        self.assertEqual(self.game_category.seo_title, 'Buy PUBG Mobile UC in Pakistan')

        response = self.client.get('/api/games/pubg-mobile/uc/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['seo_title'], 'Buy PUBG Mobile UC in Pakistan')
        self.assertEqual(response.data['seo_description'],
                         'UC top-ups with JazzCash at PKR prices.')
        self.assertEqual(response.data['seo_body'], '## Heading\n\nParagraph one.')

    def test_rerun_is_idempotent_and_partial_entries_keep_other_fields(self):
        pages = [{
            'game': 'pubg-mobile',
            'category': 'uc',
            'seo_title': 'Title v1',
            'seo_body': 'Body v1',
        }]
        first = self.run_command(pages)
        self.assertIn('1 updated', first)

        second = self.run_command(pages)
        self.assertIn('0 updated, 1 unchanged', second)

        # An entry that only carries a title must not blank the stored body.
        self.run_command([{
            'game': 'pubg-mobile',
            'category': 'uc',
            'seo_title': 'Title v2',
        }])
        self.game_category.refresh_from_db()
        self.assertEqual(self.game_category.seo_title, 'Title v2')
        self.assertEqual(self.game_category.seo_body, 'Body v1')

    def test_resolves_display_slug_renames(self):
        # Free Fire renames "Top Ups" to "Diamonds"; the URL slug is the
        # display slug, and that's what the copy file uses.
        game = Game.objects.create(name='Free Fire', slug='free-fire')
        category = Category.objects.create(name='Top Ups', slug='top-ups')
        renamed = GameCategory.objects.create(
            game=game, category=category, display_name='Diamonds',
        )

        self.run_command([{
            'game': 'free-fire',
            'category': 'diamonds',
            'seo_title': 'Free Fire Diamonds in Pakistan',
        }])
        renamed.refresh_from_db()
        self.assertEqual(renamed.seo_title, 'Free Fire Diamonds in Pakistan')

    def test_unknown_page_is_reported_but_does_not_fail(self):
        output = self.run_command([
            {'game': 'pubg-mobile', 'category': 'uc', 'seo_title': 'Real page'},
            {'game': 'no-such-game', 'category': 'uc', 'seo_title': 'Ghost page'},
        ])
        self.assertIn('1 page(s) not found', output)
        self.assertIn('no-such-game/uc', output)
        self.game_category.refresh_from_db()
        self.assertEqual(self.game_category.seo_title, 'Real page')

    def test_overlong_field_fails_before_writing_anything(self):
        with self.assertRaises(CommandError):
            self.run_command([{
                'game': 'pubg-mobile',
                'category': 'uc',
                'seo_title': 'x' * 500,
            }])
        self.game_category.refresh_from_db()
        self.assertEqual(self.game_category.seo_title, '')

    def test_dry_run_writes_nothing(self):
        output = self.run_command(
            [{'game': 'pubg-mobile', 'category': 'uc', 'seo_title': 'Dry title'}],
            dry_run=True,
        )
        self.assertIn('would update', output)
        self.game_category.refresh_from_db()
        self.assertEqual(self.game_category.seo_title, '')


    def test_links_must_be_site_relative(self):
        for href in ('https://example.com/x', '//example.com/x', 'games/pubg-mobile/uc'):
            with self.assertRaises(CommandError):
                self.run_command([{
                    'game': 'pubg-mobile',
                    'category': 'uc',
                    'seo_body': f'See [the other page]({href}) too.',
                }])
        self.game_category.refresh_from_db()
        self.assertEqual(self.game_category.seo_body, '')

    def test_links_are_only_allowed_in_the_body(self):
        with self.assertRaises(CommandError):
            self.run_command([{
                'game': 'pubg-mobile',
                'category': 'uc',
                'seo_title': 'UC [here](/games/pubg-mobile/uc)',
            }])

    def test_link_to_a_missing_page_skips_that_page_until_fixed(self):
        pages = [{
            'game': 'pubg-mobile',
            'category': 'uc',
            'seo_title': 'UC title',
            'seo_body': 'Codes are on our [gift-cards page](/games/pubg-mobile/gift-cards).',
        }]
        output = self.run_command(pages)
        self.assertIn('1 page(s) skipped for dead links', output)
        self.assertIn('pubg-mobile/uc: /games/pubg-mobile/gift-cards', output)
        self.game_category.refresh_from_db()
        # Nothing on the page is written, not even the title, so the copy
        # goes live as one piece once the link is fixed.
        self.assertEqual(self.game_category.seo_title, '')
        self.assertEqual(self.game_category.seo_body, '')

        gift_cards = Category.objects.create(name='Gift Cards', slug='gift-cards')
        GameCategory.objects.create(game=self.game, category=gift_cards)
        output = self.run_command(pages)
        self.assertIn('1 updated', output)
        self.assertIn('0 page(s) skipped', output)
        self.game_category.refresh_from_db()
        self.assertEqual(self.game_category.seo_title, 'UC title')

    def test_links_resolve_display_slugs_game_pages_and_static_routes(self):
        game = Game.objects.create(name='Free Fire', slug='free-fire')
        category = Category.objects.create(name='Top Ups', slug='top-ups')
        GameCategory.objects.create(game=game, category=category, display_name='Diamonds')

        body = (
            'Pakistan server? Use the [Free Fire Diamonds page](/games/free-fire/diamonds), '
            'the [Free Fire hub](/games/free-fire) or browse [all top-ups](/top-ups).'
        )
        output = self.run_command([{
            'game': 'pubg-mobile', 'category': 'uc', 'seo_body': body,
        }])
        self.assertIn('1 updated', output)
        self.game_category.refresh_from_db()
        self.assertEqual(self.game_category.seo_body, body)

        # The API hands the markup through untouched; the frontend renders it.
        response = self.client.get('/api/games/pubg-mobile/uc/')
        self.assertEqual(response.data['seo_body'], body)


class FromPriceTitleTests(TestCase):
    """The "from PKR {from_price}" token in seo_title, filled per-response."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.seller = User.objects.create_user(username='pseller', password='pw12345678')
        game = Game.objects.create(name='PUBG Mobile', slug='pubg-mobile')
        category = Category.objects.create(name='UC', slug='uc')
        self.game_category = GameCategory.objects.create(
            game=game, category=category,
            seo_title='Buy PUBG Mobile UC in Pakistan from PKR {from_price} — Top-Up',
        )

    def add_listing(self, price, status='active'):
        return Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title=f'{price} pack',
            price=Decimal(price),
            status=status,
        )

    def get_seo_title(self):
        response = self.client.get('/api/games/pubg-mobile/uc/')
        self.assertEqual(response.status_code, 200)
        return response.data['seo_title']

    def test_token_filled_with_min_price_floored_to_two_significant_digits(self):
        self.add_listing('8499.00')
        self.add_listing('12000.00')
        self.assertEqual(
            self.get_seo_title(),
            'Buy PUBG Mobile UC in Pakistan from PKR 8,400 — Top-Up',
        )

    def test_small_prices_stay_exact(self):
        self.add_listing('87.00')
        self.assertEqual(
            self.get_seo_title(),
            'Buy PUBG Mobile UC in Pakistan from PKR 87 — Top-Up',
        )

    def test_inactive_listings_do_not_set_the_price(self):
        self.add_listing('100.00', status='inactive')
        self.add_listing('250.00')
        self.assertEqual(
            self.get_seo_title(),
            'Buy PUBG Mobile UC in Pakistan from PKR 250 — Top-Up',
        )

    def test_no_stock_drops_the_whole_price_phrase(self):
        self.add_listing('100.00', status='inactive')
        self.assertEqual(
            self.get_seo_title(),
            'Buy PUBG Mobile UC in Pakistan — Top-Up',
        )

    def test_title_without_token_is_untouched(self):
        self.game_category.seo_title = 'Buy PUBG Mobile UC in Pakistan'
        self.game_category.save(update_fields=['seo_title'])
        self.add_listing('250.00')
        self.assertEqual(self.get_seo_title(), 'Buy PUBG Mobile UC in Pakistan')
