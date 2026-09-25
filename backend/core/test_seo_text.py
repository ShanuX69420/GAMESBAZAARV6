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

from .models import Category, CategoryOption, Game, GameCategory, Listing


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

    def test_token_filled_with_the_exact_cheapest_active_price(self):
        self.add_listing('8499.00')
        self.add_listing('12000.00')
        self.assertEqual(
            self.get_seo_title(),
            'Buy PUBG Mobile UC in Pakistan from PKR 8,499 — Top-Up',
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


class DefaultPriceTitleTests(TestCase):
    """Keys and accounts pages without hand-written copy get a generated
    "<Game> <Category> in Pakistan from PKR X" title (pilot rolled out
    sitewide 2026-09-03). Other categories keep the frontend fallback."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.seller = User.objects.create_user(username='dseller', password='pw12345678')
        self.game = Game.objects.create(name='Elden Ring', slug='elden-ring')
        self.keys = Category.objects.create(name='Keys', slug='keys')
        self.accounts = Category.objects.create(name='Accounts', slug='accounts')
        self.gift_cards = Category.objects.create(name='Gift Cards', slug='gift-cards')

    def page(self, category, **fields):
        return GameCategory.objects.create(game=self.game, category=category, **fields)

    def add_listing(self, game_category, price, status='active'):
        return Listing.objects.create(
            seller=self.seller, game_category=game_category,
            title=f'{price} listing', price=Decimal(price), status=status,
        )

    def get_seo_title(self, slug):
        response = self.client.get(f'/api/games/elden-ring/{slug}/')
        self.assertEqual(response.status_code, 200)
        return response.data['seo_title']

    def test_keys_page_without_copy_gets_a_priced_title(self):
        page = self.page(self.keys)
        self.add_listing(page, '5499.00')
        self.add_listing(page, '8000.00')
        self.assertEqual(self.get_seo_title('keys'), 'Elden Ring Keys in Pakistan from PKR 5,499')

    def test_accounts_page_uses_the_per_game_display_name(self):
        page = self.page(self.accounts, display_name='Steam Accounts')
        self.add_listing(page, '12100.00')
        self.assertEqual(
            self.get_seo_title('accounts'),
            'Elden Ring Steam Accounts in Pakistan from PKR 12,100',
        )

    def test_other_categories_keep_the_frontend_fallback(self):
        page = self.page(self.gift_cards)
        self.add_listing(page, '900.00')
        self.assertEqual(self.get_seo_title('gift-cards'), '')

    def test_no_stock_drops_the_price_phrase(self):
        page = self.page(self.keys)
        self.add_listing(page, '5000.00', status='inactive')
        self.assertEqual(self.get_seo_title('keys'), 'Elden Ring Keys in Pakistan')

    def test_hand_written_title_still_wins(self):
        page = self.page(self.keys, seo_title='Buy Elden Ring in Pakistan')
        self.add_listing(page, '5000.00')
        self.assertEqual(self.get_seo_title('keys'), 'Buy Elden Ring in Pakistan')



class PriceListTokenTests(TestCase):
    """{price_table} in seo_body and {price_list} in seo_description, filled
    per-response from the offer tiles (Search Console 2026-09-26: "1000 robux
    in pkr" / "1 uc to pkr" queries found nothing on the page answering them)."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.seller = User.objects.create_user(username='tseller', password='pw12345678')
        game = Game.objects.create(name='Roblox', slug='roblox')
        category = Category.objects.create(name='Robux', slug='robux')
        self.page = GameCategory.objects.create(
            game=game, category=category, listing_mode='offer',
            seo_description='{price_list}. Global codes, paid with JazzCash.',
            seo_body='## Robux to PKR price list\n\n{price_table}\n\n## FAQs',
        )
        self.order = 0

    def offer(self, name, price, status='active'):
        option = CategoryOption.objects.create(
            game_category=self.page, name=name, order=self.order)
        self.order += 1
        Listing.objects.create(
            seller=self.seller, game_category=self.page, option=option,
            title=name, price=Decimal(price), status=status,
        )
        return option

    def get(self):
        response = self.client.get('/api/games/roblox/robux/')
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_table_lists_every_pack_with_a_per_unit_price(self):
        self.offer('50 Robux (Global)', '320.00')
        self.offer('1000 Robux (Global)', '3530.00')
        self.offer('10000 Robux (Global)', '31300.00')
        self.offer('1000 Robux (USA)', '2950.00')

        self.assertEqual(self.get()['seo_body'], '\n'.join([
            '## Robux to PKR price list',
            '',
            '| Pack | Price | Per Robux |',
            '|---|---|---|',
            '| 50 Robux (Global) | PKR 320 | PKR 6.40 |',
            '| 1,000 Robux (Global) | PKR 3,530 | PKR 3.53 |',
            '| 10,000 Robux (Global) | PKR 31,300 | PKR 3.13 |',
            '| 1,000 Robux (USA) | PKR 2,950 | PKR 2.95 |',
            '',
            '## FAQs',
        ]))

    def test_a_named_region_lists_only_that_regions_packs(self):
        # Robux sells 44 packs over three regions; Shayan wanted Global only.
        self.page.seo_body = '{price_table:Global}'
        self.page.seo_description = '{price_list:global}. Global codes.'
        self.page.save(update_fields=['seo_body', 'seo_description'])
        self.offer('100 Robux (Global)', '510.00')
        self.offer('200 Robux (Russia)', '920.00')
        self.offer('1000 Robux (USA)', '2950.00')
        self.offer('1000 Robux (Global)', '3530.00')

        data = self.get()
        self.assertEqual(data['seo_body'], '\n'.join([
            '| Pack | Price | Per Robux |',
            '|---|---|---|',
            '| 100 Robux (Global) | PKR 510 | PKR 5.10 |',
            '| 1,000 Robux (Global) | PKR 3,530 | PKR 3.53 |',
        ]))
        self.assertEqual(data['seo_description'],
                         '100 Robux PKR 510 · 1,000 Robux PKR 3,530. Global codes.')

    def test_a_region_with_no_packs_leaves_the_empty_note(self):
        self.page.seo_body = '{price_table:Turkey}'
        self.page.save(update_fields=['seo_body'])
        self.offer('100 Robux (Global)', '510.00')

        self.assertEqual(self.get()['seo_body'], 'No packs are in stock right now.')

    def test_description_names_the_first_packs_once_per_amount(self):
        self.offer('50 Robux (Global)', '320.00')
        self.offer('100 Robux (Global)', '510.00')
        self.offer('100 Robux (USA)', '490.00')  # region twin of 100 Robux
        self.offer('800 Robux (Global)', '2890.00')
        self.offer('1000 Robux (Global)', '3530.00')
        self.offer('2000 Robux (Global)', '7060.00')  # past the limit of four

        self.assertEqual(
            self.get()['seo_description'],
            '50 Robux PKR 320 · 100 Robux PKR 510 · 800 Robux PKR 2,890 · '
            '1,000 Robux PKR 3,530. Global codes, paid with JazzCash.',
        )

    def test_packs_without_an_active_offer_are_left_out(self):
        self.offer('50 Robux (Global)', '320.00', status='inactive')
        self.offer('100 Robux (Global)', '510.00')

        data = self.get()
        self.assertNotIn('50 Robux', data['seo_body'])
        self.assertIn('| 100 Robux (Global) | PKR 510 | PKR 5.10 |', data['seo_body'])
        self.assertTrue(data['seo_description'].startswith('100 Robux PKR 510. '))

    def test_mixed_packs_get_no_per_unit_column(self):
        self.offer('10 USD', '2900.00')
        self.offer('Premium 1 Month', '1500.00')

        body = self.get()['seo_body']
        self.assertIn('| Pack | Price |\n|---|---|\n| 10 USD | PKR 2,900 |', body)
        self.assertNotIn('Per ', body)

    def test_no_stock_leaves_a_note_and_drops_the_list(self):
        self.offer('50 Robux (Global)', '320.00', status='inactive')

        data = self.get()
        self.assertIn('No packs are in stock right now.', data['seo_body'])
        self.assertNotIn('{price_table}', data['seo_body'])
        self.assertEqual(data['seo_description'], 'Global codes, paid with JazzCash.')

    def test_standard_pages_have_no_tiles_so_tokens_resolve_empty(self):
        self.page.listing_mode = 'standard'
        self.page.save(update_fields=['listing_mode'])
        self.offer('50 Robux (Global)', '320.00')

        data = self.get()
        self.assertNotIn('{price', data['seo_body'] + data['seo_description'])

    def test_copy_without_tokens_is_untouched(self):
        self.page.seo_description = 'Plain description.'
        self.page.seo_body = '## Plain body'
        self.page.save(update_fields=['seo_description', 'seo_body'])
        self.offer('50 Robux (Global)', '320.00')

        data = self.get()
        self.assertEqual(data['seo_description'], 'Plain description.')
        self.assertEqual(data['seo_body'], '## Plain body')
