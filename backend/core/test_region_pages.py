"""Allow-listed region pages (/games/<game>/<category>/<region>, SEO fix #10):
the brand page with its Region filter pinned. Covers the region endpoint, the
"shop by region" row on the brand page, the region-priced title, the
region-pages feed the sitemap reads, seeding rows + copy from seo_copy.json,
and IndexNow treating region pages as pages of their own."""

import json
import tempfile
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from . import indexnow
from .models import (
    Category, CategoryOption, CategoryRegionPage, Filter, FilterOption, Game,
    GameCategory, GameCategoryFilter, Listing,
)


class RegionPageFixture(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.seller = User.objects.create_user(username='regionseller', password='password123')
        self.game = Game.objects.create(name='PlayStation', slug='playstation')
        self.category = Category.objects.create(name='Gift Cards', slug='gift-cards')
        self.gc = GameCategory.objects.create(
            game=self.game, category=self.category, listing_mode='offer',
        )
        self.region_filter = Filter.objects.create(name='Region', filter_type='dropdown')
        self.usa = FilterOption.objects.create(filter=self.region_filter, label='USA', value='usa')
        self.uk = FilterOption.objects.create(
            filter=self.region_filter, label='United Kingdom', value='united-kingdom')
        self.turkiye = FilterOption.objects.create(
            filter=self.region_filter, label='Turkiye', value='turkiye')
        GameCategoryFilter.objects.create(
            game_category=self.gc, filter=self.region_filter, require_selection=True)
        self.fid = str(self.region_filter.id)

        self.option_usa = CategoryOption.objects.create(
            game_category=self.gc, name='10 USD (USA)', order=0)
        self.option_uk = CategoryOption.objects.create(
            game_category=self.gc, name='20 GBP (United Kingdom)', order=1)

        self.usa_cheap = self.make_offer(self.option_usa, 'usa', '3000.00')
        self.usa_dear = self.make_offer(self.option_usa, 'usa', '5000.00')
        self.uk_offer = self.make_offer(self.option_uk, 'united-kingdom', '4000.00')

        self.page_usa = CategoryRegionPage.objects.create(
            game_category=self.gc, region='usa', order=0)
        self.page_uk = CategoryRegionPage.objects.create(
            game_category=self.gc, region='united-kingdom', order=1)
        self.page_turkiye = CategoryRegionPage.objects.create(
            game_category=self.gc, region='turkiye', order=2)

    def make_offer(self, option, region, price, status='active'):
        return Listing.objects.create(
            seller=self.seller,
            game_category=self.gc,
            option=option,
            title=option.name,
            price=Decimal(price),
            status=status,
            filter_values={self.fid: region},
        )


class RegionPageApiTests(RegionPageFixture):

    def test_region_page_pins_the_region_filter(self):
        response = self.client.get('/api/games/playstation/gift-cards/usa/')

        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual(data['applied_filters'], {self.fid: 'usa'})
        self.assertEqual([opt['name'] for opt in data['options']], ['10 USD (USA)'])
        self.assertEqual(data['options'][0]['min_price'], '3000.00')
        self.assertEqual(data['region_page'], {
            'region': 'usa',
            'label': 'USA',
            'filter_id': self.region_filter.id,
            'path': '/games/playstation/gift-cards/usa',
            'brand_path': '/games/playstation/gift-cards',
        })
        self.assertEqual(data['region_listing_count'], 2)
        # Every offer shown belongs to the region.
        self.assertEqual([l['id'] for l in data['listings']],
                         [self.usa_cheap.id, self.usa_dear.id])
        # Brand-level plumbing is untouched.
        self.assertEqual(data['category']['slug'], 'gift-cards')
        self.assertEqual([c['slug'] for c in data['all_categories']], ['gift-cards'])

    def test_region_page_title_is_priced_from_that_region(self):
        self.gc.seo_title = 'PSN Gift Cards in Pakistan from PKR {from_price}'
        self.gc.seo_description = 'Brand description'
        self.gc.seo_body = '## Brand body'
        self.gc.save()
        self.page_uk.seo_title = 'PSN UK Gift Cards from PKR {from_price}'
        self.page_uk.seo_description = 'UK description'
        self.page_uk.seo_body = '## UK body'
        self.page_uk.save()
        # The brand's cheapest card is a USA one; the UK page must not use it.
        brand = self.client.get('/api/games/playstation/gift-cards/').data
        uk = self.client.get('/api/games/playstation/gift-cards/united-kingdom/').data

        self.assertEqual(brand['seo_title'], 'PSN Gift Cards in Pakistan from PKR 3,000')
        self.assertEqual(uk['seo_title'], 'PSN UK Gift Cards from PKR 4,000')
        self.assertEqual(uk['seo_description'], 'UK description')
        self.assertEqual(uk['seo_body'], '## UK body')
        # Brand copy stays on the brand page only.
        self.assertEqual(brand['seo_description'], 'Brand description')

    def test_region_page_without_copy_gets_a_default_priced_title(self):
        data = self.client.get('/api/games/playstation/gift-cards/usa/').data

        self.assertEqual(data['seo_title'],
                         'PlayStation Gift Cards USA in Pakistan from PKR 3,000')
        self.assertEqual(data['seo_description'], '')
        self.assertEqual(data['seo_body'], '')

    def test_empty_region_page_reports_zero_stock_and_drops_the_price(self):
        data = self.client.get('/api/games/playstation/gift-cards/turkiye/').data

        self.assertEqual(data['region_listing_count'], 0)
        self.assertEqual(data['options'], [])
        self.assertEqual(data['listings'], [])
        self.assertEqual(data['seo_title'], 'PlayStation Gift Cards Turkiye in Pakistan')

    def test_regions_off_the_allow_list_are_404(self):
        # An option that exists but has no row.
        FilterOption.objects.create(filter=self.region_filter, label='India', value='india')
        self.assertEqual(
            self.client.get('/api/games/playstation/gift-cards/india/').status_code, 404)
        # A row whose region is no longer an option on the filter.
        CategoryRegionPage.objects.create(game_category=self.gc, region='mars')
        self.assertEqual(
            self.client.get('/api/games/playstation/gift-cards/mars/').status_code, 404)
        # Unknown page.
        self.assertEqual(
            self.client.get('/api/games/playstation/keys/usa/').status_code, 404)

    def test_query_params_cannot_unpin_the_region(self):
        response = self.client.get(
            f'/api/games/playstation/gift-cards/usa/'
            f'?filter_{self.fid}=united-kingdom&region=united-kingdom')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['applied_filters'], {self.fid: 'usa'})
        self.assertEqual([opt['name'] for opt in response.data['options']],
                         ['10 USD (USA)'])

    def test_brand_page_lists_its_region_pages_with_stock_counts(self):
        data = self.client.get('/api/games/playstation/gift-cards/').data

        self.assertNotIn('region_page', data)
        self.assertNotIn('region_listing_count', data)
        self.assertEqual(data['region_pages'], [
            {'region': 'usa', 'label': 'USA',
             'path': '/games/playstation/gift-cards/usa', 'listing_count': 2},
            {'region': 'united-kingdom', 'label': 'United Kingdom',
             'path': '/games/playstation/gift-cards/united-kingdom', 'listing_count': 1},
            {'region': 'turkiye', 'label': 'Turkiye',
             'path': '/games/playstation/gift-cards/turkiye', 'listing_count': 0},
        ])
        # The region page carries the same row so buyers can hop regions.
        usa = self.client.get('/api/games/playstation/gift-cards/usa/').data
        self.assertEqual(usa['region_pages'], data['region_pages'])

    def test_pages_without_region_rows_send_an_empty_row(self):
        CategoryRegionPage.objects.all().delete()
        data = self.client.get('/api/games/playstation/gift-cards/').data
        self.assertEqual(data['region_pages'], [])
        self.assertEqual(
            self.client.get('/api/games/playstation/gift-cards/usa/').status_code, 404)

    def test_brand_page_query_region_is_still_just_a_filter(self):
        # ?region= on the brand page keeps working as the ad-landing filter
        # and never turns into a region page.
        data = self.client.get('/api/games/playstation/gift-cards/?region=usa').data
        self.assertEqual(data['applied_filters'], {self.fid: 'usa'})
        self.assertNotIn('region_page', data)

    def test_brand_and_region_responses_are_cached_apart(self):
        brand = self.client.get('/api/games/playstation/gift-cards/').data
        region = self.client.get('/api/games/playstation/gift-cards/usa/').data
        brand_again = self.client.get('/api/games/playstation/gift-cards/').data

        self.assertNotIn('region_page', brand)
        self.assertEqual(region['region_page']['region'], 'usa')
        self.assertNotIn('region_page', brand_again)

    def test_renamed_category_answers_at_both_slugs_with_the_display_path(self):
        self.gc.display_name = 'PSN Cards'
        self.gc.save()

        new_slug = self.client.get('/api/games/playstation/psn-cards/usa/')
        old_slug = self.client.get('/api/games/playstation/gift-cards/usa/')

        self.assertEqual(new_slug.status_code, 200)
        self.assertEqual(old_slug.status_code, 200)
        self.assertEqual(new_slug.data['region_page']['path'],
                         '/games/playstation/psn-cards/usa')
        self.assertEqual(old_slug.data['category']['slug'], 'psn-cards')

    def test_region_pages_feed_lists_every_row_with_stock(self):
        response = self.client.get('/api/region-pages/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [
            {'game_slug': 'playstation', 'category_slug': 'gift-cards',
             'region': 'usa', 'label': 'USA',
             'path': '/games/playstation/gift-cards/usa', 'listing_count': 2},
            {'game_slug': 'playstation', 'category_slug': 'gift-cards',
             'region': 'united-kingdom', 'label': 'United Kingdom',
             'path': '/games/playstation/gift-cards/united-kingdom', 'listing_count': 1},
            {'game_slug': 'playstation', 'category_slug': 'gift-cards',
             'region': 'turkiye', 'label': 'Turkiye',
             'path': '/games/playstation/gift-cards/turkiye', 'listing_count': 0},
        ])

    def test_region_pages_feed_skips_hidden_games(self):
        self.game.is_active = False
        self.game.save()
        self.assertEqual(self.client.get('/api/region-pages/').data, [])


class RegionPageSeedTests(RegionPageFixture):
    """seed_seo_text entries with a "region" key create the allow-list row."""

    def setUp(self):
        super().setUp()
        CategoryRegionPage.objects.all().delete()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def run_command(self, pages, **options):
        path = Path(self.tmpdir.name) / 'seo_copy.json'
        path.write_text(json.dumps({'pages': pages}), encoding='utf-8')
        out = StringIO()
        call_command('seed_seo_text', file=str(path), stdout=out, **options)
        return out.getvalue()

    def test_region_entry_creates_the_row_with_its_copy(self):
        output = self.run_command([{
            'game': 'playstation', 'category': 'gift-cards', 'region': 'usa',
            'order': 3,
            'seo_title': 'PSN USA Gift Cards in Pakistan from PKR {from_price}',
            'seo_description': 'US-region PSN cards.',
            'seo_body': '## USA cards\n\nSee the [UK page](/games/playstation/gift-cards/united-kingdom) too.',
        }, {
            'game': 'playstation', 'category': 'gift-cards', 'region': 'united-kingdom',
            'seo_title': 'PSN UK Gift Cards',
        }])

        self.assertIn('created region page playstation/gift-cards/usa', output)
        self.assertIn('2 region page(s) created', output)
        row = CategoryRegionPage.objects.get(game_category=self.gc, region='usa')
        self.assertEqual(row.order, 3)
        self.assertEqual(row.seo_title, 'PSN USA Gift Cards in Pakistan from PKR {from_price}')
        self.assertEqual(row.seo_description, 'US-region PSN cards.')
        self.assertTrue(row.seo_body.startswith('## USA cards'))

        data = self.client.get('/api/games/playstation/gift-cards/usa/').data
        self.assertEqual(data['seo_title'], 'PSN USA Gift Cards in Pakistan from PKR 3,000')

        # Second run: nothing to do; a changed title is an update, not a create.
        self.assertIn('0 updated, 2 unchanged', self.run_command([
            {'game': 'playstation', 'category': 'gift-cards', 'region': 'usa',
             'order': 3,
             'seo_title': 'PSN USA Gift Cards in Pakistan from PKR {from_price}',
             'seo_description': 'US-region PSN cards.',
             'seo_body': '## USA cards\n\nSee the [UK page](/games/playstation/gift-cards/united-kingdom) too.'},
            {'game': 'playstation', 'category': 'gift-cards', 'region': 'united-kingdom',
             'seo_title': 'PSN UK Gift Cards'},
        ]))
        self.assertIn('1 updated', self.run_command([
            {'game': 'playstation', 'category': 'gift-cards', 'region': 'usa',
             'seo_title': 'New title'},
        ]))
        self.assertEqual(CategoryRegionPage.objects.count(), 2)

    def test_region_must_be_an_option_on_the_pages_region_filter(self):
        output = self.run_command([
            {'game': 'playstation', 'category': 'gift-cards', 'region': 'mars',
             'seo_title': 'Mars'},
            {'game': 'playstation', 'category': 'keys', 'region': 'usa',
             'seo_title': 'Keys USA'},
        ])

        self.assertEqual(CategoryRegionPage.objects.count(), 0)
        self.assertIn('2 page(s) not found', output)
        self.assertIn("playstation/gift-cards/mars (region is not an option on the "
                      "page's Region filter)", output)
        self.assertIn('playstation/keys/usa (page not found)', output)

    def test_dry_run_creates_nothing_but_accepts_links_to_declared_pages(self):
        output = self.run_command([
            {'game': 'playstation', 'category': 'gift-cards',
             'seo_body': 'Shop [USA cards](/games/playstation/gift-cards/usa).'},
            {'game': 'playstation', 'category': 'gift-cards', 'region': 'usa',
             'seo_title': 'USA'},
        ], dry_run=True)

        self.assertIn('would create region page playstation/gift-cards/usa', output)
        self.assertIn('would update playstation/gift-cards: seo_body', output)
        self.assertIn('0 page(s) skipped for dead links', output)
        self.assertEqual(CategoryRegionPage.objects.count(), 0)
        self.gc.refresh_from_db()
        self.assertEqual(self.gc.seo_body, '')

    def test_links_to_region_pages_that_will_not_exist_are_dead(self):
        output = self.run_command([
            {'game': 'playstation', 'category': 'gift-cards',
             'seo_body': 'Shop [India cards](/games/playstation/gift-cards/india).'},
            # Declared but unresolvable: still not a valid link target.
            {'game': 'playstation', 'category': 'gift-cards', 'region': 'usa',
             'seo_body': 'See [Mars](/games/playstation/gift-cards/mars).'},
            {'game': 'playstation', 'category': 'gift-cards', 'region': 'mars',
             'seo_title': 'Mars'},
        ])

        self.assertIn('2 page(s) skipped for dead links', output)
        self.assertIn('playstation/gift-cards: /games/playstation/gift-cards/india', output)
        self.assertIn('playstation/gift-cards/usa: /games/playstation/gift-cards/mars', output)
        self.assertEqual(CategoryRegionPage.objects.count(), 0)

    def test_duplicate_region_entries_are_rejected(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self.run_command([
                {'game': 'playstation', 'category': 'gift-cards', 'region': 'usa'},
                {'game': 'playstation', 'category': 'gift-cards', 'region': 'usa'},
            ])
        # A brand entry and a region entry for the same page are different keys.
        self.run_command([
            {'game': 'playstation', 'category': 'gift-cards', 'seo_title': 'Brand'},
            {'game': 'playstation', 'category': 'gift-cards', 'region': 'usa',
             'seo_title': 'USA'},
        ])
        self.assertEqual(CategoryRegionPage.objects.count(), 1)


def accepted():
    response = Mock()
    response.status_code = 200
    response.text = ''
    return response


@override_settings(INDEXNOW_KEY='testkey123', PUBLIC_SITE_URL='https://www.example.pk')
class RegionPageIndexNowTests(RegionPageFixture):

    def test_catch_up_push_includes_stocked_region_pages_only(self):
        urls = indexnow.indexable_category_page_urls()

        self.assertIn('https://www.example.pk/games/playstation/gift-cards', urls)
        self.assertIn('https://www.example.pk/games/playstation/gift-cards/usa', urls)
        self.assertIn('https://www.example.pk/games/playstation/gift-cards/united-kingdom', urls)
        self.assertNotIn('https://www.example.pk/games/playstation/gift-cards/turkiye', urls)

    def test_a_changed_listing_pings_its_region_page_too(self):
        for listing in (self.usa_dear, self.uk_offer):
            Listing.objects.filter(pk=listing.pk).update(
                updated_at=timezone.now() - timedelta(days=3))
        Listing.objects.filter(pk=self.usa_cheap.pk).update(updated_at=timezone.now())

        category_urls, listing_urls = indexnow.changed_pages_since(
            timezone.now() - timedelta(hours=1))

        self.assertEqual(category_urls, [
            'https://www.example.pk/games/playstation/gift-cards',
            'https://www.example.pk/games/playstation/gift-cards/usa',
        ])
        self.assertEqual(listing_urls, [f'https://www.example.pk/listing/{self.usa_cheap.pk}'])

    def test_paths_submission_accepts_region_page_paths(self):
        with patch('core.indexnow.requests.post', return_value=accepted()) as post:
            out = StringIO()
            call_command('indexnow_ping', '--paths',
                         '/games/playstation/gift-cards/usa', stdout=out)
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['urlList'],
                         ['https://www.example.pk/games/playstation/gift-cards/usa'])
        self.assertIn('Submitted 1 URL(s).', out.getvalue())
