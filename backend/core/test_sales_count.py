"""Sold counts: Listing.sales_count and the profile Sales stat both count
completed sales — on-site orders plus WhatsApp sales — and a refunded sale
stops counting."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from .models import (
    Category, Game, GameCategory, Listing, Order, Wallet, WhatsAppCheckout,
)
from .services import complete_order_now, complete_whatsapp_checkout


class SalesCountTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.buyer = User.objects.create_user(
            username='soldbuyer', email='soldbuyer@example.com',
            password='password123',
        )
        self.seller = User.objects.create_user(
            username='soldseller', password='password123',
        )
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])

        game = Game.objects.create(name='Sold Game', slug='sold-game')
        category = Category.objects.create(name='Sold Accounts', slug='sold-accounts')
        self.game_category = GameCategory.objects.create(game=game, category=category)
        self.listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Sold item',
            price=Decimal('100.00'),
            quantity=5,
            status='active',
        )

    def make_order(self, status='delivered', **extra):
        return Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            listing=self.listing,
            listing_title=self.listing.title,
            quantity=1,
            unit_price=Decimal('100.00'),
            total_amount=Decimal('100.00'),
            commission_rate=Decimal('10.00'),
            commission_amount=Decimal('10.00'),
            seller_amount=Decimal('90.00'),
            status=status,
            **extra,
        )

    def _complete_whatsapp(self, **overrides):
        fields = dict(
            listing=self.listing,
            listing_title=self.listing.title,
            quantity=1,
            amount=Decimal('100.00'),
            buyer_phone='03001234567',
        )
        fields.update(overrides)
        checkout = WhatsAppCheckout.objects.create(**fields)
        with patch('core.services.meta_capi.queue_whatsapp_purchase_event'):
            complete_whatsapp_checkout(checkout)
        return checkout

    def test_completion_increments_sales_count_once(self):
        order = self.make_order()
        complete_order_now(order)
        complete_order_now(order)  # double completion must not double count

        self.listing.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.listing.sales_count, 1)
        self.assertIsNotNone(order.completed_at)

    def test_whatsapp_completion_increments_sales_count(self):
        self._complete_whatsapp()
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.sales_count, 1)

    def test_refund_of_completed_order_decrements_sales_count(self):
        order = self.make_order()
        complete_order_now(order)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.sales_count, 1)

        self.client.force_authenticate(user=self.seller)
        response = self.client.post(f'/api/orders/{order.id}/refund/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        self.listing.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')
        self.assertEqual(self.listing.sales_count, 0)

    def test_listing_api_exposes_sales_count(self):
        order = self.make_order()
        complete_order_now(order)

        response = self.client.get(f'/api/listings/{self.listing.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['sales_count'], 1)

    def test_seller_profile_counts_whatsapp_sales_too(self):
        order = self.make_order()
        complete_order_now(order)
        self._complete_whatsapp()

        response = self.client.get(f'/api/seller/profile/{self.seller.username}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['completed_sales'], 2)
