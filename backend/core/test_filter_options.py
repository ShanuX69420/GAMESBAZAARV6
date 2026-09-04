"""Stock-aware filter options on the game+category page (Shayan 2026-09-05:
after the top-up / gift-card retirements the Region dropdown on brand pages
kept listing Germany, Malaysia, Singapore... as choices that returned
nothing). Buyers are only offered options at least one active listing on the
page carries; the sell form still gets everything; a selection the buyer
already made stays pickable."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from .filter_options import stocked_filter_values, trim_filters_to_stock
from .models import (
    Category, CategoryRegionPage, Filter, FilterOption, Game, GameCategory,
    GameCategoryFilter, Listing,
)


class StockAwareFilterOptionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.seller = User.objects.create_user(username='optionseller', password='password123')
        game = Game.objects.create(name='Roblox', slug='roblox')
        category = Category.objects.create(name='Gift Cards', slug='gift-cards')
        self.page = GameCategory.objects.create(game=game, category=category)

        self.region = Filter.objects.create(name='Region', filter_type='dropdown')
        for label, value in (('USA', 'usa'), ('Germany', 'germany'),
                             ('Malaysia', 'malaysia'), ('Global', 'global')):
            FilterOption.objects.create(filter=self.region, label=label, value=value)
        self.platform = Filter.objects.create(name='Platform', filter_type='dropdown')
        FilterOption.objects.create(filter=self.platform, label='PC', value='pc')
        GameCategoryFilter.objects.create(game_category=self.page, filter=self.region)
        GameCategoryFilter.objects.create(game_category=self.page, filter=self.platform)
        self.rid = str(self.region.id)

        self.add_listing('USA card', {self.rid: 'usa'})
        self.add_listing('Global card', {self.rid: 'global'})
        self.add_listing('Bare card', {})
        # Off listings don't count: the only Germany card is out of stock.
        self.add_listing('Germany card', {self.rid: 'germany'}, status='inactive')

    def tearDown(self):
        cache.clear()

    def add_listing(self, title, filter_values, status='active'):
        return Listing.objects.create(
            seller=self.seller, game_category=self.page, title=title,
            price=Decimal('10.00'), quantity=1, status=status,
            filter_values=filter_values)

    def browse(self, suffix=''):
        response = self.client.get(f'/api/games/roblox/gift-cards/{suffix}')
        self.assertEqual(response.status_code, 200)
        return response.data, {f['id']: f for f in response.data['filters']}

    def region_values(self, by_id):
        return [option['value'] for option in by_id[self.region.id]['options']]

    def test_only_stocked_options_are_offered(self):
        _, by_id = self.browse()

        # Priority order (Global first) survives the trim.
        self.assertEqual(self.region_values(by_id), ['global', 'usa'])
        # A filter no active listing fills at all is left out entirely.
        self.assertNotIn(self.platform.id, by_id)

    def test_options_come_back_with_stock(self):
        self.add_listing('Malaysia card', {self.rid: 'malaysia'})
        Listing.objects.filter(title='Germany card').update(status='active')
        self.add_listing('PC thing', {str(self.platform.id): 'pc'})

        _, by_id = self.browse()

        self.assertEqual(self.region_values(by_id), ['global', 'usa', 'germany', 'malaysia'])
        self.assertEqual([o['value'] for o in by_id[self.platform.id]['options']], ['pc'])

    def test_sell_form_still_gets_every_option(self):
        _, by_id = self.browse('?all_options=1')

        self.assertEqual(self.region_values(by_id), ['global', 'usa', 'germany', 'malaysia'])
        self.assertEqual([o['value'] for o in by_id[self.platform.id]['options']], ['pc'])

    def test_a_dead_value_the_buyer_picked_stays_listed(self):
        data, by_id = self.browse(f'?filter_{self.rid}=germany')

        # The dropdown shows "Germany" over the empty state, not "All Region".
        self.assertEqual(self.region_values(by_id), ['global', 'usa', 'germany'])
        self.assertEqual(data['listings'], [])

    def test_ad_landing_on_a_dead_region_arrives_unfiltered(self):
        data, by_id = self.browse('?region=germany')

        self.assertEqual(data['applied_filters'], {})
        self.assertEqual(sorted(l['title'] for l in data['listings']),
                         ['Bare card', 'Global card', 'USA card'])
        self.assertEqual(self.region_values(by_id), ['global', 'usa'])

    def test_ad_landing_on_a_stocked_region_still_applies(self):
        data, by_id = self.browse('?region=usa')

        self.assertEqual(data['applied_filters'], {self.rid: 'usa'})
        self.assertEqual([l['title'] for l in data['listings']], ['USA card'])
        self.assertEqual(self.region_values(by_id), ['global', 'usa'])

    def test_region_page_keeps_its_pinned_region_listed(self):
        CategoryRegionPage.objects.create(game_category=self.page, region='germany')

        data, by_id = self.browse('germany/')

        self.assertEqual(data['applied_filters'], {self.rid: 'germany'})
        self.assertEqual(data['region_listing_count'], 0)
        # Pinned region stays so the dropdown reads "Germany"; the rest of the
        # list is the stocked regions the buyer can hop to.
        self.assertEqual(self.region_values(by_id), ['global', 'usa', 'germany'])

    def test_helpers(self):
        self.assertEqual(stocked_filter_values(self.page), {self.rid: {'usa', 'global'}})

        payload = [
            {'id': 1, 'name': 'Region', 'options': [
                {'value': 'usa', 'label': 'USA'}, {'value': 'germany', 'label': 'Germany'}]},
            {'id': 2, 'name': 'Platform', 'options': [{'value': 'pc', 'label': 'PC'}]},
        ]
        self.assertEqual(
            trim_filters_to_stock(payload, {'1': {'usa'}}),
            [{'id': 1, 'name': 'Region', 'options': [{'value': 'usa', 'label': 'USA'}]}])
        self.assertEqual(
            trim_filters_to_stock(payload, {'1': {'usa'}}, keep={'1': 'germany'})[0]['options'],
            [{'value': 'usa', 'label': 'USA'}, {'value': 'germany', 'label': 'Germany'}])
        # A kept value that isn't an option at all changes nothing.
        self.assertEqual(
            trim_filters_to_stock(payload, {'1': {'usa'}}, keep={'1': 'mars', '2': 'pc'}),
            [{'id': 1, 'name': 'Region', 'options': [{'value': 'usa', 'label': 'USA'}]},
             {'id': 2, 'name': 'Platform', 'options': [{'value': 'pc', 'label': 'PC'}]}])
        # The payload passed in is not mutated.
        self.assertEqual(len(payload[0]['options']), 2)
