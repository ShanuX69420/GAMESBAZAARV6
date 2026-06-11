from decimal import Decimal

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from .models import (
    Category, CategoryOption, Filter, FilterOption, Game, GameCategory,
    GameCategoryFilter, Listing,
)


class OfferModeTests(TestCase):
    """Offer-mode categories: admin-defined options with competing seller offers."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.seller = User.objects.create_user(username='offerseller', password='password123')
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])
        self.other_seller = User.objects.create_user(username='rivalseller', password='password123')
        self.other_seller.profile.seller_status = 'approved'
        self.other_seller.profile.save(update_fields=['seller_status'])

        self.game = Game.objects.create(name='PUBG Mobile', slug='pubg-mobile')
        self.category = Category.objects.create(name='UC', slug='uc')
        self.game_category = GameCategory.objects.create(
            game=self.game, category=self.category, listing_mode='offer',
        )
        self.option_small = CategoryOption.objects.create(
            game_category=self.game_category, name='60 UC', order=0,
        )
        self.option_popular = CategoryOption.objects.create(
            game_category=self.game_category, name='325 UC', order=1, is_popular=True,
        )

    def make_offer(self, seller, option, price, **kwargs):
        return Listing.objects.create(
            seller=seller,
            game_category=self.game_category,
            option=option,
            title=option.name,
            price=Decimal(price),
            status=kwargs.pop('status', 'active'),
            **kwargs,
        )

    def test_browse_returns_options_with_min_price_and_offer_count(self):
        self.make_offer(self.seller, self.option_small, '150.00')
        self.make_offer(self.other_seller, self.option_small, '120.00')
        self.make_offer(self.seller, self.option_small, '90.00', status='inactive')

        response = self.client.get('/api/games/pubg-mobile/uc/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['listing_mode'], 'offer')
        options = {opt['name']: opt for opt in response.data['options']}
        self.assertEqual(options['60 UC']['min_price'], '120.00')
        self.assertEqual(options['60 UC']['offer_count'], 2)
        self.assertIsNone(options['325 UC']['min_price'])
        self.assertEqual(options['325 UC']['offer_count'], 0)

    def test_browse_defaults_to_popular_option_and_scopes_listings(self):
        small_offer = self.make_offer(self.seller, self.option_small, '120.00')
        popular_offer = self.make_offer(self.seller, self.option_popular, '500.00')

        response = self.client.get('/api/games/pubg-mobile/uc/')

        self.assertEqual(response.data['selected_option_id'], self.option_popular.id)
        listing_ids = [listing['id'] for listing in response.data['listings']]
        self.assertEqual(listing_ids, [popular_offer.id])
        self.assertNotIn(small_offer.id, listing_ids)

    def test_browse_option_param_scopes_listings_cheapest_first(self):
        cheap = self.make_offer(self.seller, self.option_small, '99.00')
        pricey = self.make_offer(self.other_seller, self.option_small, '150.00')

        response = self.client.get(
            f'/api/games/pubg-mobile/uc/?option={self.option_small.id}'
        )

        self.assertEqual(response.data['selected_option_id'], self.option_small.id)
        listing_ids = [listing['id'] for listing in response.data['listings']]
        self.assertEqual(listing_ids, [cheap.id, pricey.id])
        self.assertEqual(response.data['listings'][0]['option_name'], '60 UC')

    def test_browse_invalid_option_param_falls_back_to_default(self):
        self.make_offer(self.seller, self.option_popular, '500.00')

        response = self.client.get('/api/games/pubg-mobile/uc/?option=999999')

        self.assertEqual(response.data['selected_option_id'], self.option_popular.id)

    def test_delivery_ordering_ranks_faster_delivery_first(self):
        slow = self.make_offer(self.seller, self.option_popular, '450.00',
                               delivery_time='1-3 Days')
        fast = self.make_offer(self.other_seller, self.option_popular, '500.00',
                               delivery_time='1-2 Hours')

        response = self.client.get(
            f'/api/games/pubg-mobile/uc/?option={self.option_popular.id}&ordering=delivery'
        )

        listing_ids = [listing['id'] for listing in response.data['listings']]
        self.assertEqual(listing_ids, [fast.id, slow.id])

    def test_standard_category_has_no_options_payload(self):
        standard_category = Category.objects.create(name='Accounts', slug='accounts')
        GameCategory.objects.create(game=self.game, category=standard_category)

        response = self.client.get('/api/games/pubg-mobile/accounts/')

        self.assertEqual(response.data['listing_mode'], 'standard')
        self.assertNotIn('options', response.data)
        self.assertNotIn('selected_option_id', response.data)

    def test_create_offer_requires_option_and_sets_title(self):
        self.client.force_authenticate(user=self.seller)

        missing = self.client.post('/api/listings/', {
            'game_slug': 'pubg-mobile',
            'category_slug': 'uc',
            'price': '120.00',
            'delivery_time': '1-2 Hours',
        }, format='json')
        self.assertEqual(missing.status_code, 400)

        created = self.client.post('/api/listings/', {
            'game_slug': 'pubg-mobile',
            'category_slug': 'uc',
            'option_id': self.option_small.id,
            'price': '120.00',
            'delivery_time': '1-2 Hours',
            'delivery_instructions': 'Send your Player ID. No password needed.',
        }, format='json')
        self.assertEqual(created.status_code, 201)
        listing = Listing.objects.get(seller=self.seller, option=self.option_small)
        self.assertEqual(listing.title, '60 UC')
        self.assertEqual(listing.status, 'active')

    def test_create_offer_requires_delivery_instructions(self):
        self.client.force_authenticate(user=self.seller)

        response = self.client.post('/api/listings/', {
            'game_slug': 'pubg-mobile',
            'category_slug': 'uc',
            'option_id': self.option_small.id,
            'price': '120.00',
            'delivery_time': '1-2 Hours',
            'delivery_instructions': '   ',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('delivery_instructions', response.data)

    def test_update_cannot_blank_offer_delivery_instructions(self):
        listing = self.make_offer(self.seller, self.option_small, '120.00',
                                  delivery_instructions='Send your Player ID.')
        self.client.force_authenticate(user=self.seller)

        blanked = self.client.put(f'/api/listings/{listing.id}/', {
            'delivery_instructions': '',
        }, format='json')
        self.assertEqual(blanked.status_code, 400)

        updated = self.client.put(f'/api/listings/{listing.id}/', {
            'delivery_instructions': 'Send your UID and stay logged out.',
        }, format='json')
        self.assertEqual(updated.status_code, 200)
        listing.refresh_from_db()
        self.assertEqual(listing.delivery_instructions, 'Send your UID and stay logged out.')

    def test_create_offer_rejects_duplicate_active_offer(self):
        self.make_offer(self.seller, self.option_small, '120.00')
        self.client.force_authenticate(user=self.seller)

        response = self.client.post('/api/listings/', {
            'game_slug': 'pubg-mobile',
            'category_slug': 'uc',
            'option_id': self.option_small.id,
            'price': '110.00',
            'delivery_time': '1-2 Hours',
            'delivery_instructions': 'Send your Player ID.',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            Listing.objects.filter(seller=self.seller, option=self.option_small).count(), 1,
        )

    def test_create_offer_rejects_option_from_other_category(self):
        standard_category = Category.objects.create(name='Accounts', slug='accounts')
        other_gc = GameCategory.objects.create(
            game=self.game, category=standard_category, listing_mode='offer',
        )
        foreign_option = CategoryOption.objects.create(
            game_category=other_gc, name='Foreign', order=0,
        )
        self.client.force_authenticate(user=self.seller)

        response = self.client.post('/api/listings/', {
            'game_slug': 'pubg-mobile',
            'category_slug': 'uc',
            'option_id': foreign_option.id,
            'price': '120.00',
            'delivery_time': '1-2 Hours',
        }, format='json')

        self.assertEqual(response.status_code, 400)

    def test_standard_category_rejects_option_id(self):
        standard_category = Category.objects.create(name='Accounts', slug='accounts')
        GameCategory.objects.create(game=self.game, category=standard_category)
        self.client.force_authenticate(user=self.seller)

        response = self.client.post('/api/listings/', {
            'game_slug': 'pubg-mobile',
            'category_slug': 'accounts',
            'option_id': self.option_small.id,
            'title': 'Some account',
            'price': '120.00',
            'delivery_time': '1-2 Hours',
        }, format='json')

        self.assertEqual(response.status_code, 400)

    def test_update_cannot_change_offer_title(self):
        listing = self.make_offer(self.seller, self.option_small, '120.00')
        self.client.force_authenticate(user=self.seller)

        response = self.client.put(f'/api/listings/{listing.id}/', {
            'title': 'Hacked title',
            'price': '110.00',
        }, format='json')

        self.assertEqual(response.status_code, 200)
        listing.refresh_from_db()
        self.assertEqual(listing.title, '60 UC')
        self.assertEqual(listing.price, Decimal('110.00'))

    def test_update_cannot_reactivate_into_duplicate_active_offer(self):
        inactive = self.make_offer(self.seller, self.option_small, '120.00', status='inactive')
        self.make_offer(self.seller, self.option_small, '130.00')
        self.client.force_authenticate(user=self.seller)

        response = self.client.put(f'/api/listings/{inactive.id}/', {
            'status': 'active',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        inactive.refresh_from_db()
        self.assertEqual(inactive.status, 'inactive')

    def make_region_filter(self, require_selection=True):
        region_filter = Filter.objects.create(name='Region', filter_type='dropdown')
        FilterOption.objects.create(filter=region_filter, label='Global', value='global')
        FilterOption.objects.create(filter=region_filter, label='Pakistan', value='pakistan')
        GameCategoryFilter.objects.create(
            game_category=self.game_category,
            filter=region_filter,
            require_selection=require_selection,
        )
        return region_filter

    def test_filters_payload_includes_require_selection_flag(self):
        self.make_region_filter(require_selection=True)

        response = self.client.get('/api/games/pubg-mobile/uc/')

        region_payload = next(f for f in response.data['filters'] if f['name'] == 'Region')
        self.assertTrue(region_payload['require_selection'])

    def test_option_aggregates_respect_filter_params(self):
        region_filter = self.make_region_filter()
        global_offer = self.make_offer(self.seller, self.option_small, '120.00')
        global_offer.filter_values = {str(region_filter.id): 'global'}
        global_offer.save(update_fields=['filter_values'])
        pakistan_offer = self.make_offer(self.other_seller, self.option_small, '99.00')
        pakistan_offer.filter_values = {str(region_filter.id): 'pakistan'}
        pakistan_offer.save(update_fields=['filter_values'])

        unfiltered = self.client.get('/api/games/pubg-mobile/uc/')
        filtered = self.client.get(
            f'/api/games/pubg-mobile/uc/?filter_{region_filter.id}=global'
            f'&option={self.option_small.id}'
        )

        unfiltered_opt = next(o for o in unfiltered.data['options'] if o['name'] == '60 UC')
        self.assertEqual(unfiltered_opt['min_price'], '99.00')
        self.assertEqual(unfiltered_opt['offer_count'], 2)

        filtered_opt = next(o for o in filtered.data['options'] if o['name'] == '60 UC')
        self.assertEqual(filtered_opt['min_price'], '120.00')
        self.assertEqual(filtered_opt['offer_count'], 1)
        listing_ids = [listing['id'] for listing in filtered.data['listings']]
        self.assertEqual(listing_ids, [global_offer.id])

    def test_delivery_instructions_visibility(self):
        offer = self.make_offer(self.seller, self.option_small, '120.00',
                                delivery_instructions='Send your Player ID.')
        standard_category = Category.objects.create(name='Accounts', slug='accounts')
        standard_gc = GameCategory.objects.create(game=self.game, category=standard_category)
        standard = Listing.objects.create(
            seller=self.seller,
            game_category=standard_gc,
            title='Rare account',
            price=Decimal('500.00'),
            status='active',
            delivery_instructions='Change the password after receiving.',
        )

        # Anonymous buyers: offer instructions are public, standard ones are not.
        offer_detail = self.client.get(f'/api/listings/{offer.id}/')
        self.assertEqual(offer_detail.data['delivery_instructions'], 'Send your Player ID.')
        standard_detail = self.client.get(f'/api/listings/{standard.id}/')
        self.assertEqual(standard_detail.data['delivery_instructions'], '')

        # The seller still sees their own standard listing's instructions.
        self.client.force_authenticate(user=self.seller)
        own_detail = self.client.get(f'/api/listings/{standard.id}/')
        self.assertEqual(
            own_detail.data['delivery_instructions'],
            'Change the password after receiving.',
        )

    def test_buying_an_offer_creates_order_with_option_title(self):
        from .models import Order, Wallet

        listing = self.make_offer(self.seller, self.option_small, '120.00')
        buyer = User.objects.create_user(username='offerbuyer', password='password123')
        wallet = Wallet.objects.get(user=buyer)
        wallet.balance = Decimal('500.00')
        wallet.save(update_fields=['balance'])
        self.client.force_authenticate(user=buyer)

        response = self.client.post('/api/orders/buy/', {
            'listing_id': listing.id,
            'quantity': 1,
        }, format='json')

        self.assertEqual(response.status_code, 201)
        order = Order.objects.get(pk=response.data['id'])
        self.assertEqual(order.listing_title, '60 UC')
        self.assertEqual(order.total_amount, Decimal('120.00'))
