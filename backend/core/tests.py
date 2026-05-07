from decimal import Decimal
from io import BytesIO
from threading import Barrier, Thread
from urllib.parse import urlsplit
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission, User
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections, IntegrityError, transaction as db_transaction
from PIL import Image
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import resolve
from django.utils import timezone
from rest_framework import permissions
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.test import APIClient

from .admin import OrderAdmin, TopUpRequestAdmin, WithdrawRequestAdmin
from .admin_dashboard import GamesBazaarAdminSite
from .models import (
    Category, Conversation, Filter, FilterOption, Game, GameCategory, GameCategoryFilter,
    Listing, Message, Notification, Order, Report, Review, SupportTicket,
    PlatformLedgerEntry, SellerCommissionOverride, TopUpRequest, UserProfile, Wallet,
    WalletTransaction, WithdrawRequest,
)
from .serializers import (
    MAX_AUTO_DELIVERY_LINE_LENGTH,
    MAX_AUTO_DELIVERY_LINES,
    MAX_DELIVERY_NOTE_LENGTH,
    MAX_DISPUTE_REASON_LENGTH,
    WalletTransactionSerializer,
)
from .services import decrypt_sensitive_text, encrypt_sensitive_text


def make_image_file(name='proof.png', image_format='PNG', content_type='image/png', size=(2, 2)):
    buffer = BytesIO()
    image = Image.new('RGB', size, color='green')
    image.save(buffer, format=image_format)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


def path_with_query(url):
    parsed = urlsplit(url)
    if parsed.query:
        return f'{parsed.path}?{parsed.query}'
    return parsed.path


class PurchaseFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.buyer = User.objects.create_user(username='buyer', password='password123')
        self.seller = User.objects.create_user(username='seller', password='password123')
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])

        self.buyer_wallet = Wallet.objects.get(user=self.buyer)
        self.buyer_wallet.balance = Decimal('100.00')
        self.buyer_wallet.save(update_fields=['balance'])

        game = Game.objects.create(name='Test Game', slug='test-game')
        self.category = Category.objects.create(name='Accounts', slug='accounts')
        self.game_category = GameCategory.objects.create(game=game, category=self.category)

        self.client.force_authenticate(user=self.buyer)

    def test_cannot_buy_more_than_available_stock(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='One stock item',
            price=Decimal('25.00'),
            quantity=1,
            status='active',
        )

        first = self.client.post(
            '/api/orders/buy/',
            {'listing_id': listing.id, 'quantity': 1},
            format='json',
        )
        second = self.client.post(
            '/api/orders/buy/',
            {'listing_id': listing.id, 'quantity': 1},
            format='json',
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(Order.objects.filter(listing=listing).count(), 1)

        listing.refresh_from_db()
        self.assertEqual(listing.quantity, 0)
        self.assertEqual(listing.status, 'sold')

        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('75.00'))

    def test_order_number_is_public_random_reference(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Public ref item',
            price=Decimal('10.00'),
            quantity=1,
            status='active',
        )

        buy_response = self.client.post(
            '/api/orders/buy/',
            {'listing_id': listing.id, 'quantity': 1},
            format='json',
        )

        self.assertEqual(buy_response.status_code, 201)
        order_number = buy_response.data['order_number']
        self.assertRegex(order_number, r'^GB-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}$')
        self.assertNotEqual(order_number, str(buy_response.data['id']))

        detail_response = self.client.get(f'/api/orders/{order_number}/')
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.data['id'], buy_response.data['id'])
        self.assertEqual(detail_response.data['order_number'], order_number)

    def test_delivery_and_confirm_accept_public_order_number_reference(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Public ref action item',
            price=Decimal('10.00'),
            quantity=1,
            status='active',
        )
        buy_response = self.client.post(
            '/api/orders/buy/',
            {'listing_id': listing.id, 'quantity': 1},
            format='json',
        )
        order_number = buy_response.data['order_number']

        self.client.force_authenticate(user=self.seller)
        deliver_response = self.client.post(
            f'/api/orders/{order_number}/deliver/',
            {'delivery_note': 'Delivered by public reference.'},
            format='json',
        )
        self.client.force_authenticate(user=self.buyer)
        confirm_response = self.client.post(
            f'/api/orders/{order_number}/confirm/',
            {},
            format='json',
        )

        self.assertEqual(deliver_response.status_code, 200)
        self.assertEqual(confirm_response.status_code, 200)
        self.assertEqual(confirm_response.data['status'], 'completed')

    def test_dispute_and_refund_accept_public_order_number_reference(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Public ref refund item',
            price=Decimal('10.00'),
            quantity=1,
            status='active',
        )
        buy_response = self.client.post(
            '/api/orders/buy/',
            {'listing_id': listing.id, 'quantity': 1},
            format='json',
        )
        order_number = buy_response.data['order_number']

        dispute_response = self.client.post(
            f'/api/orders/{order_number}/dispute/',
            {'reason': 'Something went wrong.'},
            format='json',
        )
        self.client.force_authenticate(user=self.seller)
        refund_response = self.client.post(
            f'/api/orders/{order_number}/refund/',
            {},
            format='json',
        )

        self.assertEqual(dispute_response.status_code, 200)
        self.assertEqual(refund_response.status_code, 200)
        self.assertEqual(refund_response.data['status'], 'cancelled')

    def test_oversized_numeric_order_reference_returns_not_found(self):
        huge_reference = '9' * 5000
        response = self.client.get(f'/api/orders/{huge_reference}/')
        self.assertEqual(response.status_code, 404)

    def test_cannot_buy_with_negative_quantity(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Negative quantity item',
            price=Decimal('10.00'),
            quantity=5,
            status='active',
        )

        response = self.client.post(
            '/api/orders/buy/',
            {'listing_id': listing.id, 'quantity': -10},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('quantity', response.data)
        self.assertFalse(Order.objects.filter(listing=listing).exists())

        listing.refresh_from_db()
        self.assertEqual(listing.quantity, 5)

        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('100.00'))

    def test_auto_delivery_short_data_does_not_debit_wallet(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Mismatched auto stock',
            price=Decimal('10.00'),
            quantity=2,
            status='active',
            is_auto_delivery=True,
            auto_delivery_data='code-one',
        )

        response = self.client.post(
            '/api/orders/buy/',
            {'listing_id': listing.id, 'quantity': 2},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'Only 1 item remaining for auto-delivery.')
        self.assertFalse(Order.objects.filter(listing=listing).exists())

        listing.refresh_from_db()
        self.assertEqual(listing.quantity, 2)
        self.assertEqual(listing.status, 'active')
        self.assertEqual(listing.auto_delivery_data, 'code-one')

        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('100.00'))

    def test_auto_delivery_whitespace_only_stock_does_not_debit_wallet(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Whitespace only auto stock',
            price=Decimal('10.00'),
            quantity=1,
            status='active',
            is_auto_delivery=True,
            auto_delivery_data=' \n\t',
        )

        response = self.client.post(
            '/api/orders/buy/',
            {'listing_id': listing.id, 'quantity': 1},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'Only 0 items remaining for auto-delivery.')
        self.assertFalse(Order.objects.filter(listing=listing).exists())

        listing.refresh_from_db()
        self.assertEqual(listing.quantity, 1)
        self.assertEqual(listing.status, 'active')
        self.assertEqual(listing.auto_delivery_data, ' \n\t')

        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('100.00'))

    def test_refund_auto_delivery_does_not_restore_consumed_stock(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Auto delivery item',
            price=Decimal('10.00'),
            quantity=1,
            status='active',
            is_auto_delivery=True,
            auto_delivery_data='code-one',
        )

        buy_response = self.client.post(
            '/api/orders/buy/',
            {'listing_id': listing.id, 'quantity': 1},
            format='json',
        )
        self.assertEqual(buy_response.status_code, 201)
        self.assertEqual(buy_response.data['status'], 'delivered')

        listing.refresh_from_db()
        self.assertEqual(listing.quantity, 0)
        self.assertEqual(listing.status, 'sold')
        self.assertEqual(listing.auto_delivery_data, '')

        self.client.force_authenticate(user=self.seller)
        refund_response = self.client.post(
            f"/api/orders/{buy_response.data['id']}/refund/",
            {},
            format='json',
        )

        self.assertEqual(refund_response.status_code, 200)
        listing.refresh_from_db()
        self.assertEqual(listing.quantity, 0)
        self.assertEqual(listing.status, 'sold')
        self.assertEqual(listing.auto_delivery_data, '')

        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('100.00'))

    def test_auto_delivery_api_stores_and_delivers_encrypted_secrets(self):
        self.game_category.allow_auto_delivery = True
        self.game_category.save(update_fields=['allow_auto_delivery'])

        self.client.force_authenticate(user=self.seller)
        create_response = self.client.post(
            '/api/listings/',
            {
                'game_slug': 'test-game',
                'category_slug': 'accounts',
                'title': 'Encrypted auto item',
                'price': '10.00',
                'is_auto_delivery': True,
                'auto_delivery_data': 'code-one\ncode-two',
                'delivery_instructions': 'Change the password after login.',
                'filter_values': {},
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, 201)
        listing = Listing.objects.get(title='Encrypted auto item')
        self.assertNotEqual(listing.auto_delivery_data, 'code-one\ncode-two')
        self.assertEqual(decrypt_sensitive_text(listing.auto_delivery_data), 'code-one\ncode-two')

        self.client.force_authenticate(user=self.buyer)
        buy_response = self.client.post(
            '/api/orders/buy/',
            {'listing_id': listing.id, 'quantity': 1},
            format='json',
        )

        self.assertEqual(buy_response.status_code, 201)
        self.assertEqual(buy_response.data['delivery_note'], 'code-one')
        self.assertEqual(buy_response.data['delivery_instructions'], 'Change the password after login.')
        self.assertTrue(buy_response.data['is_auto_delivery'])
        order = Order.objects.get(pk=buy_response.data['id'])
        self.assertNotIn('code-one', order.delivery_note)
        self.assertTrue(order.was_auto_delivery)
        self.assertEqual(order.delivery_instructions_snapshot, 'Change the password after login.')
        self.assertEqual(decrypt_sensitive_text(order.delivery_note), buy_response.data['delivery_note'])
        listing.refresh_from_db()
        self.assertEqual(decrypt_sensitive_text(listing.auto_delivery_data), 'code-two')

        listing.is_auto_delivery = False
        listing.delivery_instructions = 'Changed later.'
        listing.save(update_fields=['is_auto_delivery', 'delivery_instructions'])
        self.client.force_authenticate(user=self.buyer)
        detail_response = self.client.get(f'/api/orders/{order.pk}/')
        self.assertEqual(detail_response.status_code, 200)
        self.assertTrue(detail_response.data['is_auto_delivery'])
        self.assertEqual(detail_response.data['auto_delivery_data'], 'code-one')
        self.assertEqual(detail_response.data['delivery_instructions'], 'Change the password after login.')

        listing.delete()
        detail_response = self.client.get(f'/api/orders/{order.pk}/')
        self.assertEqual(detail_response.status_code, 200)
        self.assertTrue(detail_response.data['is_auto_delivery'])
        self.assertEqual(detail_response.data['auto_delivery_data'], 'code-one')

    def test_auto_delivery_create_rejects_whitespace_only_inventory(self):
        self.game_category.allow_auto_delivery = True
        self.game_category.save(update_fields=['allow_auto_delivery'])
        self.client.force_authenticate(user=self.seller)

        for title, payload in (
            ('Whitespace auto item spaces', ' '),
            ('Whitespace auto item tabs', '\t'),
            ('Whitespace auto item mixed', ' \n\t'),
        ):
            with self.subTest(payload=repr(payload)):
                response = self.client.post(
                    '/api/listings/',
                    {
                        'game_slug': 'test-game',
                        'category_slug': 'accounts',
                        'title': title,
                        'price': '10.00',
                        'is_auto_delivery': True,
                        'auto_delivery_data': payload,
                        'filter_values': {},
                    },
                    format='json',
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn('auto_delivery_data', response.data)
                self.assertFalse(Listing.objects.filter(title=title).exists())

    def test_auto_delivery_preserves_item_edge_whitespace(self):
        self.game_category.allow_auto_delivery = True
        self.game_category.save(update_fields=['allow_auto_delivery'])
        self.client.force_authenticate(user=self.seller)

        create_response = self.client.post(
            '/api/listings/',
            {
                'game_slug': 'test-game',
                'category_slug': 'accounts',
                'title': 'Whitespace credential',
                'description': 'Sensitive spacing',
                'price': '25.00',
                'filter_values': {},
                'is_auto_delivery': True,
                'auto_delivery_data': '  code-one  \ncode-two',
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, 201)
        listing = Listing.objects.get(title='Whitespace credential')
        self.assertEqual(decrypt_sensitive_text(listing.auto_delivery_data), '  code-one  \ncode-two')

        self.client.force_authenticate(user=self.buyer)
        buy_response = self.client.post(
            '/api/orders/buy/',
            {'listing_id': listing.id, 'quantity': 1},
            format='json',
        )

        self.assertEqual(buy_response.status_code, 201)
        self.assertEqual(buy_response.data['delivery_note'], '  code-one  ')
        listing.refresh_from_db()
        self.assertEqual(decrypt_sensitive_text(listing.auto_delivery_data), 'code-two')

    def test_auto_delivery_payload_limits_are_enforced(self):
        self.game_category.allow_auto_delivery = True
        self.game_category.save(update_fields=['allow_auto_delivery'])
        self.client.force_authenticate(user=self.seller)

        too_many_items = '\n'.join(f'code-{index}' for index in range(MAX_AUTO_DELIVERY_LINES + 1))
        too_many_response = self.client.post(
            '/api/listings/',
            {
                'game_slug': 'test-game',
                'category_slug': 'accounts',
                'title': 'Too many auto items',
                'price': '10.00',
                'is_auto_delivery': True,
                'auto_delivery_data': too_many_items,
                'filter_values': {},
            },
            format='json',
        )
        long_line_response = self.client.post(
            '/api/listings/',
            {
                'game_slug': 'test-game',
                'category_slug': 'accounts',
                'title': 'Too long auto item',
                'price': '10.00',
                'is_auto_delivery': True,
                'auto_delivery_data': 'x' * (MAX_AUTO_DELIVERY_LINE_LENGTH + 1),
                'filter_values': {},
            },
            format='json',
        )

        self.assertEqual(too_many_response.status_code, 400)
        self.assertEqual(long_line_response.status_code, 400)
        self.assertIn('auto_delivery_data', too_many_response.data)
        self.assertIn('auto_delivery_data', long_line_response.data)

    def test_confirm_order_records_platform_commission_ledger(self):
        self.category.commission_rate = Decimal('10.00')
        self.category.save(update_fields=['commission_rate'])
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Commissioned item',
            price=Decimal('50.00'),
            quantity=1,
            status='active',
        )

        buy_response = self.client.post(
            '/api/orders/buy/',
            {'listing_id': listing.id, 'quantity': 1},
            format='json',
        )
        self.assertEqual(buy_response.status_code, 201)

        order_id = buy_response.data['id']
        order = Order.objects.get(pk=order_id)
        order.status = 'delivered'
        order.save(update_fields=['status'])

        confirm_response = self.client.post(
            f'/api/orders/{order_id}/confirm/',
            {},
            format='json',
        )

        self.assertEqual(confirm_response.status_code, 200)
        entry = PlatformLedgerEntry.objects.get(
            entry_type='commission_collected',
            reference_id=f'order_{order_id}',
        )
        self.assertEqual(entry.amount, Decimal('5.00'))

        seller_wallet = Wallet.objects.get(user=self.seller)
        self.assertEqual(seller_wallet.balance, Decimal('45.00'))
        sale_tx = WalletTransaction.objects.get(
            wallet=seller_wallet,
            transaction_type='sale',
            reference_id=f'order_{order_id}',
        )
        commission_tx = WalletTransaction.objects.get(
            wallet=seller_wallet,
            transaction_type='commission',
            reference_id=f'order_{order_id}',
        )
        self.assertEqual(sale_tx.amount, Decimal('50.00'))
        self.assertEqual(sale_tx.balance_after, Decimal('50.00'))
        self.assertEqual(commission_tx.amount, Decimal('5.00'))
        self.assertEqual(commission_tx.balance_after, Decimal('45.00'))

    def test_completed_order_refund_reverses_platform_commission_ledger(self):
        self.category.commission_rate = Decimal('10.00')
        self.category.save(update_fields=['commission_rate'])
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Refunded commissioned item',
            price=Decimal('50.00'),
            quantity=1,
            status='active',
        )

        buy_response = self.client.post(
            '/api/orders/buy/',
            {'listing_id': listing.id, 'quantity': 1},
            format='json',
        )
        self.assertEqual(buy_response.status_code, 201)
        order_id = buy_response.data['id']
        order = Order.objects.get(pk=order_id)
        order.status = 'delivered'
        order.save(update_fields=['status'])

        confirm_response = self.client.post(
            f'/api/orders/{order_id}/confirm/',
            {},
            format='json',
        )
        self.assertEqual(confirm_response.status_code, 200)

        self.client.force_authenticate(user=self.seller)
        refund_response = self.client.post(
            f'/api/orders/{order_id}/refund/',
            {},
            format='json',
        )

        self.assertEqual(refund_response.status_code, 200)
        collected = PlatformLedgerEntry.objects.get(
            entry_type='commission_collected',
            reference_id=f'order_{order_id}',
        )
        reversed_entry = PlatformLedgerEntry.objects.get(
            entry_type='commission_reversed',
            reference_id=f'order_{order_id}',
        )
        self.assertEqual(collected.amount, Decimal('5.00'))
        self.assertEqual(reversed_entry.amount, Decimal('-5.00'))

        self.buyer_wallet.refresh_from_db()
        seller_wallet = Wallet.objects.get(user=self.seller)
        self.assertEqual(self.buyer_wallet.balance, Decimal('100.00'))
        self.assertEqual(seller_wallet.balance, Decimal('0.00'))
        seller_refund_tx = WalletTransaction.objects.get(
            wallet=seller_wallet,
            transaction_type='refund',
            reference_id=f'order_{order_id}',
        )
        buyer_refund_tx = WalletTransaction.objects.get(
            wallet=self.buyer_wallet,
            transaction_type='refund',
            reference_id=f'order_{order_id}',
        )
        seller_refund_data = WalletTransactionSerializer(seller_refund_tx).data
        buyer_refund_data = WalletTransactionSerializer(buyer_refund_tx).data
        self.assertTrue(seller_refund_data['is_debit'])
        self.assertEqual(seller_refund_data['display_amount'], '45.00')
        self.assertFalse(buyer_refund_data['is_debit'])
        self.assertEqual(buyer_refund_data['display_amount'], '50.00')

    def test_create_listing_rejects_non_positive_price(self):
        self.client.force_authenticate(user=self.seller)

        response = self.client.post(
            '/api/listings/',
            {
                'game_slug': 'test-game',
                'category_slug': 'accounts',
                'title': 'Invalid price item',
                'price': '0.00',
                'quantity': 1,
                'filter_values': {},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('price', response.data)
        self.assertFalse(Listing.objects.filter(title='Invalid price item').exists())

    def test_create_listing_accepts_valid_filter_values(self):
        rank_filter = Filter.objects.create(name='Rank', filter_type='button')
        FilterOption.objects.create(filter=rank_filter, label='Gold', value='gold')
        GameCategoryFilter.objects.create(game_category=self.game_category, filter=rank_filter)
        self.client.force_authenticate(user=self.seller)

        response = self.client.post(
            '/api/listings/',
            {
                'game_slug': 'test-game',
                'category_slug': 'accounts',
                'title': 'Filtered listing',
                'price': '10.00',
                'quantity': 1,
                'filter_values': {
                    str(rank_filter.id): ' gold ',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        listing = Listing.objects.get(title='Filtered listing')
        self.assertEqual(listing.filter_values, {str(rank_filter.id): 'gold'})

    def test_create_listing_rejects_missing_assigned_filter_values(self):
        platform_filter = Filter.objects.create(name='Platform', filter_type='dropdown')
        FilterOption.objects.create(filter=platform_filter, label='Steam', value='steam')
        GameCategoryFilter.objects.create(game_category=self.game_category, filter=platform_filter)
        self.client.force_authenticate(user=self.seller)

        response = self.client.post(
            '/api/listings/',
            {
                'game_slug': 'test-game',
                'category_slug': 'accounts',
                'title': 'Missing platform listing',
                'price': '10.00',
                'quantity': 1,
                'filter_values': {},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('filter_values', response.data)
        self.assertIn('Platform', str(response.data['filter_values']))
        self.assertFalse(Listing.objects.filter(title='Missing platform listing').exists())

    def test_create_listing_rejects_unassigned_filter_value(self):
        region_filter = Filter.objects.create(name='Region', filter_type='dropdown')
        FilterOption.objects.create(filter=region_filter, label='Asia', value='asia')
        self.client.force_authenticate(user=self.seller)

        response = self.client.post(
            '/api/listings/',
            {
                'game_slug': 'test-game',
                'category_slug': 'accounts',
                'title': 'Bad filter listing',
                'price': '10.00',
                'quantity': 1,
                'filter_values': {
                    str(region_filter.id): 'asia',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('filter_values', response.data)
        self.assertFalse(Listing.objects.filter(title='Bad filter listing').exists())

    def test_create_listing_rejects_invalid_filter_option(self):
        rank_filter = Filter.objects.create(name='Rank', filter_type='button')
        FilterOption.objects.create(filter=rank_filter, label='Gold', value='gold')
        GameCategoryFilter.objects.create(game_category=self.game_category, filter=rank_filter)
        self.client.force_authenticate(user=self.seller)

        response = self.client.post(
            '/api/listings/',
            {
                'game_slug': 'test-game',
                'category_slug': 'accounts',
                'title': 'Bad option listing',
                'price': '10.00',
                'quantity': 1,
                'filter_values': {
                    str(rank_filter.id): 'fake-rank',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('filter_values', response.data)
        self.assertFalse(Listing.objects.filter(title='Bad option listing').exists())

    def test_create_listing_rejects_malformed_filter_values(self):
        self.client.force_authenticate(user=self.seller)

        list_response = self.client.post(
            '/api/listings/',
            {
                'game_slug': 'test-game',
                'category_slug': 'accounts',
                'title': 'List filter listing',
                'price': '10.00',
                'quantity': 1,
                'filter_values': ['not', 'an', 'object'],
            },
            format='json',
        )
        non_numeric_response = self.client.post(
            '/api/listings/',
            {
                'game_slug': 'test-game',
                'category_slug': 'accounts',
                'title': 'Non numeric filter listing',
                'price': '10.00',
                'quantity': 1,
                'filter_values': {
                    'rank': 'gold',
                },
            },
            format='json',
        )

        self.assertEqual(list_response.status_code, 400)
        self.assertEqual(non_numeric_response.status_code, 400)
        self.assertIn('filter_values', list_response.data)
        self.assertIn('filter_values', non_numeric_response.data)
        self.assertFalse(Listing.objects.filter(title__contains='filter listing').exists())

    def test_update_listing_rejects_instant_delivery_for_manual_listing(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Manual delivery item',
            price=Decimal('10.00'),
            quantity=1,
            status='active',
            delivery_time='1-2 Hours',
        )
        self.client.force_authenticate(user=self.seller)

        response = self.client.put(
            f'/api/listings/{listing.id}/',
            {'delivery_time': 'Instant'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('delivery_time', response.data)
        listing.refresh_from_db()
        self.assertEqual(listing.delivery_time, '1-2 Hours')

    def test_update_listing_rejects_reactivating_empty_auto_delivery_listing(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Empty auto delivery item',
            price=Decimal('10.00'),
            quantity=0,
            status='sold',
            is_auto_delivery=True,
            auto_delivery_data='',
            delivery_time='Instant',
        )
        self.client.force_authenticate(user=self.seller)

        response = self.client.put(
            f'/api/listings/{listing.id}/',
            {'status': 'active'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('status', response.data)
        listing.refresh_from_db()
        self.assertEqual(listing.status, 'sold')

    def test_update_listing_rejects_reactivating_empty_manual_listing(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Empty manual delivery item',
            price=Decimal('10.00'),
            quantity=0,
            status='sold',
            delivery_time='1-2 Hours',
        )
        self.client.force_authenticate(user=self.seller)

        response = self.client.put(
            f'/api/listings/{listing.id}/',
            {'status': 'active'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('status', response.data)
        listing.refresh_from_db()
        self.assertEqual(listing.quantity, 0)
        self.assertEqual(listing.status, 'sold')

    def test_update_listing_allows_reactivating_manual_listing_with_unlimited_stock(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Unlimited manual delivery item',
            price=Decimal('10.00'),
            quantity=0,
            status='sold',
            delivery_time='1-2 Hours',
        )
        self.client.force_authenticate(user=self.seller)

        response = self.client.put(
            f'/api/listings/{listing.id}/',
            {'status': 'active', 'quantity': None},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        listing.refresh_from_db()
        self.assertIsNone(listing.quantity)
        self.assertEqual(listing.status, 'active')

    def test_seller_can_restock_auto_delivery_listing(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Sold auto delivery item',
            price=Decimal('10.00'),
            quantity=0,
            status='sold',
            is_auto_delivery=True,
            auto_delivery_data='',
            delivery_time='Instant',
        )
        self.client.force_authenticate(user=self.seller)

        response = self.client.post(
            f'/api/listings/{listing.id}/restock/',
            {'auto_delivery_data': 'code-two\ncode-three'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        listing.refresh_from_db()
        self.assertEqual(listing.quantity, 2)
        self.assertEqual(listing.status, 'active')
        self.assertEqual(decrypt_sensitive_text(listing.auto_delivery_data), 'code-two\ncode-three')

    def test_restock_rejects_whitespace_only_auto_delivery_data(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Sold auto delivery item',
            price=Decimal('10.00'),
            quantity=0,
            status='sold',
            is_auto_delivery=True,
            auto_delivery_data='',
            delivery_time='Instant',
        )
        self.client.force_authenticate(user=self.seller)

        response = self.client.post(
            f'/api/listings/{listing.id}/restock/',
            {'auto_delivery_data': ' \n\t'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('auto_delivery_data', response.data)
        listing.refresh_from_db()
        self.assertEqual(listing.quantity, 0)
        self.assertEqual(listing.status, 'sold')
        self.assertEqual(listing.auto_delivery_data, '')

    def test_restock_rejects_manual_listing(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Manual item',
            price=Decimal('10.00'),
            quantity=1,
            status='active',
            is_auto_delivery=False,
        )
        self.client.force_authenticate(user=self.seller)

        response = self.client.post(
            f'/api/listings/{listing.id}/restock/',
            {'auto_delivery_data': 'code-two'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'Only automated delivery listings can be restocked here.')

    def test_sensitive_text_uses_dedicated_field_key_when_configured(self):
        legacy_encrypted = encrypt_sensitive_text('legacy-code')
        key = Fernet.generate_key().decode('ascii')

        with override_settings(
            FIELD_ENCRYPTION_KEYS={'primary': key},
            FIELD_ENCRYPTION_PRIMARY_KEY_ID='primary',
        ):
            encrypted = encrypt_sensitive_text('code-one')
            self.assertTrue(encrypted.startswith('enc:v2:primary:'))
            self.assertEqual(decrypt_sensitive_text(encrypted), 'code-one')
            self.assertEqual(decrypt_sensitive_text(legacy_encrypted), 'legacy-code')


class TopUpProofUploadTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='buyer', password='password123')
        self.client.force_authenticate(user=self.user)

    def test_accepts_valid_payment_proof_image(self):
        response = self.client.post(
            '/api/wallet/top-up/',
            {
                'amount': '100.00',
                'payment_method': 'Bank Transfer',
                'transaction_id': 'valid-proof',
                'payment_proof': make_image_file(),
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 201)
        topup = TopUpRequest.objects.get(transaction_id='valid-proof')
        self.assertTrue(topup.payment_proof.name.startswith('topup_proofs/'))
        self.assertIn(f'/api/wallet/top-up/{topup.pk}/proof/', response.data['payment_proof_url'])
        self.assertNotIn('/media/', response.data['payment_proof_url'])

        proof_response = self.client.get(path_with_query(response.data['payment_proof_url']))
        self.assertEqual(proof_response.status_code, 200)
        self.assertEqual(proof_response['Content-Type'], 'image/png')
        self.assertEqual(proof_response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(proof_response['Cache-Control'], 'private, no-store')
        self.assertEqual(proof_response['Referrer-Policy'], 'no-referrer')

        self.client.force_authenticate(user=None)
        unauthenticated_signed_response = self.client.get(
            path_with_query(response.data['payment_proof_url'])
        )
        self.assertEqual(unauthenticated_signed_response.status_code, 404)

        other_user = User.objects.create_user(username='other_buyer', password='password123')
        self.client.force_authenticate(user=other_user)
        signed_other_user_response = self.client.get(
            path_with_query(response.data['payment_proof_url'])
        )
        self.assertEqual(signed_other_user_response.status_code, 404)

        unsigned_response = self.client.get(f'/api/wallet/top-up/{topup.pk}/proof/')
        self.assertEqual(unsigned_response.status_code, 404)

    def test_rejects_missing_transaction_reference(self):
        response = self.client.post(
            '/api/wallet/top-up/',
            {
                'amount': '100.00',
                'payment_method': 'Bank Transfer',
                'payment_proof': make_image_file(),
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('transaction_id', response.data)
        self.assertFalse(TopUpRequest.objects.exists())

    def test_rejects_missing_payment_proof(self):
        response = self.client.post(
            '/api/wallet/top-up/',
            {
                'amount': '100.00',
                'payment_method': 'Bank Transfer',
                'transaction_id': 'missing-proof',
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['payment_proof'], ['This field is required.'])
        self.assertFalse(TopUpRequest.objects.filter(transaction_id='missing-proof').exists())

    def test_rejects_duplicate_active_transaction_reference(self):
        TopUpRequest.objects.create(
            user=self.user,
            amount=Decimal('100.00'),
            payment_method='Bank Transfer',
            transaction_id='duplicate-ref',
        )

        response = self.client.post(
            '/api/wallet/top-up/',
            {
                'amount': '100.00',
                'payment_method': ' bank transfer ',
                'transaction_id': ' DUPLICATE-REF ',
                'payment_proof': make_image_file(),
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('transaction_id', response.data)
        self.assertEqual(
            TopUpRequest.objects.filter(transaction_id__iexact='duplicate-ref').count(),
            1,
        )

    def test_rejects_topup_amount_over_ten_thousand(self):
        response = self.client.post(
            '/api/wallet/top-up/',
            {
                'amount': '10000.01',
                'payment_method': 'Bank Transfer',
                'transaction_id': 'too-much',
                'payment_proof': make_image_file(),
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['amount'][0],
            'Max is 10000. Please contact support if you want to add more.',
        )
        self.assertFalse(TopUpRequest.objects.filter(transaction_id='too-much').exists())

    def test_rejects_payment_proof_with_invalid_content_type(self):
        response = self.client.post(
            '/api/wallet/top-up/',
            {
                'amount': '100.00',
                'transaction_id': 'invalid-type',
                'payment_proof': SimpleUploadedFile(
                    'proof.txt',
                    b'not an image',
                    content_type='text/plain',
                ),
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'Invalid image type.')
        self.assertFalse(TopUpRequest.objects.filter(transaction_id='invalid-type').exists())

    def test_rejects_svg_payment_proof(self):
        response = self.client.post(
            '/api/wallet/top-up/',
            {
                'amount': '100.00',
                'transaction_id': 'svg-proof',
                'payment_proof': SimpleUploadedFile(
                    'proof.svg',
                    b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                    content_type='image/svg+xml',
                ),
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'Invalid image type.')
        self.assertFalse(TopUpRequest.objects.filter(transaction_id='svg-proof').exists())

    def test_rejects_payment_proof_with_fake_image_bytes(self):
        response = self.client.post(
            '/api/wallet/top-up/',
            {
                'amount': '100.00',
                'transaction_id': 'fake-image',
                'payment_proof': SimpleUploadedFile(
                    'proof.png',
                    b'not actually a png',
                    content_type='image/png',
                ),
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'Invalid image file.')
        self.assertFalse(TopUpRequest.objects.filter(transaction_id='fake-image').exists())

    def test_rejects_oversized_payment_proof(self):
        response = self.client.post(
            '/api/wallet/top-up/',
            {
                'amount': '100.00',
                'transaction_id': 'too-large',
                'payment_proof': SimpleUploadedFile(
                    'proof.png',
                    b'0' * (5 * 1024 * 1024 + 1),
                    content_type='image/png',
                ),
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'Image too large. Max 5MB.')
        self.assertFalse(TopUpRequest.objects.filter(transaction_id='too-large').exists())

    def test_rejects_payment_proof_with_oversized_dimensions(self):
        response = self.client.post(
            '/api/wallet/top-up/',
            {
                'amount': '100.00',
                'transaction_id': 'too-wide',
                'payment_proof': make_image_file(size=(6001, 1)),
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'Image dimensions too large.')
        self.assertFalse(TopUpRequest.objects.filter(transaction_id='too-wide').exists())


class WithdrawalRequestTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='buyer', password='password123')
        self.wallet = Wallet.objects.get(user=self.user)
        self.wallet.balance = Decimal('1200.00')
        self.wallet.save(update_fields=['balance'])
        self.client.force_authenticate(user=self.user)

    def test_withdrawal_request_deducts_wallet_and_logs_hold(self):
        response = self.client.post(
            '/api/wallet/withdraw/',
            {
                'amount': '500.00',
                'payment_method': 'JazzCash',
                'account_title': 'Buyer Account',
                'account_details': '03001234567',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        withdraw = WithdrawRequest.objects.get(user=self.user)
        self.assertEqual(withdraw.status, 'pending')
        self.assertEqual(withdraw.amount, Decimal('500.00'))
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('700.00'))
        transaction = WalletTransaction.objects.get(
            wallet=self.wallet,
            transaction_type='withdraw_request',
            reference_id=f'withdraw_{withdraw.pk}',
        )
        self.assertEqual(transaction.amount, Decimal('500.00'))
        self.assertEqual(transaction.balance_after, Decimal('700.00'))

    def test_withdrawal_rejects_insufficient_balance_without_side_effects(self):
        response = self.client.post(
            '/api/wallet/withdraw/',
            {
                'amount': '1500.00',
                'payment_method': 'JazzCash',
                'account_title': 'Buyer Account',
                'account_details': '03001234567',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'Insufficient wallet balance.')
        self.assertFalse(WithdrawRequest.objects.exists())
        self.assertFalse(WalletTransaction.objects.filter(wallet=self.wallet).exists())
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('1200.00'))

    def test_bank_transfer_withdrawal_requires_bank_name(self):
        response = self.client.post(
            '/api/wallet/withdraw/',
            {
                'amount': '500.00',
                'payment_method': 'Bank Transfer',
                'account_title': 'Buyer Account',
                'account_details': 'PK36MEZN0001234567890123',
                'bank_name': '  ',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('bank_name', response.data)
        self.assertFalse(WithdrawRequest.objects.exists())
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('1200.00'))


class ReportFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.reporter = User.objects.create_user(username='reporter', password='password123')
        self.seller = User.objects.create_user(username='seller', password='password123')
        self.other_user = User.objects.create_user(username='other', password='password123')
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])
        game = Game.objects.create(name='Report Game', slug='report-game')
        category = Category.objects.create(name='Accounts', slug='report-accounts')
        self.game_category = GameCategory.objects.create(game=game, category=category)
        self.listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Reported listing',
            price=Decimal('100.00'),
            quantity=1,
        )

    def test_user_can_report_listing_once_while_pending(self):
        self.client.force_authenticate(user=self.reporter)
        payload = {
            'target_type': 'listing',
            'listing_id': self.listing.pk,
            'reason': 'scam',
            'description': 'Suspicious listing.',
        }

        response = self.client.post('/api/reports/', payload, format='json')
        duplicate_response = self.client.post('/api/reports/', payload, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Report.objects.count(), 1)
        report = Report.objects.get()
        self.assertEqual(report.reporter, self.reporter)
        self.assertEqual(report.reported_listing, self.listing)
        self.assertEqual(report.status, 'pending')
        self.assertEqual(duplicate_response.status_code, 400)
        self.assertEqual(Report.objects.count(), 1)

    def test_user_cannot_report_self_or_own_listing(self):
        self.client.force_authenticate(user=self.seller)
        own_listing_response = self.client.post(
            '/api/reports/',
            {
                'target_type': 'listing',
                'listing_id': self.listing.pk,
                'reason': 'other',
            },
            format='json',
        )
        self_report_response = self.client.post(
            '/api/reports/',
            {
                'target_type': 'user',
                'user_id': self.seller.pk,
                'reason': 'other',
            },
            format='json',
        )

        self.assertEqual(own_listing_response.status_code, 400)
        self.assertEqual(self_report_response.status_code, 400)
        self.assertFalse(Report.objects.exists())

    def test_my_reports_returns_only_current_users_reports(self):
        own_report = Report.objects.create(
            reporter=self.reporter,
            target_type='listing',
            reported_listing=self.listing,
            reason='misleading',
        )
        Report.objects.create(
            reporter=self.other_user,
            target_type='user',
            reported_user=self.seller,
            reason='harassment',
        )

        self.client.force_authenticate(user=self.reporter)
        response = self.client.get('/api/reports/mine/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['pagination']['count'], 1)
        self.assertEqual(len(response.data['reports']), 1)
        self.assertEqual(response.data['reports'][0]['id'], own_report.pk)
        self.assertEqual(response.data['reports'][0]['target_display'], 'Listing: Reported listing')


class SupportTicketFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='support_user',
            email='support-user@example.com',
            password='password123',
        )
        self.other_user = User.objects.create_user(
            username='other_support_user',
            email='other-support@example.com',
            password='password123',
        )

    def test_guest_can_create_support_ticket_with_email(self):
        response = self.client.post(
            '/api/support/',
            {
                'name': 'Guest Buyer',
                'email': 'guest@example.com',
                'category': 'order',
                'subject': 'Need order help',
                'message': 'I cannot see my order details.',
                'order_id': 123,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        ticket = SupportTicket.objects.get()
        self.assertIsNone(ticket.user)
        self.assertEqual(ticket.guest_email, 'guest@example.com')
        self.assertEqual(ticket.name, 'Guest Buyer')
        self.assertEqual(ticket.order_id, 123)
        self.assertEqual(response.data['ticket']['status'], 'open')
        self.assertNotIn('guest_email', response.data['ticket'])

    def test_guest_support_ticket_requires_email(self):
        response = self.client.post(
            '/api/support/',
            {
                'category': 'account',
                'subject': 'Cannot log in',
                'message': 'Please help.',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.data)
        self.assertFalse(SupportTicket.objects.exists())

    def test_authenticated_support_ticket_uses_user_and_hides_guest_email(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            '/api/support/',
            {
                'name': 'Ignored display name',
                'email': 'ignored@example.com',
                'category': 'payment',
                'subject': 'Wallet issue',
                'message': 'My balance looks wrong.',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        ticket = SupportTicket.objects.get()
        self.assertEqual(ticket.user, self.user)
        self.assertEqual(ticket.guest_email, '')
        self.assertEqual(ticket.name, 'Ignored display name')

    def test_my_support_tickets_returns_only_current_users_tickets(self):
        own_ticket = SupportTicket.objects.create(
            user=self.user,
            category='payment',
            subject='Wallet issue',
            message='My balance looks wrong.',
        )
        SupportTicket.objects.create(
            user=self.other_user,
            category='account',
            subject='Other user ticket',
            message='Do not show this.',
        )
        SupportTicket.objects.create(
            guest_email='guest@example.com',
            category='other',
            subject='Guest ticket',
            message='Do not show this either.',
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/support/mine/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['pagination']['count'], 1)
        self.assertEqual(len(response.data['tickets']), 1)
        self.assertEqual(response.data['tickets'][0]['id'], own_ticket.pk)

    def test_my_support_tickets_requires_authentication(self):
        response = self.client.get('/api/support/mine/')

        self.assertEqual(response.status_code, 401)


THROTTLE_TEST_REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_RATES': {
        'auth_login': '1/min',
        'auth_refresh': '1/min',
        'auth_register': '1/min',
        'chat_start': '1/min',
        'chat_ws_ticket': '1/min',
        'chat_message': '1/min',
        'chat_upload': '1/min',
        'topup_request': '1/min',
        'withdraw_request': '1/min',
        'heartbeat': '1/min',
        'search': '1/min',
        'avatar_upload': '1/min',
        'seller_apply': '1/min',
        'listing_create': '1/min',
        'listing_mutation': '1/min',
        'listing_restock': '1/min',
        'create_report': '1/min',
        'create_support_ticket': '1/min',
    },
}


class ApiThrottleConfigurationTests(TestCase):
    def test_sensitive_endpoints_have_scoped_throttles(self):
        cases = {
            '/api/auth/login/': 'auth_login',
            '/api/auth/refresh/': 'auth_refresh',
            '/api/auth/register/': 'auth_register',
            '/api/chat/start/': 'chat_start',
            '/api/chat/1/ws-ticket/': 'chat_ws_ticket',
            '/api/chat/1/send/': 'chat_message',
            '/api/chat/1/send-image/': 'chat_upload',
            '/api/wallet/top-up/': 'topup_request',
            '/api/wallet/withdraw/': 'withdraw_request',
            '/api/heartbeat/': 'heartbeat',
            '/api/search/': 'search',
            '/api/auth/avatar/': 'avatar_upload',
            '/api/seller/apply/': 'seller_apply',
            '/api/listings/': 'listing_create',
            '/api/listings/1/': 'listing_mutation',
            '/api/listings/1/restock/': 'listing_restock',
            '/api/reports/': 'create_report',
            '/api/support/': 'create_support_ticket',
        }

        for path, scope in cases.items():
            with self.subTest(path=path):
                view_class = resolve(path).func.view_class
                self.assertEqual(view_class.throttle_scope, scope)


class ApiPermissionConfigurationTests(TestCase):
    def test_default_api_permission_is_authenticated(self):
        self.assertEqual(
            settings.REST_FRAMEWORK['DEFAULT_PERMISSION_CLASSES'],
            ['rest_framework.permissions.IsAuthenticated'],
        )

    def test_public_endpoints_are_explicitly_marked_public(self):
        cases = [
            '/api/games/',
            '/api/games/test-game/',
            '/api/games/test-game/accounts/',
            '/api/auth/login/',
            '/api/auth/refresh/',
            '/api/auth/register/',
            '/api/reviews/seller/seller/',
            '/api/seller/profile/seller/',
            '/api/search/',
            '/api/support/',
        ]

        for path in cases:
            with self.subTest(path=path):
                view_class = resolve(path).func.view_class
                self.assertIn(permissions.AllowAny, view_class.permission_classes)


class ApiThrottleBehaviorTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.rate_patcher = patch.dict(
            ScopedRateThrottle.THROTTLE_RATES,
            THROTTLE_TEST_REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'],
        )
        self.rate_patcher.start()

    def tearDown(self):
        self.rate_patcher.stop()
        cache.clear()

    def test_register_is_rate_limited(self):
        strong_password = 'S3cure!Passphrase42'
        first = self.client.post(
            '/api/auth/register/',
            {
                'username': 'buyer1',
                'email': 'buyer1@example.com',
                'password': strong_password,
                'password2': strong_password,
            },
            format='json',
        )
        second = self.client.post(
            '/api/auth/register/',
            {
                'username': 'buyer2',
                'email': 'buyer2@example.com',
                'password': strong_password,
                'password2': strong_password,
            },
            format='json',
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)

    def test_login_is_rate_limited(self):
        User.objects.create_user(
            username='buyer',
            email='buyer@example.com',
            password='password123',
        )

        first = self.client.post(
            '/api/auth/login/',
            {'email': 'buyer@example.com', 'password': 'wrong-password'},
            format='json',
            HTTP_ORIGIN='http://localhost:3000',
        )
        second = self.client.post(
            '/api/auth/login/',
            {'email': 'buyer@example.com', 'password': 'wrong-password'},
            format='json',
            HTTP_ORIGIN='http://localhost:3000',
        )

        self.assertEqual(first.status_code, 401)
        self.assertEqual(second.status_code, 429)

    def test_heartbeat_is_rate_limited_per_authenticated_user(self):
        user = User.objects.create_user(username='buyer', password='password123')
        self.client.force_authenticate(user=user)

        first = self.client.post('/api/heartbeat/', {}, format='json')
        second = self.client.post('/api/heartbeat/', {}, format='json')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_chat_message_send_is_rate_limited_per_authenticated_user(self):
        buyer = User.objects.create_user(username='buyer', password='password123')
        seller = User.objects.create_user(username='seller', password='password123')
        conversation = Conversation.objects.create()
        conversation.participants.add(buyer, seller)
        self.client.force_authenticate(user=buyer)

        first = self.client.post(
            f'/api/chat/{conversation.id}/send/',
            {'content': 'hello'},
            format='json',
        )
        second = self.client.post(
            f'/api/chat/{conversation.id}/send/',
            {'content': 'again'},
            format='json',
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)

    def test_chat_websocket_ticket_is_rate_limited_per_authenticated_user(self):
        buyer = User.objects.create_user(username='ticket_buyer', password='password123')
        seller = User.objects.create_user(username='ticket_seller', password='password123')
        conversation = Conversation.objects.create()
        conversation.participants.add(buyer, seller)
        self.client.force_authenticate(user=buyer)

        first = self.client.post(
            f'/api/chat/{conversation.id}/ws-ticket/',
            {},
            format='json',
        )
        second = self.client.post(
            f'/api/chat/{conversation.id}/ws-ticket/',
            {},
            format='json',
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_search_is_rate_limited(self):
        first = self.client.get('/api/search/?q=Valorant')
        second = self.client.get('/api/search/?q=Valorant')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_support_ticket_is_rate_limited(self):
        payload = {
            'email': 'guest@example.com',
            'category': 'other',
            'subject': 'Need help',
            'message': 'Please help me with my account.',
        }

        first = self.client.post('/api/support/', payload, format='json')
        second = self.client.post('/api/support/', payload, format='json')

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)


class HeartbeatUpdateTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(username='buyer', password='password123')
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        cache.clear()

    def test_repeated_heartbeat_does_not_rewrite_recent_last_active(self):
        first = self.client.post('/api/heartbeat/', {}, format='json')
        self.user.profile.refresh_from_db()
        first_last_active = self.user.profile.last_active

        second = self.client.post('/api/heartbeat/', {}, format='json')
        self.user.profile.refresh_from_db()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(first.data['updated'])
        self.assertFalse(second.data['updated'])
        self.assertEqual(self.user.profile.last_active, first_last_active)


class RegistrationPasswordValidationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_rejects_password_failing_django_validators(self):
        response = self.client.post(
            '/api/auth/register/',
            {
                'username': 'weakbuyer',
                'email': 'weakbuyer@example.com',
                'password': 'short7',
                'password2': 'short7',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('password', response.data)
        self.assertFalse(User.objects.filter(username='weakbuyer').exists())

    def test_register_accepts_strong_password(self):
        strong_password = 'S3cure!Passphrase42'
        response = self.client.post(
            '/api/auth/register/',
            {
                'username': 'strongbuyer',
                'email': 'strongbuyer@example.com',
                'password': strong_password,
                'password2': strong_password,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(username='strongbuyer').exists())

    def test_register_rejects_case_insensitive_duplicate_username(self):
        User.objects.create_user(
            username='SellerName',
            email='seller-name@example.com',
            password='password123',
        )
        strong_password = 'S3cure!Passphrase42'

        response = self.client.post(
            '/api/auth/register/',
            {
                'username': ' sellername ',
                'email': 'seller-name-2@example.com',
                'password': strong_password,
                'password2': strong_password,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('username', response.data)

    def test_register_uses_django_username_validator(self):
        strong_password = 'S3cure!Passphrase42'
        response = self.client.post(
            '/api/auth/register/',
            {
                'username': 'bad/name',
                'email': 'bad-name@example.com',
                'password': strong_password,
                'password2': strong_password,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('username', response.data)

    def test_user_email_unique_constraint_is_case_insensitive(self):
        User.objects.create_user(
            username='casebuyer',
            email='unique-case@example.com',
            password='password123',
        )

        with self.assertRaises(IntegrityError):
            with db_transaction.atomic():
                User.objects.create_user(
                    username='casebuyer2',
                    email=' UNIQUE-CASE@example.com ',
                    password='password123',
                )


class CookieJWTAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='cookiebuyer',
            email='cookiebuyer@example.com',
            password='password123',
        )

    def login(self):
        return self.client.post(
            '/api/auth/login/',
            {'email': 'cookiebuyer@example.com', 'password': 'password123'},
            format='json',
            HTTP_ORIGIN='http://localhost:3000',
        )

    def test_login_sets_httponly_auth_cookies(self):
        response = self.login()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'message': 'Logged in.'})
        self.assertNotIn('access', response.data)
        self.assertNotIn('refresh', response.data)

        access_cookie = response.cookies[settings.JWT_AUTH_COOKIE_ACCESS]
        refresh_cookie = response.cookies[settings.JWT_AUTH_COOKIE_REFRESH]
        for cookie in (access_cookie, refresh_cookie):
            self.assertTrue(cookie['httponly'])
            self.assertFalse(cookie['secure'])
            self.assertEqual(cookie['samesite'], 'Lax')
            self.assertEqual(cookie['path'], settings.JWT_AUTH_COOKIE_PATH)

    def test_me_works_from_access_cookie(self):
        login_response = self.login()
        self.assertEqual(login_response.status_code, 200)

        response = self.client.get('/api/auth/me/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['username'], 'cookiebuyer')

    def test_refresh_works_from_refresh_cookie(self):
        login_response = self.login()
        self.assertEqual(login_response.status_code, 200)
        self.client.cookies[settings.JWT_AUTH_COOKIE_ACCESS] = 'not-a-valid-access-token'

        response = self.client.post(
            '/api/auth/refresh/',
            {},
            format='json',
            HTTP_ORIGIN='http://localhost:3000',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'message': 'Token refreshed.'})
        self.assertNotIn('access', response.data)
        self.assertNotIn('refresh', response.data)
        self.assertIn(settings.JWT_AUTH_COOKIE_ACCESS, response.cookies)
        self.assertIn(settings.JWT_AUTH_COOKIE_REFRESH, response.cookies)

    def test_refresh_rotation_blacklists_old_refresh_token(self):
        login_response = self.login()
        self.assertEqual(login_response.status_code, 200)
        old_refresh = login_response.cookies[settings.JWT_AUTH_COOKIE_REFRESH].value

        first_refresh = self.client.post(
            '/api/auth/refresh/',
            {},
            format='json',
            HTTP_ORIGIN='http://localhost:3000',
        )

        self.assertEqual(first_refresh.status_code, 200)
        self.assertNotIn('refresh', first_refresh.data)
        self.assertIn(settings.JWT_AUTH_COOKIE_REFRESH, first_refresh.cookies)
        self.assertNotEqual(
            first_refresh.cookies[settings.JWT_AUTH_COOKIE_REFRESH].value,
            old_refresh,
        )

        old_refresh_reuse = self.client.post(
            '/api/auth/refresh/',
            {'refresh': old_refresh},
            format='json',
            HTTP_ORIGIN='http://localhost:3000',
        )

        self.assertEqual(old_refresh_reuse.status_code, 401)

    def test_password_change_blacklists_existing_refresh_tokens(self):
        login_response = self.login()
        self.assertEqual(login_response.status_code, 200)
        old_refresh = login_response.cookies[settings.JWT_AUTH_COOKIE_REFRESH].value

        response = self.client.post(
            '/api/auth/password/',
            {
                'current_password': 'password123',
                'new_password': 'BetterPass123!x',
                'new_password2': 'BetterPass123!x',
            },
            format='json',
            HTTP_ORIGIN='http://localhost:3000',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(settings.JWT_AUTH_COOKIE_REFRESH, response.cookies)
        self.assertNotEqual(
            response.cookies[settings.JWT_AUTH_COOKIE_REFRESH].value,
            old_refresh,
        )

        old_refresh_reuse = self.client.post(
            '/api/auth/refresh/',
            {'refresh': old_refresh},
            format='json',
            HTTP_ORIGIN='http://localhost:3000',
        )
        self.assertEqual(old_refresh_reuse.status_code, 401)

    def test_logout_clears_auth_cookies(self):
        login_response = self.login()
        self.assertEqual(login_response.status_code, 200)

        response = self.client.post(
            '/api/auth/logout/',
            {},
            format='json',
            HTTP_ORIGIN='http://localhost:3000',
        )

        self.assertEqual(response.status_code, 200)
        for cookie_name in (settings.JWT_AUTH_COOKIE_ACCESS, settings.JWT_AUTH_COOKIE_REFRESH):
            self.assertIn(cookie_name, response.cookies)
            self.assertEqual(response.cookies[cookie_name].value, '')
            self.assertEqual(response.cookies[cookie_name]['max-age'], 0)

    def test_bearer_token_auth_still_works(self):
        from rest_framework_simplejwt.tokens import AccessToken

        access = AccessToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.get('/api/auth/me/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['username'], 'cookiebuyer')

    def test_cookie_auth_rejects_untrusted_origin_for_unsafe_request(self):
        login_response = self.login()
        self.assertEqual(login_response.status_code, 200)

        response = self.client.post(
            '/api/heartbeat/',
            {},
            format='json',
            HTTP_ORIGIN='https://evil.example',
        )

        self.assertEqual(response.status_code, 403)

    def test_cookie_auth_rejects_missing_origin_and_referer_for_unsafe_request(self):
        login_response = self.login()
        self.assertEqual(login_response.status_code, 200)

        response = self.client.post(
            '/api/heartbeat/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, 403)

    def test_cookie_auth_allows_trusted_referer_when_origin_is_missing(self):
        login_response = self.login()
        self.assertEqual(login_response.status_code, 200)

        response = self.client.post(
            '/api/heartbeat/',
            {},
            format='json',
            HTTP_REFERER='http://localhost:3000/account',
        )

        self.assertEqual(response.status_code, 200)


class CommissionRateValidationTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(username='seller', password='password123')
        self.category = Category.objects.create(name='Accounts', slug='accounts')

    def test_category_commission_rate_must_be_between_zero_and_one_hundred(self):
        for rate in (Decimal('-0.01'), Decimal('100.01')):
            with self.subTest(rate=rate):
                category = Category(name=f'Invalid {rate}', slug=f'invalid-{str(rate).replace(".", "-")}',
                                    commission_rate=rate)
                with self.assertRaises(ValidationError):
                    category.full_clean()
                with self.assertRaises(IntegrityError):
                    with db_transaction.atomic():
                        Category.objects.create(
                            name=f'DB Invalid {rate}',
                            slug=f'db-invalid-{str(rate).replace(".", "-")}',
                            commission_rate=rate,
                        )

    def test_seller_override_commission_rate_must_be_between_zero_and_one_hundred(self):
        for rate in (Decimal('-0.01'), Decimal('100.01')):
            with self.subTest(rate=rate):
                override = SellerCommissionOverride(
                    seller=self.seller,
                    category=self.category,
                    commission_rate=rate,
                )
                with self.assertRaises(ValidationError):
                    override.full_clean()
                with self.assertRaises(IntegrityError):
                    with db_transaction.atomic():
                        SellerCommissionOverride.objects.create(
                            seller=self.seller,
                            category=self.category,
                            commission_rate=rate,
                        )

    def test_commission_rate_boundaries_are_valid(self):
        for rate in (Decimal('0.00'), Decimal('100.00')):
            with self.subTest(rate=rate):
                category = Category(
                    name=f'Boundary {rate}',
                    slug=f'boundary-{str(rate).replace(".", "-")}',
                    commission_rate=rate,
                )
                category.full_clean()


class TopUpAmountValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='buyer', password='password123')

    def test_topup_amount_must_be_at_least_one(self):
        for amount in (Decimal('0.00'), Decimal('-0.01')):
            with self.subTest(amount=amount):
                topup = TopUpRequest(user=self.user, amount=amount)
                with self.assertRaises(ValidationError):
                    topup.full_clean()
                with self.assertRaises(IntegrityError):
                    with db_transaction.atomic():
                        TopUpRequest.objects.create(user=self.user, amount=amount)

    def test_topup_amount_minimum_boundary_is_valid(self):
        topup = TopUpRequest(user=self.user, amount=Decimal('1.00'))

        topup.full_clean()
        topup.save()

        self.assertEqual(topup.amount, Decimal('1.00'))


class GameCategoryListingPaginationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.seller = User.objects.create_user(username='seller', password='password123')
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])

        self.game = Game.objects.create(name='Test Game', slug='test-game')
        self.category = Category.objects.create(name='Accounts', slug='accounts')
        self.game_category = GameCategory.objects.create(game=self.game, category=self.category)

        rank_filter = Filter.objects.create(name='Rank', filter_type='button')
        self.gold = FilterOption.objects.create(
            filter=rank_filter,
            label='Gold',
            value='gold',
        )

        for index in range(3):
            Listing.objects.create(
                seller=self.seller,
                game_category=self.game_category,
                title=f'Listing {index}',
                price=Decimal('10.00'),
                quantity=1,
                status='active',
                filter_values={str(rank_filter.id): 'gold'},
            )

    def test_category_listings_are_paginated_with_filter_display(self):
        response = self.client.get('/api/games/test-game/accounts/?limit=2')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['listings']), 2)
        self.assertEqual(response.data['listing_pagination'], {
            'count': 3,
            'limit': 2,
            'offset': 0,
            'next_offset': 2,
            'previous_offset': None,
        })
        self.assertEqual(response.data['listings'][0]['filter_display'], {'Rank': 'Gold'})

        second_page = self.client.get('/api/games/test-game/accounts/?limit=2&offset=2')

        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(len(second_page.data['listings']), 1)
        self.assertEqual(second_page.data['listing_pagination']['next_offset'], None)
        self.assertEqual(second_page.data['listing_pagination']['previous_offset'], 0)

    def test_seller_filter_scopes_sibling_category_counts(self):
        other_seller = User.objects.create_user(username='other_seller', password='password123')
        other_seller.profile.seller_status = 'approved'
        other_seller.profile.save(update_fields=['seller_status'])
        boosting = Category.objects.create(name='Boosting', slug='boosting')
        boosting_game_category = GameCategory.objects.create(
            game=self.game,
            category=boosting,
            order=2,
        )

        for index in range(2):
            Listing.objects.create(
                seller=other_seller,
                game_category=self.game_category,
                title=f'Other Seller Account {index}',
                price=Decimal('12.00'),
                quantity=1,
                status='active',
            )
        Listing.objects.create(
            seller=self.seller,
            game_category=boosting_game_category,
            title='Seller Boosting',
            price=Decimal('15.00'),
            quantity=1,
            status='active',
        )
        Listing.objects.create(
            seller=other_seller,
            game_category=boosting_game_category,
            title='Other Seller Boosting',
            price=Decimal('20.00'),
            quantity=1,
            status='active',
        )

        response = self.client.get('/api/games/test-game/accounts/?seller=seller')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['listing_pagination']['count'], 3)
        category_counts = {
            category['slug']: category['listing_count']
            for category in response.data['all_categories']
        }
        self.assertEqual(category_counts['accounts'], 3)
        self.assertEqual(category_counts['boosting'], 1)


class MyListingsPaginationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.seller = User.objects.create_user(username='seller', password='password123')
        self.other_seller = User.objects.create_user(username='other_seller', password='password123')
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])

        game = Game.objects.create(name='Test Game', slug='test-game')
        category = Category.objects.create(name='Accounts', slug='accounts')
        self.game_category = GameCategory.objects.create(game=game, category=category)

        for index in range(5):
            Listing.objects.create(
                seller=self.seller,
                game_category=self.game_category,
                title=f'My listing {index}',
                price=Decimal('10.00'),
                quantity=1,
                status='sold' if index == 0 else 'active',
            )
        Listing.objects.create(
            seller=self.other_seller,
            game_category=self.game_category,
            title='Other seller listing',
            price=Decimal('10.00'),
            quantity=1,
            status='active',
        )

    def test_my_listings_are_paginated_with_summary(self):
        self.client.force_authenticate(user=self.seller)
        response = self.client.get('/api/listings/mine/?limit=2')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['listings']), 2)
        self.assertEqual(response.data['pagination'], {
            'count': 5,
            'limit': 2,
            'offset': 0,
            'next_offset': 2,
            'previous_offset': None,
        })
        self.assertEqual(response.data['summary'], {
            'active_count': 4,
            'sold_count': 1,
            'inactive_count': 0,
            'total_count': 5,
        })
        self.assertEqual(response.data['status_counts'], {
            'active': 4,
            'inactive': 0,
            'sold': 1,
        })
        self.assertEqual(response.data['seller_games'], [{
            'slug': 'test-game',
            'name': 'Test Game',
            'listing_count': 5,
            'categories': [{
                'slug': 'accounts',
                'name': 'Accounts',
                'icon': '',
                'listing_count': 5,
            }],
        }])

        second_page = self.client.get('/api/listings/mine/?limit=2&offset=2')

        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(len(second_page.data['listings']), 2)
        self.assertEqual(second_page.data['pagination']['next_offset'], 4)
        self.assertEqual(second_page.data['pagination']['previous_offset'], 0)

    def test_my_listings_filters_and_optional_facets(self):
        self.client.force_authenticate(user=self.seller)

        status_response = self.client.get('/api/listings/mine/?status=sold')

        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.data['pagination']['count'], 1)
        self.assertEqual(
            {listing['status'] for listing in status_response.data['listings']},
            {'sold'},
        )
        self.assertEqual(status_response.data['summary']['total_count'], 5)

        no_facets_response = self.client.get('/api/listings/mine/?limit=2&offset=2&include_facets=0')

        self.assertEqual(no_facets_response.status_code, 200)
        self.assertEqual(len(no_facets_response.data['listings']), 2)
        self.assertNotIn('summary', no_facets_response.data)
        self.assertNotIn('status_counts', no_facets_response.data)
        self.assertNotIn('seller_games', no_facets_response.data)


class AccessControlTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.buyer = User.objects.create_user(username='buyer', password='password123')
        self.seller = User.objects.create_user(username='seller', password='password123')
        self.other_seller = User.objects.create_user(username='other_seller', password='password123')
        self.intruder = User.objects.create_user(username='intruder', password='password123')

        for user in (self.seller, self.other_seller):
            user.profile.seller_status = 'approved'
            user.profile.save(update_fields=['seller_status'])

        game = Game.objects.create(name='Test Game', slug='test-game')
        category = Category.objects.create(
            name='Accounts',
            slug='accounts',
            commission_rate=Decimal('0.00'),
        )
        self.game_category = GameCategory.objects.create(game=game, category=category)

        self.listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Seller listing',
            price=Decimal('50.00'),
            quantity=2,
            status='active',
        )
        self.order = Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            listing=self.listing,
            listing_title=self.listing.title,
            quantity=1,
            unit_price=Decimal('50.00'),
            total_amount=Decimal('50.00'),
            commission_rate=Decimal('0.00'),
            commission_amount=Decimal('0.00'),
            seller_amount=Decimal('50.00'),
            status='pending',
        )
        self.conversation = Conversation.objects.create()
        self.conversation.participants.add(self.buyer, self.seller)

    def test_non_seller_cannot_create_listing(self):
        self.client.force_authenticate(user=self.buyer)

        response = self.client.post(
            '/api/listings/',
            {
                'game_slug': 'test-game',
                'category_slug': 'accounts',
                'title': 'Buyer listing',
                'price': '10.00',
                'quantity': 1,
                'filter_values': {},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Listing.objects.filter(title='Buyer listing').exists())

    def test_seller_cannot_edit_or_delete_another_sellers_listing(self):
        self.client.force_authenticate(user=self.other_seller)

        edit_response = self.client.put(
            f'/api/listings/{self.listing.id}/',
            {'title': 'Stolen listing'},
            format='json',
        )
        delete_response = self.client.delete(f'/api/listings/{self.listing.id}/')

        self.assertEqual(edit_response.status_code, 404)
        self.assertEqual(delete_response.status_code, 404)

        self.listing.refresh_from_db()
        self.assertEqual(self.listing.title, 'Seller listing')
        self.assertTrue(Listing.objects.filter(pk=self.listing.pk).exists())

    def test_listing_detail_hides_inactive_or_sold_listings_from_outsiders(self):
        active_response = self.client.get(f'/api/listings/{self.listing.id}/')
        self.assertEqual(active_response.status_code, 200)

        self.listing.status = 'sold'
        self.listing.save(update_fields=['status'])

        anon_response = self.client.get(f'/api/listings/{self.listing.id}/')
        self.assertEqual(anon_response.status_code, 404)

        self.client.force_authenticate(user=self.buyer)
        outsider_response = self.client.get(f'/api/listings/{self.listing.id}/')
        self.assertEqual(outsider_response.status_code, 404)

        self.client.force_authenticate(user=self.seller)
        owner_response = self.client.get(f'/api/listings/{self.listing.id}/')
        self.assertEqual(owner_response.status_code, 200)

        staff = User.objects.create_user(
            username='staff_user',
            password='password123',
            is_staff=True,
        )
        self.client.force_authenticate(user=staff)
        staff_response = self.client.get(f'/api/listings/{self.listing.id}/')
        self.assertEqual(staff_response.status_code, 200)

    def test_order_delivery_note_and_dispute_reason_have_length_limits(self):
        self.client.force_authenticate(user=self.seller)
        deliver_response = self.client.post(
            f'/api/orders/{self.order.id}/deliver/',
            {'delivery_note': 'x' * (MAX_DELIVERY_NOTE_LENGTH + 1)},
            format='json',
        )
        self.assertEqual(deliver_response.status_code, 400)

        self.client.force_authenticate(user=self.buyer)
        dispute_response = self.client.post(
            f'/api/orders/{self.order.id}/dispute/',
            {'reason': 'x' * (MAX_DISPUTE_REASON_LENGTH + 1)},
            format='json',
        )
        self.assertEqual(dispute_response.status_code, 400)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')

    def test_intruder_cannot_view_or_mutate_order(self):
        self.client.force_authenticate(user=self.intruder)

        detail_response = self.client.get(f'/api/orders/{self.order.id}/')
        deliver_response = self.client.post(
            f'/api/orders/{self.order.id}/deliver/',
            {'delivery_note': 'not yours'},
            format='json',
        )
        confirm_response = self.client.post(
            f'/api/orders/{self.order.id}/confirm/',
            {},
            format='json',
        )
        dispute_response = self.client.post(
            f'/api/orders/{self.order.id}/dispute/',
            {'reason': 'not yours'},
            format='json',
        )
        refund_response = self.client.post(
            f'/api/orders/{self.order.id}/refund/',
            {},
            format='json',
        )

        self.assertEqual(detail_response.status_code, 403)
        self.assertEqual(deliver_response.status_code, 404)
        self.assertEqual(confirm_response.status_code, 404)
        self.assertEqual(dispute_response.status_code, 404)
        self.assertEqual(refund_response.status_code, 404)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')

    def test_buyer_and_seller_cannot_use_wrong_order_actions(self):
        self.client.force_authenticate(user=self.buyer)
        buyer_deliver_response = self.client.post(
            f'/api/orders/{self.order.id}/deliver/',
            {'delivery_note': 'buyer cannot deliver'},
            format='json',
        )
        buyer_refund_response = self.client.post(
            f'/api/orders/{self.order.id}/refund/',
            {},
            format='json',
        )

        self.client.force_authenticate(user=self.seller)
        seller_confirm_response = self.client.post(
            f'/api/orders/{self.order.id}/confirm/',
            {},
            format='json',
        )
        seller_dispute_response = self.client.post(
            f'/api/orders/{self.order.id}/dispute/',
            {'reason': 'seller cannot dispute as buyer'},
            format='json',
        )

        self.assertEqual(buyer_deliver_response.status_code, 404)
        self.assertEqual(buyer_refund_response.status_code, 404)
        self.assertEqual(seller_confirm_response.status_code, 404)
        self.assertEqual(seller_dispute_response.status_code, 404)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')

    def test_buyer_cannot_confirm_pending_order(self):
        self.client.force_authenticate(user=self.buyer)

        response = self.client.post(
            f'/api/orders/{self.order.id}/confirm/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')
        seller_wallet = Wallet.objects.get(user=self.seller)
        self.assertEqual(seller_wallet.balance, Decimal('0.00'))

    def test_chat_non_participant_cannot_read_or_send(self):
        self.client.force_authenticate(user=self.intruder)

        detail_response = self.client.get(f'/api/chat/{self.conversation.id}/')
        send_response = self.client.post(
            f'/api/chat/{self.conversation.id}/send/',
            {'content': 'not your chat'},
            format='json',
        )
        image_response = self.client.post(
            f'/api/chat/{self.conversation.id}/send-image/',
            {'image': make_image_file()},
            format='multipart',
        )

        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(send_response.status_code, 404)
        self.assertEqual(image_response.status_code, 404)
        self.assertFalse(Message.objects.filter(content='not your chat').exists())

    def test_chat_text_message_rejects_overlong_content(self):
        from .services import MAX_CHAT_MESSAGE_LENGTH

        self.client.force_authenticate(user=self.buyer)
        response = self.client.post(
            f'/api/chat/{self.conversation.id}/send/',
            {'content': 'x' * (MAX_CHAT_MESSAGE_LENGTH + 1)},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.data)
        self.assertFalse(Message.objects.filter(conversation=self.conversation).exists())

        start_response = self.client.post(
            '/api/chat/start/',
            {
                'user_id': self.seller.id,
                'message': 'x' * (MAX_CHAT_MESSAGE_LENGTH + 1),
            },
            format='json',
        )

        self.assertEqual(start_response.status_code, 400)
        self.assertIn('error', start_response.data)
        self.assertFalse(Message.objects.filter(conversation=self.conversation).exists())

    def test_start_conversation_rejects_invalid_user_id(self):
        self.client.force_authenticate(user=self.buyer)
        before_count = Conversation.objects.count()

        non_numeric_response = self.client.post(
            '/api/chat/start/',
            {'user_id': 'abc', 'message': 'hello'},
            format='json',
        )
        zero_response = self.client.post(
            '/api/chat/start/',
            {'user_id': 0, 'message': 'hello'},
            format='json',
        )
        negative_response = self.client.post(
            '/api/chat/start/',
            {'user_id': -1, 'message': 'hello'},
            format='json',
        )

        self.assertEqual(non_numeric_response.status_code, 400)
        self.assertEqual(zero_response.status_code, 400)
        self.assertEqual(negative_response.status_code, 400)
        self.assertEqual(Conversation.objects.count(), before_count)
        self.assertFalse(Message.objects.filter(content='hello').exists())

    def test_chat_image_is_served_through_private_endpoint(self):
        message = Message.objects.create(
            conversation=self.conversation,
            sender=self.buyer,
            image=make_image_file(name='chat.png'),
        )

        self.client.force_authenticate(user=self.buyer)
        detail_response = self.client.get(f'/api/chat/{self.conversation.id}/')
        self.assertEqual(detail_response.status_code, 200)

        image_url = next(
            msg['image_url']
            for msg in detail_response.data['messages']
            if msg['id'] == message.id
        )
        self.assertIn(f'/api/chat/messages/{message.pk}/image/', image_url)
        self.assertNotIn('/media/', image_url)

        signed_response = self.client.get(path_with_query(image_url))
        self.assertEqual(signed_response.status_code, 200)

        self.client.force_authenticate(user=None)
        unauthenticated_signed_response = self.client.get(path_with_query(image_url))
        self.assertEqual(unauthenticated_signed_response.status_code, 404)

        self.client.force_authenticate(user=self.intruder)
        signed_response = self.client.get(path_with_query(image_url))
        self.assertEqual(signed_response.status_code, 404)

        unsigned_response = self.client.get(f'/api/chat/messages/{message.pk}/image/')
        self.assertEqual(unsigned_response.status_code, 404)

        self.client.force_authenticate(user=self.seller)
        participant_response = self.client.get(f'/api/chat/messages/{message.pk}/image/')
        self.assertEqual(participant_response.status_code, 200)

    def test_conversation_detail_messages_are_paginated_from_latest(self):
        for index in range(60):
            Message.objects.create(
                conversation=self.conversation,
                sender=self.seller if index % 2 else self.buyer,
                content=f'msg-{index:02d}',
            )

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get(f'/api/chat/{self.conversation.id}/?limit=10')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['messages']), 10)
        self.assertEqual(response.data['messages'][0]['content'], 'msg-50')
        self.assertEqual(response.data['messages'][-1]['content'], 'msg-59')
        self.assertEqual(response.data['message_pagination']['count'], 60)
        self.assertEqual(
            response.data['message_pagination']['next_before_id'],
            response.data['messages'][0]['id'],
        )

        Message.objects.create(
            conversation=self.conversation,
            sender=self.seller,
            content='msg-60',
        )

        before_id = response.data['message_pagination']['next_before_id']
        older_response = self.client.get(
            f'/api/chat/{self.conversation.id}/?limit=10&before_id={before_id}'
        )

        self.assertEqual(older_response.status_code, 200)
        self.assertEqual(older_response.data['messages'][0]['content'], 'msg-40')
        self.assertEqual(older_response.data['messages'][-1]['content'], 'msg-49')

    def test_conversation_list_includes_last_message_and_unread_count(self):
        Message.objects.create(
            conversation=self.conversation,
            sender=self.seller,
            content='first unread seller message',
        )
        Message.objects.create(
            conversation=self.conversation,
            sender=self.buyer,
            content='latest buyer message',
        )

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get('/api/chat/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['conversations']), 1)
        self.assertEqual(response.data['pagination']['count'], 1)
        self.assertEqual(response.data['conversations'][0]['unread_count'], 1)
        self.assertEqual(response.data['conversations'][0]['last_message']['content'], 'latest buyer message')
        self.assertEqual(response.data['conversations'][0]['other_user']['id'], self.seller.id)

    def test_conversation_list_orders_by_newest_message(self):
        old_conversation = self.conversation
        newer_conversation = Conversation.objects.create()
        newer_conversation.participants.add(self.buyer, self.other_seller)

        Message.objects.create(
            conversation=old_conversation,
            sender=self.seller,
            content='older chat message',
        )
        Message.objects.create(
            conversation=newer_conversation,
            sender=self.other_seller,
            content='newer chat message',
        )
        Message.objects.create(
            conversation=old_conversation,
            sender=self.buyer,
            content='old chat is newest now',
        )
        old_conversation.save()

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get('/api/chat/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['conversations'][0]['id'], old_conversation.id)
        self.assertEqual(response.data['conversations'][0]['last_message']['content'], 'old chat is newest now')
        self.assertEqual(response.data['conversations'][1]['id'], newer_conversation.id)

    def test_conversation_list_supports_pagination(self):
        third_seller = User.objects.create_user(
            username='third_seller',
            password='password123',
        )
        conversations = []
        for seller in (self.seller, self.other_seller, third_seller):
            conversation = (
                self.conversation
                if seller == self.seller else Conversation.objects.create()
            )
            if seller != self.seller:
                conversation.participants.add(self.buyer, seller)
            Message.objects.create(
                conversation=conversation,
                sender=seller,
                content=f'message from {seller.username}',
            )
            conversations.append(conversation)

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get('/api/chat/?limit=2')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['conversations']), 2)
        self.assertEqual(response.data['pagination']['count'], len(conversations))
        self.assertEqual(response.data['pagination']['next_offset'], 2)

    def test_conversation_list_can_filter_by_other_user(self):
        other_conversation = Conversation.objects.create()
        other_conversation.participants.add(self.buyer, self.other_seller)

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get(
            f'/api/chat/?other_user_id={self.other_seller.id}&limit=1'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['pagination']['count'], 1)
        self.assertEqual(len(response.data['conversations']), 1)
        self.assertEqual(response.data['conversations'][0]['id'], other_conversation.id)
        self.assertEqual(
            response.data['conversations'][0]['other_user']['id'],
            self.other_seller.id,
        )

    def test_chat_websocket_ticket_is_scoped_to_participant_and_conversation(self):
        from .services import CHAT_WS_TICKET_MAX_AGE_SECONDS, decode_chat_ws_ticket

        self.client.force_authenticate(user=self.buyer)
        response = self.client.post(
            f'/api/chat/{self.conversation.id}/ws-ticket/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['expires_in'], CHAT_WS_TICKET_MAX_AGE_SECONDS)

        payload = decode_chat_ws_ticket(response.data['ticket'])
        self.assertEqual(payload['user_id'], self.buyer.id)
        self.assertEqual(payload['conversation_id'], self.conversation.id)
        self.assertTrue(payload['nonce'])

        self.client.force_authenticate(user=self.intruder)
        intruder_response = self.client.post(
            f'/api/chat/{self.conversation.id}/ws-ticket/',
            {},
            format='json',
        )

        self.assertEqual(intruder_response.status_code, 404)


class HistoryPaginationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.buyer = User.objects.create_user(username='buyer', password='password123')
        self.seller = User.objects.create_user(username='seller', password='password123')

    def create_order(self, index, status='pending', seller_amount=Decimal('10.00')):
        return Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            listing_title=f'Order {index}',
            quantity=1,
            unit_price=Decimal('10.00'),
            total_amount=Decimal('10.00'),
            commission_rate=Decimal('0.00'),
            commission_amount=Decimal('0.00'),
            seller_amount=seller_amount,
            status=status,
        )

    def test_wallet_transactions_are_paginated(self):
        wallet = Wallet.objects.get(user=self.buyer)
        for index in range(30):
            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type='refund',
                amount=Decimal('1.00'),
                balance_after=Decimal(index),
                reference_id=f'tx-{index}',
            )

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get('/api/wallet/transactions/?limit=10')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['transactions']), 10)
        self.assertEqual(response.data['pagination']['count'], 30)
        self.assertEqual(response.data['pagination']['next_offset'], 10)

    def test_topup_requests_are_paginated_for_current_user(self):
        other_user = User.objects.create_user(username='other', password='password123')
        for index in range(30):
            TopUpRequest.objects.create(
                user=self.buyer,
                amount=Decimal('100.00'),
                transaction_id=f'buyer-topup-{index}',
            )
        TopUpRequest.objects.create(
            user=other_user,
            amount=Decimal('100.00'),
            transaction_id='other-topup',
        )

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get('/api/wallet/top-up/?limit=10')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['topup_requests']), 10)
        self.assertEqual(response.data['pagination']['count'], 30)
        self.assertEqual(response.data['pagination']['next_offset'], 10)

    def test_withdraw_requests_are_paginated_for_current_user(self):
        other_user = User.objects.create_user(username='other', password='password123')
        for index in range(30):
            WithdrawRequest.objects.create(
                user=self.buyer,
                amount=Decimal('500.00'),
                payment_method='JazzCash',
                account_title='Buyer Account',
                account_details=f'03001234{index:02d}',
            )
        WithdrawRequest.objects.create(
            user=other_user,
            amount=Decimal('500.00'),
            payment_method='JazzCash',
            account_title='Other Account',
            account_details='03009999999',
        )

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get('/api/wallet/withdraw/?limit=10')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['withdraw_requests']), 10)
        self.assertEqual(response.data['pagination']['count'], 30)
        self.assertEqual(response.data['pagination']['next_offset'], 10)

    def test_buyer_orders_are_paginated(self):
        for index in range(25):
            self.create_order(index)

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get('/api/orders/mine/?limit=10')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['orders']), 10)
        self.assertEqual(response.data['pagination']['count'], 25)
        self.assertEqual(response.data['pagination']['next_offset'], 10)

    def test_buyer_orders_support_cursor_pagination_without_count(self):
        for index in range(25):
            self.create_order(index)

        self.client.force_authenticate(user=self.buyer)
        first_page = self.client.get('/api/orders/mine/?limit=10&cursor=1')

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(len(first_page.data['orders']), 10)
        self.assertIsNone(first_page.data['pagination']['count'])
        before_id = first_page.data['pagination']['next_before_id']
        self.assertIsNotNone(before_id)

        second_page = self.client.get(f'/api/orders/mine/?limit=10&before_id={before_id}')
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(len(second_page.data['orders']), 10)
        self.assertLess(second_page.data['orders'][0]['id'], before_id)

    def test_buyer_orders_ignore_invalid_date_filters(self):
        self.create_order(1)

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get('/api/orders/mine/?date_from=not-a-date&date_to=also-bad')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['pagination']['count'], 1)

    def test_seller_sales_are_paginated_with_summary(self):
        for index in range(5):
            self.create_order(index, status='pending')
        for index in range(5, 8):
            self.create_order(index, status='completed', seller_amount=Decimal('10.00'))

        self.client.force_authenticate(user=self.seller)
        response = self.client.get('/api/orders/sales/?limit=4')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['sales']), 4)
        self.assertEqual(response.data['pagination']['count'], 8)
        self.assertEqual(response.data['pagination']['next_offset'], 4)
        self.assertEqual(response.data['summary']['pending_count'], 5)
        self.assertEqual(response.data['summary']['completed_count'], 3)
        self.assertEqual(response.data['summary']['total_revenue'], '30.00')

    def test_seller_sales_ignore_invalid_date_filters(self):
        self.create_order(1)

        self.client.force_authenticate(user=self.seller)
        response = self.client.get('/api/orders/sales/?date_from=not-a-date&date_to=also-bad')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['pagination']['count'], 1)


class ChatWebSocketTicketIntegrationTests(TransactionTestCase):
    reset_sequences = True
    websocket_test_origin = b'http://localhost:3000'

    def setUp(self):
        cache.clear()
        self.buyer = User.objects.create_user(username='buyer', password='password123')
        self.seller = User.objects.create_user(username='seller', password='password123')
        self.intruder = User.objects.create_user(username='intruder', password='password123')
        self.conversation = Conversation.objects.create()
        self.conversation.participants.add(self.buyer, self.seller)
        self.other_conversation = Conversation.objects.create()
        self.other_conversation.participants.add(self.buyer, self.intruder)

    def tearDown(self):
        cache.clear()

    def make_websocket_communicator(self, application, path):
        from channels.testing import WebsocketCommunicator
        return WebsocketCommunicator(
            application,
            path,
            headers=[(b'origin', self.websocket_test_origin)],
        )

    def test_websocket_accepts_scoped_ticket_and_rejects_raw_jwt(self):
        from asgiref.sync import async_to_sync
        from channels.testing import WebsocketCommunicator
        from gamesbazaar.asgi import application
        from rest_framework_simplejwt.tokens import AccessToken

        from .services import create_chat_ws_ticket

        async def run_ticket_flow():
            ticket = create_chat_ws_ticket(self.buyer, self.conversation.id)
            communicator = self.make_websocket_communicator(
                application,
                f'/ws/chat/{self.conversation.id}/?ticket={ticket}',
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            await communicator.send_json_to({
                'type': 'chat_message',
                'content': 'hello over ticket',
            })
            event = await communicator.receive_json_from()
            self.assertEqual(event['type'], 'new_message')
            self.assertEqual(event['message']['content'], 'hello over ticket')
            await communicator.disconnect()

            replay_communicator = self.make_websocket_communicator(
                application,
                f'/ws/chat/{self.conversation.id}/?ticket={ticket}',
            )
            replay_connected, _ = await replay_communicator.connect()
            self.assertFalse(replay_connected)

        async_to_sync(run_ticket_flow)()

        self.assertTrue(
            Message.objects.filter(
                conversation=self.conversation,
                sender=self.buyer,
                content='hello over ticket',
            ).exists()
        )

        async def run_jwt_rejection():
            raw_jwt = AccessToken.for_user(self.buyer)
            jwt_communicator = self.make_websocket_communicator(
                application,
                f'/ws/chat/{self.conversation.id}/?token={raw_jwt}',
            )
            connected, _ = await jwt_communicator.connect()
            self.assertFalse(connected)

        async_to_sync(run_jwt_rejection)()

    def test_websocket_rejects_ticket_for_different_conversation(self):
        from asgiref.sync import async_to_sync
        from channels.testing import WebsocketCommunicator
        from gamesbazaar.asgi import application

        from .services import create_chat_ws_ticket

        async def run_wrong_conversation_rejection():
            wrong_ticket = create_chat_ws_ticket(self.buyer, self.other_conversation.id)
            communicator = self.make_websocket_communicator(
                application,
                f'/ws/chat/{self.conversation.id}/?ticket={wrong_ticket}',
            )

            connected, _ = await communicator.connect()
            self.assertFalse(connected)

        async_to_sync(run_wrong_conversation_rejection)()

    def test_rest_message_send_broadcasts_to_open_websocket(self):
        from asgiref.sync import async_to_sync, sync_to_async
        from channels.testing import WebsocketCommunicator
        from gamesbazaar.asgi import application

        from .services import create_chat_ws_ticket

        def post_message():
            client = APIClient()
            client.force_authenticate(user=self.buyer)
            return client.post(
                f'/api/chat/{self.conversation.id}/send/',
                {'content': 'hello from rest'},
                format='json',
            )

        async def run_rest_broadcast_flow():
            ticket = create_chat_ws_ticket(self.seller, self.conversation.id)
            communicator = self.make_websocket_communicator(
                application,
                f'/ws/chat/{self.conversation.id}/?ticket={ticket}',
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            response = await sync_to_async(post_message, thread_sensitive=True)()
            self.assertEqual(response.status_code, 201)

            event = await communicator.receive_json_from()
            self.assertEqual(event['type'], 'new_message')
            self.assertEqual(event['message']['content'], 'hello from rest')
            self.assertEqual(event['message']['sender_id'], self.buyer.id)
            self.assertFalse(event['message']['is_mine'])
            await communicator.disconnect()

        async_to_sync(run_rest_broadcast_flow)()

    def test_rest_image_send_broadcasts_to_open_websocket(self):
        from asgiref.sync import async_to_sync, sync_to_async
        from channels.testing import WebsocketCommunicator
        from gamesbazaar.asgi import application

        from .services import create_chat_ws_ticket

        def post_image():
            client = APIClient()
            client.force_authenticate(user=self.buyer)
            return client.post(
                f'/api/chat/{self.conversation.id}/send-image/',
                {'image': make_image_file(name='rest-chat.png')},
                format='multipart',
            )

        async def run_image_broadcast_flow():
            ticket = create_chat_ws_ticket(self.seller, self.conversation.id)
            communicator = self.make_websocket_communicator(
                application,
                f'/ws/chat/{self.conversation.id}/?ticket={ticket}',
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            response = await sync_to_async(post_image, thread_sensitive=True)()
            self.assertEqual(response.status_code, 201)

            event = await communicator.receive_json_from()
            self.assertEqual(event['type'], 'new_message')
            self.assertEqual(event['message']['sender_id'], self.buyer.id)
            self.assertTrue(event['message']['image_url'])
            self.assertFalse(event['message']['is_mine'])
            await communicator.disconnect()

        async_to_sync(run_image_broadcast_flow)()

    def test_websocket_rejects_overlong_message(self):
        from asgiref.sync import async_to_sync
        from channels.testing import WebsocketCommunicator
        from gamesbazaar.asgi import application

        from .services import MAX_CHAT_MESSAGE_LENGTH, create_chat_ws_ticket

        async def run_overlong_message_rejection():
            ticket = create_chat_ws_ticket(self.buyer, self.conversation.id)
            communicator = self.make_websocket_communicator(
                application,
                f'/ws/chat/{self.conversation.id}/?ticket={ticket}',
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            await communicator.send_json_to({
                'type': 'chat_message',
                'content': 'x' * (MAX_CHAT_MESSAGE_LENGTH + 1),
            })
            event = await communicator.receive_json_from()
            self.assertEqual(event['type'], 'error')
            self.assertEqual(event['code'], 'message_too_long')
            await communicator.disconnect()

        async_to_sync(run_overlong_message_rejection)()

        self.assertFalse(Message.objects.filter(conversation=self.conversation).exists())

    def test_websocket_rate_limits_message_bursts(self):
        from asgiref.sync import async_to_sync
        from channels.testing import WebsocketCommunicator
        from gamesbazaar.asgi import application

        from .services import CHAT_WS_MESSAGE_LIMIT, create_chat_ws_ticket

        async def run_rate_limit_rejection():
            ticket = create_chat_ws_ticket(self.buyer, self.conversation.id)
            communicator = self.make_websocket_communicator(
                application,
                f'/ws/chat/{self.conversation.id}/?ticket={ticket}',
            )
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            for index in range(CHAT_WS_MESSAGE_LIMIT):
                await communicator.send_json_to({
                    'type': 'chat_message',
                    'content': f'msg-{index}',
                })
                event = await communicator.receive_json_from()
                self.assertEqual(event['type'], 'new_message')
                self.assertEqual(event['message']['content'], f'msg-{index}')

            await communicator.send_json_to({
                'type': 'chat_message',
                'content': 'too fast',
            })
            event = await communicator.receive_json_from()
            self.assertEqual(event['type'], 'error')
            self.assertEqual(event['code'], 'rate_limited')
            await communicator.disconnect()

        async_to_sync(run_rate_limit_rejection)()

        self.assertEqual(
            Message.objects.filter(conversation=self.conversation).count(),
            CHAT_WS_MESSAGE_LIMIT,
        )
        self.assertFalse(Message.objects.filter(content='too fast').exists())

    def test_websocket_rate_limit_is_shared_across_connections(self):
        from asgiref.sync import async_to_sync
        from channels.testing import WebsocketCommunicator
        from gamesbazaar.asgi import application

        from .services import CHAT_WS_MESSAGE_LIMIT, create_chat_ws_ticket

        async def run_shared_rate_limit_rejection():
            first_ticket = create_chat_ws_ticket(self.buyer, self.conversation.id)
            first = self.make_websocket_communicator(
                application,
                f'/ws/chat/{self.conversation.id}/?ticket={first_ticket}',
            )
            connected, _ = await first.connect()
            self.assertTrue(connected)

            for index in range(CHAT_WS_MESSAGE_LIMIT):
                await first.send_json_to({
                    'type': 'chat_message',
                    'content': f'shared-{index}',
                })
                event = await first.receive_json_from()
                self.assertEqual(event['type'], 'new_message')

            await first.disconnect()

            second_ticket = create_chat_ws_ticket(self.buyer, self.conversation.id)
            second = self.make_websocket_communicator(
                application,
                f'/ws/chat/{self.conversation.id}/?ticket={second_ticket}',
            )
            connected, _ = await second.connect()
            self.assertTrue(connected)

            await second.send_json_to({
                'type': 'chat_message',
                'content': 'too fast after reconnect',
            })
            event = await second.receive_json_from()
            self.assertEqual(event['type'], 'error')
            self.assertEqual(event['code'], 'rate_limited')
            await second.disconnect()

        async_to_sync(run_shared_rate_limit_rejection)()

        self.assertEqual(
            Message.objects.filter(conversation=self.conversation).count(),
            CHAT_WS_MESSAGE_LIMIT,
        )
        self.assertFalse(Message.objects.filter(content='too fast after reconnect').exists())


class DisputeResolutionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.staff = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='password123',
        )
        self.buyer = User.objects.create_user(username='buyer', password='password123')
        self.seller = User.objects.create_user(username='seller', password='password123')
        self.buyer_wallet = Wallet.objects.get(user=self.buyer)
        self.seller_wallet = Wallet.objects.get(user=self.seller)

        game = Game.objects.create(name='Test Game', slug='test-game')
        category = Category.objects.create(
            name='Accounts',
            slug='accounts',
            commission_rate=Decimal('10.00'),
        )
        self.game_category = GameCategory.objects.create(game=game, category=category)

    def create_order(self, status='disputed'):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Disputed item',
            price=Decimal('100.00'),
            quantity=0,
            status='sold',
        )
        return Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            listing=listing,
            listing_title=listing.title,
            quantity=1,
            unit_price=Decimal('100.00'),
            total_amount=Decimal('100.00'),
            commission_rate=Decimal('10.00'),
            commission_amount=Decimal('10.00'),
            seller_amount=Decimal('90.00'),
            status=status,
        )

    def test_non_staff_cannot_resolve_dispute(self):
        order = self.create_order()
        self.client.force_authenticate(user=self.buyer)

        response = self.client.post(
            f'/api/admin/orders/{order.pk}/resolve-dispute/',
            {'resolution_action': 'refund_buyer'},
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, 'disputed')

    def test_resolve_dispute_rejects_invalid_action(self):
        order = self.create_order()
        self.client.force_authenticate(user=self.staff)

        response = self.client.post(
            f'/api/admin/orders/{order.pk}/resolve-dispute/',
            {'resolution_action': 'invalid'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('resolution_action', response.data['error'])

    def test_resolve_dispute_refunds_buyer_and_restores_stock(self):
        order = self.create_order()
        self.client.force_authenticate(user=self.staff)

        response = self.client.post(
            f'/api/admin/orders/{order.pk}/resolve-dispute/',
            {'resolution_action': 'refund_buyer'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        order.listing.refresh_from_db()
        self.buyer_wallet.refresh_from_db()
        self.seller_wallet.refresh_from_db()

        self.assertEqual(order.status, 'cancelled')
        self.assertEqual(order.listing.quantity, 1)
        self.assertEqual(order.listing.status, 'active')
        self.assertEqual(self.buyer_wallet.balance, Decimal('100.00'))
        self.assertEqual(self.seller_wallet.balance, Decimal('0.00'))
        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.buyer_wallet,
                transaction_type='refund',
                reference_id=f'order_{order.pk}',
            ).count(),
            1,
        )

    def test_resolve_dispute_refund_does_not_restore_auto_delivery_stock(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Disputed auto delivery item',
            price=Decimal('100.00'),
            quantity=0,
            status='sold',
            is_auto_delivery=True,
            auto_delivery_data='',
        )
        order = Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            listing=listing,
            listing_title=listing.title,
            quantity=1,
            unit_price=Decimal('100.00'),
            total_amount=Decimal('100.00'),
            commission_rate=Decimal('10.00'),
            commission_amount=Decimal('10.00'),
            seller_amount=Decimal('90.00'),
            status='disputed',
            delivery_note='code-one',
        )
        self.client.force_authenticate(user=self.staff)

        response = self.client.post(
            f'/api/admin/orders/{order.pk}/resolve-dispute/',
            {'resolution_action': 'refund_buyer'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        listing.refresh_from_db()
        self.assertEqual(listing.quantity, 0)
        self.assertEqual(listing.status, 'sold')
        self.assertEqual(listing.auto_delivery_data, '')

    def test_resolve_dispute_pays_seller_and_records_commission(self):
        order = self.create_order()
        self.client.force_authenticate(user=self.staff)

        response = self.client.post(
            f'/api/admin/orders/{order.pk}/resolve-dispute/',
            {'resolution_action': 'pay_seller'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.buyer_wallet.refresh_from_db()
        self.seller_wallet.refresh_from_db()

        self.assertEqual(order.status, 'completed')
        self.assertEqual(self.buyer_wallet.balance, Decimal('0.00'))
        self.assertEqual(self.seller_wallet.balance, Decimal('90.00'))
        sale_tx = WalletTransaction.objects.get(
            wallet=self.seller_wallet,
            transaction_type='sale',
            reference_id=f'order_{order.pk}',
        )
        commission_tx = WalletTransaction.objects.get(
            wallet=self.seller_wallet,
            transaction_type='commission',
            reference_id=f'order_{order.pk}',
        )
        self.assertEqual(sale_tx.amount, Decimal('100.00'))
        self.assertEqual(sale_tx.balance_after, Decimal('100.00'))
        self.assertEqual(commission_tx.amount, Decimal('10.00'))
        self.assertEqual(commission_tx.balance_after, Decimal('90.00'))
        entry = PlatformLedgerEntry.objects.get(
            entry_type='commission_collected',
            reference_id=f'order_{order.pk}',
        )
        self.assertEqual(entry.amount, Decimal('10.00'))

    def test_resolve_dispute_rejects_non_disputed_order(self):
        order = self.create_order(status='pending')
        self.client.force_authenticate(user=self.staff)

        response = self.client.post(
            f'/api/admin/orders/{order.pk}/resolve-dispute/',
            {'resolution_action': 'refund_buyer'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'Only disputed orders can be resolved.')


class AdminMoneyActionTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.factory = RequestFactory()
        self.request = self.factory.post('/admin/')
        self.request.user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='password123',
        )
        self.buyer = User.objects.create_user(username='buyer', password='password123')
        self.seller = User.objects.create_user(username='seller', password='password123')
        self.buyer_wallet = Wallet.objects.get(user=self.buyer)
        self.seller_wallet = Wallet.objects.get(user=self.seller)

        game = Game.objects.create(name='Test Game', slug='test-game')
        category = Category.objects.create(
            name='Accounts',
            slug='accounts',
            commission_rate=Decimal('10.00'),
        )
        self.game_category = GameCategory.objects.create(game=game, category=category)

    def create_order(self, status='disputed'):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Admin action item',
            price=Decimal('100.00'),
            quantity=0,
            status='sold',
        )
        return Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            listing=listing,
            listing_title=listing.title,
            quantity=1,
            unit_price=Decimal('100.00'),
            total_amount=Decimal('100.00'),
            commission_rate=Decimal('10.00'),
            commission_amount=Decimal('10.00'),
            seller_amount=Decimal('90.00'),
            status=status,
        )

    def test_wallet_transaction_reference_is_unique_per_wallet_and_type(self):
        WalletTransaction.objects.create(
            wallet=self.buyer_wallet,
            transaction_type='refund',
            amount=Decimal('100.00'),
            balance_after=Decimal('100.00'),
            reference_id='order_1',
        )

        with self.assertRaises(IntegrityError):
            with db_transaction.atomic():
                WalletTransaction.objects.create(
                    wallet=self.buyer_wallet,
                    transaction_type='refund',
                    amount=Decimal('100.00'),
                    balance_after=Decimal('200.00'),
                    reference_id='order_1',
                )

    def test_admin_topup_approval_is_idempotent(self):
        topup = TopUpRequest.objects.create(
            user=self.buyer,
            amount=Decimal('100.00'),
            payment_method='Bank Transfer',
            transaction_id='admin-topup',
        )
        admin_obj = TopUpRequestAdmin(TopUpRequest, self.site)
        queryset = TopUpRequest.objects.filter(pk=topup.pk)

        with patch.object(admin_obj, 'message_user'):
            admin_obj.approve_topups(self.request, queryset)
            admin_obj.approve_topups(self.request, queryset)

        topup.refresh_from_db()
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(topup.status, 'approved')
        self.assertEqual(self.buyer_wallet.balance, Decimal('100.00'))
        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.buyer_wallet,
                transaction_type='topup_approved',
                reference_id=f'topup_{topup.pk}',
            ).count(),
            1,
        )

    def test_admin_withdrawal_approval_is_idempotent(self):
        withdraw = WithdrawRequest.objects.create(
            user=self.buyer,
            amount=Decimal('500.00'),
            payment_method='JazzCash',
            account_title='Buyer Account',
            account_details='03001234567',
        )
        admin_obj = WithdrawRequestAdmin(WithdrawRequest, self.site)
        queryset = WithdrawRequest.objects.filter(pk=withdraw.pk)

        with patch.object(admin_obj, 'message_user'):
            admin_obj.approve_withdrawals(self.request, queryset)
            admin_obj.approve_withdrawals(self.request, queryset)

        withdraw.refresh_from_db()
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(withdraw.status, 'approved')
        self.assertIsNotNone(withdraw.reviewed_at)
        self.assertEqual(self.buyer_wallet.balance, Decimal('0.00'))
        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.buyer_wallet,
                transaction_type='withdraw_approved',
                reference_id=f'withdraw_{withdraw.pk}',
            ).count(),
            1,
        )

    def test_admin_withdrawal_rejection_refunds_once(self):
        withdraw = WithdrawRequest.objects.create(
            user=self.buyer,
            amount=Decimal('500.00'),
            payment_method='JazzCash',
            account_title='Buyer Account',
            account_details='03001234567',
        )
        admin_obj = WithdrawRequestAdmin(WithdrawRequest, self.site)
        queryset = WithdrawRequest.objects.filter(pk=withdraw.pk)

        with patch.object(admin_obj, 'message_user'):
            admin_obj.reject_withdrawals(self.request, queryset)
            admin_obj.reject_withdrawals(self.request, queryset)

        withdraw.refresh_from_db()
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(withdraw.status, 'rejected')
        self.assertIsNotNone(withdraw.reviewed_at)
        self.assertEqual(self.buyer_wallet.balance, Decimal('500.00'))
        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.buyer_wallet,
                transaction_type='withdraw_rejected',
                reference_id=f'withdraw_{withdraw.pk}',
            ).count(),
            1,
        )

    def test_admin_terminal_withdrawal_edit_does_not_reverse_money(self):
        withdraw = WithdrawRequest.objects.create(
            user=self.buyer,
            amount=Decimal('500.00'),
            payment_method='JazzCash',
            account_title='Buyer Account',
            account_details='03001234567',
            status='approved',
            reviewed_at=timezone.now(),
        )
        admin_obj = WithdrawRequestAdmin(WithdrawRequest, self.site)
        form = type('ChangedStatusForm', (), {'changed_data': ['status']})()

        withdraw.status = 'rejected'
        with patch.object(admin_obj, 'message_user'):
            admin_obj.save_model(self.request, withdraw, form, change=True)

        withdraw.refresh_from_db()
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(withdraw.status, 'approved')
        self.assertEqual(self.buyer_wallet.balance, Decimal('0.00'))
        self.assertFalse(
            WalletTransaction.objects.filter(
                wallet=self.buyer_wallet,
                transaction_type='withdraw_rejected',
                reference_id=f'withdraw_{withdraw.pk}',
            ).exists()
        )

    def test_active_topup_transaction_reference_is_unique_per_method(self):
        TopUpRequest.objects.create(
            user=self.buyer,
            amount=Decimal('100.00'),
            payment_method='Bank Transfer',
            transaction_id='admin-topup',
        )

        with self.assertRaises(IntegrityError):
            with db_transaction.atomic():
                TopUpRequest.objects.create(
                    user=self.seller,
                    amount=Decimal('100.00'),
                    payment_method=' bank transfer ',
                    transaction_id='ADMIN-TOPUP',
                )

    def test_admin_refund_and_cancel_is_idempotent(self):
        order = self.create_order(status='disputed')
        admin_obj = OrderAdmin(Order, self.site)
        queryset = Order.objects.filter(pk=order.pk)

        with patch.object(admin_obj, 'message_user'):
            admin_obj.refund_and_cancel(self.request, queryset)
            admin_obj.refund_and_cancel(self.request, queryset)

        order.refresh_from_db()
        order.listing.refresh_from_db()
        self.buyer_wallet.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')
        self.assertEqual(order.listing.quantity, 1)
        self.assertEqual(order.listing.status, 'active')
        self.assertEqual(self.buyer_wallet.balance, Decimal('100.00'))
        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.buyer_wallet,
                transaction_type='refund',
                reference_id=f'order_{order.pk}',
            ).count(),
            1,
        )

    def test_admin_release_to_seller_is_idempotent(self):
        order = self.create_order(status='disputed')
        admin_obj = OrderAdmin(Order, self.site)
        queryset = Order.objects.filter(pk=order.pk)

        with patch.object(admin_obj, 'message_user'):
            admin_obj.release_to_seller(self.request, queryset)
            admin_obj.release_to_seller(self.request, queryset)

        order.refresh_from_db()
        self.seller_wallet.refresh_from_db()
        self.assertEqual(order.status, 'completed')
        self.assertEqual(self.seller_wallet.balance, Decimal('90.00'))
        sale_tx = WalletTransaction.objects.get(
            wallet=self.seller_wallet,
            transaction_type='sale',
            reference_id=f'order_{order.pk}',
        )
        commission_tx = WalletTransaction.objects.get(
            wallet=self.seller_wallet,
            transaction_type='commission',
            reference_id=f'order_{order.pk}',
        )
        self.assertEqual(sale_tx.amount, Decimal('100.00'))
        self.assertEqual(sale_tx.balance_after, Decimal('100.00'))
        self.assertEqual(commission_tx.amount, Decimal('10.00'))
        self.assertEqual(commission_tx.balance_after, Decimal('90.00'))
        entry = PlatformLedgerEntry.objects.get(
            entry_type='commission_collected',
            reference_id=f'order_{order.pk}',
        )
        self.assertEqual(entry.amount, Decimal('10.00'))


class AdminChatProtectionTests(TestCase):
    def setUp(self):
        self.site = GamesBazaarAdminSite(name='test_admin')
        self.factory = RequestFactory()
        self.buyer = User.objects.create_user(username='chat_buyer', password='password123')
        self.seller = User.objects.create_user(username='chat_seller', password='password123')
        self.no_perm_admin = User.objects.create_user(
            username='no_perm_admin',
            password='password123',
            is_staff=True,
        )
        self.view_only_admin = User.objects.create_user(
            username='view_only_admin',
            password='password123',
            is_staff=True,
        )
        self.sender_admin = User.objects.create_user(
            username='sender_admin',
            password='password123',
            is_staff=True,
        )
        self.grant_permission(self.view_only_admin, 'view_conversation')
        self.grant_permission(self.sender_admin, 'view_conversation')
        self.grant_permission(self.sender_admin, 'add_message')
        self.conversation = Conversation.objects.create()
        self.conversation.participants.add(self.buyer, self.seller)

    def grant_permission(self, user, codename):
        permission = Permission.objects.get(
            content_type__app_label='core',
            codename=codename,
        )
        user.user_permissions.add(permission)
        for attr in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
            if hasattr(user, attr):
                delattr(user, attr)

    def test_admin_chatbox_requires_conversation_view_permission(self):
        request = self.factory.get(
            f'/admin/core/conversation/{self.conversation.pk}/chatbox/',
        )
        request.user = self.no_perm_admin

        with self.assertRaises(PermissionDenied):
            self.site.conversation_chatbox_view(request, self.conversation.pk)

    def test_view_only_admin_cannot_send_chatbox_message(self):
        request = self.factory.post(
            f'/admin/core/conversation/{self.conversation.pk}/chatbox/',
            {'message': 'Admin note'},
        )
        request.user = self.view_only_admin

        with self.assertRaises(PermissionDenied):
            self.site.conversation_chatbox_view(request, self.conversation.pk)

        self.assertFalse(
            Message.objects.filter(
                conversation=self.conversation,
                sender=self.view_only_admin,
            ).exists()
        )

    def test_admin_with_message_permission_can_send_chatbox_message(self):
        request = self.factory.post(
            f'/admin/core/conversation/{self.conversation.pk}/chatbox/',
            {'message': 'Please share a screenshot.'},
        )
        request.user = self.sender_admin

        response = self.site.conversation_chatbox_view(request, self.conversation.pk)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Message.objects.filter(
                conversation=self.conversation,
                sender=self.sender_admin,
                content='Please share a screenshot.',
            ).exists()
        )
        self.assertTrue(
            self.conversation.participants.filter(pk=self.sender_admin.pk).exists()
        )

    def test_admin_message_image_view_requires_conversation_view_permission(self):
        message = Message.objects.create(
            conversation=self.conversation,
            sender=self.buyer,
            content='image',
        )
        request = self.factory.get(f'/admin/core/message/{message.pk}/image/')
        request.user = self.no_perm_admin

        with self.assertRaises(PermissionDenied):
            self.site.conversation_message_image_view(request, message.pk)


class ConcurrentPurchaseFlowTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.buyer = User.objects.create_user(username='buyer', password='password123')
        self.seller = User.objects.create_user(username='seller', password='password123')
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])

        self.buyer_wallet = Wallet.objects.get(user=self.buyer)
        self.buyer_wallet.balance = Decimal('100.00')
        self.buyer_wallet.save(update_fields=['balance'])

        game = Game.objects.create(name='Test Game', slug='test-game')
        category = Category.objects.create(name='Accounts', slug='accounts')
        self.game_category = GameCategory.objects.create(game=game, category=category)

    def test_concurrent_buyers_cannot_both_buy_single_stock_listing(self):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='One stock concurrent item',
            price=Decimal('25.00'),
            quantity=1,
            status='active',
        )
        barrier = Barrier(2)
        results = [None, None]

        def buy(index):
            client = APIClient()
            client.force_authenticate(user=self.buyer)
            try:
                barrier.wait(timeout=5)
                response = client.post(
                    '/api/orders/buy/',
                    {'listing_id': listing.id, 'quantity': 1},
                    format='json',
                )
                results[index] = response.status_code
            except Exception as exc:
                results[index] = exc
            finally:
                connections.close_all()

        threads = [Thread(target=buy, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(results.count(201), 1, results)
        self.assertEqual(results.count(400), 1, results)
        self.assertEqual(Order.objects.filter(listing=listing).count(), 1)

        listing.refresh_from_db()
        self.assertEqual(listing.quantity, 0)
        self.assertEqual(listing.status, 'sold')

        self.buyer_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('75.00'))


class ConcurrentConversationCreationTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.buyer = User.objects.create_user(username='buyer', password='password123')
        self.seller = User.objects.create_user(username='seller', password='password123')

    def test_concurrent_start_conversation_creates_one_private_thread(self):
        barrier = Barrier(2)
        results = [None, None]

        def post(index):
            client = APIClient()
            client.force_authenticate(user=self.buyer)
            try:
                barrier.wait(timeout=5)
                response = client.post(
                    '/api/chat/start/',
                    {
                        'user_id': self.seller.id,
                        'message': f'hello {index}',
                    },
                    format='json',
                )
                results[index] = response.status_code
            except Exception as exc:
                results[index] = exc
            finally:
                connections.close_all()

        threads = [Thread(target=post, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(results.count(201), 2, results)
        conversations = Conversation.objects.filter(
            participants=self.buyer
        ).filter(
            participants=self.seller
        ).distinct()
        self.assertEqual(conversations.count(), 1)
        self.assertEqual(
            Message.objects.filter(conversation=conversations.get()).count(),
            2,
        )


class ConcurrentOrderStateTransitionTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.buyer = User.objects.create_user(username='buyer', password='password123')
        self.seller = User.objects.create_user(username='seller', password='password123')
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])

        self.buyer_wallet = Wallet.objects.get(user=self.buyer)
        self.buyer_wallet.balance = Decimal('0.00')
        self.buyer_wallet.save(update_fields=['balance'])

        self.seller_wallet = Wallet.objects.get(user=self.seller)
        self.seller_wallet.balance = Decimal('0.00')
        self.seller_wallet.save(update_fields=['balance'])

        game = Game.objects.create(name='Test Game', slug='test-game')
        category = Category.objects.create(
            name='Accounts',
            slug='accounts',
            commission_rate=Decimal('0.00'),
        )
        self.game_category = GameCategory.objects.create(game=game, category=category)

    def create_order(self, status):
        listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title=f'{status} order item',
            price=Decimal('50.00'),
            quantity=0,
            status='sold',
        )
        order = Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            listing=listing,
            listing_title=listing.title,
            quantity=1,
            unit_price=Decimal('50.00'),
            total_amount=Decimal('50.00'),
            commission_rate=Decimal('0.00'),
            commission_amount=Decimal('0.00'),
            seller_amount=Decimal('50.00'),
            status=status,
        )
        return order

    def post_concurrently(self, user, path):
        barrier = Barrier(2)
        results = [None, None]

        def post(index):
            client = APIClient()
            client.force_authenticate(user=user)
            try:
                barrier.wait(timeout=5)
                response = client.post(path, {}, format='json')
                results[index] = response.status_code
            except Exception as exc:
                results[index] = exc
            finally:
                connections.close_all()

        threads = [Thread(target=post, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        return results

    def post_pairs_concurrently(self, requests):
        barrier = Barrier(len(requests))
        results = [None] * len(requests)

        def post(index, user, path, payload):
            client = APIClient()
            client.force_authenticate(user=user)
            try:
                barrier.wait(timeout=5)
                response = client.post(path, payload, format='json')
                results[index] = response.status_code
            except Exception as exc:
                results[index] = exc
            finally:
                connections.close_all()

        threads = [
            Thread(target=post, args=(index, user, path, payload))
            for index, (user, path, payload) in enumerate(requests)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        return results

    def test_concurrent_confirm_releases_seller_funds_once(self):
        order = self.create_order(status='delivered')

        results = self.post_concurrently(
            self.buyer,
            f'/api/orders/{order.id}/confirm/',
        )

        self.assertEqual(results.count(200), 2, results)

        order.refresh_from_db()
        self.assertEqual(order.status, 'completed')

        self.seller_wallet.refresh_from_db()
        self.assertEqual(self.seller_wallet.balance, Decimal('50.00'))
        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.seller_wallet,
                transaction_type='sale',
                reference_id=f'order_{order.id}',
            ).count(),
            1,
        )

    def test_concurrent_deliver_and_confirm_never_confirms_before_delivery(self):
        order = self.create_order(status='pending')

        results = self.post_pairs_concurrently([
            (
                self.seller,
                f'/api/orders/{order.id}/deliver/',
                {'delivery_note': 'delivered'},
            ),
            (
                self.buyer,
                f'/api/orders/{order.id}/confirm/',
                {},
            ),
        ])

        self.assertIn(results[0], (200, 400), results)
        self.assertIn(results[1], (200, 400), results)
        self.assertIn(200, results)

        order.refresh_from_db()
        sale_count = WalletTransaction.objects.filter(
            wallet=self.seller_wallet,
            transaction_type='sale',
            reference_id=f'order_{order.id}',
        ).count()

        self.seller_wallet.refresh_from_db()
        if sale_count:
            self.assertEqual(order.status, 'completed')
            self.assertEqual(self.seller_wallet.balance, Decimal('50.00'))
        else:
            self.assertEqual(order.status, 'delivered')
            self.assertEqual(self.seller_wallet.balance, Decimal('0.00'))
        self.assertLessEqual(sale_count, 1)

    def test_concurrent_dispute_and_confirm_cannot_dispute_paid_order(self):
        order = self.create_order(status='pending')

        results = self.post_pairs_concurrently([
            (
                self.buyer,
                f'/api/orders/{order.id}/dispute/',
                {'reason': 'not delivered'},
            ),
            (
                self.buyer,
                f'/api/orders/{order.id}/confirm/',
                {},
            ),
        ])

        self.assertEqual(results.count(200), 1, results)
        self.assertEqual(results.count(400), 1, results)

        order.refresh_from_db()
        self.seller_wallet.refresh_from_db()
        self.assertEqual(order.status, 'disputed')
        self.assertEqual(self.seller_wallet.balance, Decimal('0.00'))
        self.assertFalse(
            WalletTransaction.objects.filter(
                wallet=self.seller_wallet,
                transaction_type='sale',
                reference_id=f'order_{order.id}',
            ).exists()
        )

    def test_concurrent_refund_reverses_completed_order_once(self):
        order = self.create_order(status='completed')
        self.seller_wallet.balance = Decimal('50.00')
        self.seller_wallet.save(update_fields=['balance'])

        results = self.post_concurrently(
            self.seller,
            f'/api/orders/{order.id}/refund/',
        )

        self.assertEqual(results.count(200), 2, results)

        order.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')

        order.listing.refresh_from_db()
        self.assertEqual(order.listing.quantity, 1)
        self.assertEqual(order.listing.status, 'active')

        self.buyer_wallet.refresh_from_db()
        self.seller_wallet.refresh_from_db()
        self.assertEqual(self.buyer_wallet.balance, Decimal('50.00'))
        self.assertEqual(self.seller_wallet.balance, Decimal('0.00'))

        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.buyer_wallet,
                transaction_type='refund',
                reference_id=f'order_{order.id}',
            ).count(),
            1,
        )
        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.seller_wallet,
                transaction_type='refund',
                reference_id=f'order_{order.id}',
            ).count(),
            1,
        )


class ReviewTests(TestCase):
    """Tests for the Reviews & Trust system."""

    def setUp(self):
        self.client = APIClient()
        self.buyer = User.objects.create_user(username='buyer', password='password123')
        self.seller = User.objects.create_user(username='seller', password='password123')
        self.other_buyer = User.objects.create_user(username='other_buyer', password='password123')

        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])

        game = Game.objects.create(name='Test Game', slug='test-game')
        category = Category.objects.create(
            name='Accounts', slug='accounts', commission_rate=Decimal('10.00'),
        )
        self.game_category = GameCategory.objects.create(game=game, category=category)

        self.listing = Listing.objects.create(
            seller=self.seller,
            game_category=self.game_category,
            title='Test Listing',
            price=Decimal('50.00'),
            quantity=5,
            status='active',
        )

        self.completed_order = Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            listing=self.listing,
            listing_title=self.listing.title,
            quantity=1,
            unit_price=Decimal('50.00'),
            total_amount=Decimal('50.00'),
            commission_rate=Decimal('10.00'),
            commission_amount=Decimal('5.00'),
            seller_amount=Decimal('45.00'),
            status='completed',
        )

    # CreateReviewView tests

    def test_buyer_can_review_completed_order(self):
        self.client.force_authenticate(user=self.buyer)

        response = self.client.post(
            '/api/reviews/',
            {'order_id': self.completed_order.id, 'rating': 5, 'comment': 'Great seller!'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['rating'], 5)
        self.assertEqual(response.data['comment'], 'Great seller!')
        self.assertTrue(Review.objects.filter(order=self.completed_order).exists())

    def test_buyer_can_review_completed_order_by_order_number(self):
        self.client.force_authenticate(user=self.buyer)

        response = self.client.post(
            '/api/reviews/',
            {
                'order_id': self.completed_order.order_number,
                'rating': 5,
                'comment': 'Found by public order number.',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['order'], self.completed_order.pk)
        self.assertTrue(Review.objects.filter(order=self.completed_order).exists())

    def test_review_without_comment_is_accepted(self):
        self.client.force_authenticate(user=self.buyer)

        response = self.client.post(
            '/api/reviews/',
            {'order_id': self.completed_order.id, 'rating': 4},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['rating'], 4)
        self.assertEqual(response.data['comment'], '')

    def test_cannot_review_same_order_twice(self):
        Review.objects.create(
            order=self.completed_order,
            reviewer=self.buyer,
            seller=self.seller,
            rating=5,
            comment='First review',
        )
        self.client.force_authenticate(user=self.buyer)

        response = self.client.post(
            '/api/reviews/',
            {'order_id': self.completed_order.id, 'rating': 3, 'comment': 'Second review'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('already reviewed', response.data['error'])
        self.assertEqual(Review.objects.filter(order=self.completed_order).count(), 1)

    def test_cannot_review_pending_order(self):
        pending_order = Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            listing=self.listing,
            listing_title=self.listing.title,
            quantity=1,
            unit_price=Decimal('50.00'),
            total_amount=Decimal('50.00'),
            commission_rate=Decimal('10.00'),
            commission_amount=Decimal('5.00'),
            seller_amount=Decimal('45.00'),
            status='pending',
        )
        self.client.force_authenticate(user=self.buyer)

        response = self.client.post(
            '/api/reviews/',
            {'order_id': pending_order.id, 'rating': 5},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('completed orders', response.data['error'])
        self.assertFalse(Review.objects.filter(order=pending_order).exists())

    def test_cannot_review_cancelled_order(self):
        cancelled_order = Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            listing=self.listing,
            listing_title=self.listing.title,
            quantity=1,
            unit_price=Decimal('50.00'),
            total_amount=Decimal('50.00'),
            commission_rate=Decimal('10.00'),
            commission_amount=Decimal('5.00'),
            seller_amount=Decimal('45.00'),
            status='cancelled',
        )
        self.client.force_authenticate(user=self.buyer)

        response = self.client.post(
            '/api/reviews/',
            {'order_id': cancelled_order.id, 'rating': 1},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Review.objects.filter(order=cancelled_order).exists())

    def test_seller_cannot_review_own_order(self):
        self.client.force_authenticate(user=self.seller)

        response = self.client.post(
            '/api/reviews/',
            {'order_id': self.completed_order.id, 'rating': 5},
            format='json',
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Review.objects.filter(order=self.completed_order).exists())

    def test_other_buyer_cannot_review_someone_elses_order(self):
        self.client.force_authenticate(user=self.other_buyer)

        response = self.client.post(
            '/api/reviews/',
            {'order_id': self.completed_order.id, 'rating': 5},
            format='json',
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Review.objects.filter(order=self.completed_order).exists())

    def test_unauthenticated_user_cannot_review(self):
        response = self.client.post(
            '/api/reviews/',
            {'order_id': self.completed_order.id, 'rating': 5},
            format='json',
        )

        self.assertEqual(response.status_code, 401)

    def test_review_rejects_rating_below_1(self):
        self.client.force_authenticate(user=self.buyer)

        response = self.client.post(
            '/api/reviews/',
            {'order_id': self.completed_order.id, 'rating': 0},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Review.objects.filter(order=self.completed_order).exists())

    def test_review_rejects_rating_above_5(self):
        self.client.force_authenticate(user=self.buyer)

        response = self.client.post(
            '/api/reviews/',
            {'order_id': self.completed_order.id, 'rating': 6},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Review.objects.filter(order=self.completed_order).exists())

    def test_review_rejects_missing_rating(self):
        self.client.force_authenticate(user=self.buyer)

        response = self.client.post(
            '/api/reviews/',
            {'order_id': self.completed_order.id},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_review_rejects_missing_order_id(self):
        self.client.force_authenticate(user=self.buyer)

        response = self.client.post(
            '/api/reviews/',
            {'rating': 5},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    # OrderSerializer has_review flag

    def test_order_has_review_false_before_review(self):
        self.client.force_authenticate(user=self.buyer)

        response = self.client.get(f'/api/orders/{self.completed_order.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['has_review'])

    def test_order_has_review_true_after_review(self):
        Review.objects.create(
            order=self.completed_order,
            reviewer=self.buyer,
            seller=self.seller,
            rating=5,
        )
        self.client.force_authenticate(user=self.buyer)

        response = self.client.get(f'/api/orders/{self.completed_order.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['has_review'])

    def test_order_detail_includes_review_data_and_seller_reply(self):
        review = Review.objects.create(
            order=self.completed_order,
            reviewer=self.buyer,
            seller=self.seller,
            rating=5,
            comment='Great seller.',
            seller_reply='Thanks for buying.',
            seller_reply_at=timezone.now(),
        )
        self.client.force_authenticate(user=self.buyer)

        response = self.client.get(f'/api/orders/{self.completed_order.order_number}/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['has_review'])
        self.assertEqual(response.data['review_data']['id'], review.pk)
        self.assertEqual(response.data['review_data']['rating'], 5)
        self.assertEqual(response.data['review_data']['seller_reply'], 'Thanks for buying.')

    def test_buyer_can_update_own_review(self):
        review = Review.objects.create(
            order=self.completed_order,
            reviewer=self.buyer,
            seller=self.seller,
            rating=4,
            comment='Good.',
        )
        self.client.force_authenticate(user=self.buyer)

        response = self.client.put(
            f'/api/reviews/{review.pk}/',
            {'rating': 2, 'comment': 'Updated after issue.'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        review.refresh_from_db()
        self.assertEqual(review.rating, 2)
        self.assertEqual(review.comment, 'Updated after issue.')
        self.assertEqual(response.data['rating'], 2)

    def test_other_buyer_cannot_update_review(self):
        review = Review.objects.create(
            order=self.completed_order,
            reviewer=self.buyer,
            seller=self.seller,
            rating=4,
        )
        self.client.force_authenticate(user=self.other_buyer)

        response = self.client.put(
            f'/api/reviews/{review.pk}/',
            {'rating': 1, 'comment': 'Not my review.'},
            format='json',
        )

        self.assertEqual(response.status_code, 404)
        review.refresh_from_db()
        self.assertEqual(review.rating, 4)

    def test_seller_can_reply_to_review_once(self):
        review = Review.objects.create(
            order=self.completed_order,
            reviewer=self.buyer,
            seller=self.seller,
            rating=5,
        )
        self.client.force_authenticate(user=self.seller)

        response = self.client.post(
            f'/api/reviews/{review.pk}/reply/',
            {'reply': 'Thanks for the kind review.'},
            format='json',
        )
        duplicate_response = self.client.post(
            f'/api/reviews/{review.pk}/reply/',
            {'reply': 'Second reply.'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['seller_reply'], 'Thanks for the kind review.')
        self.assertEqual(duplicate_response.status_code, 400)
        review.refresh_from_db()
        self.assertEqual(review.seller_reply, 'Thanks for the kind review.')
        self.assertIsNotNone(review.seller_reply_at)

    def test_non_seller_cannot_reply_to_review(self):
        review = Review.objects.create(
            order=self.completed_order,
            reviewer=self.buyer,
            seller=self.seller,
            rating=5,
        )
        self.client.force_authenticate(user=self.buyer)

        response = self.client.post(
            f'/api/reviews/{review.pk}/reply/',
            {'reply': 'Not the seller.'},
            format='json',
        )

        self.assertEqual(response.status_code, 404)
        review.refresh_from_db()
        self.assertEqual(review.seller_reply, '')

    # SellerReviewsView tests

    def test_seller_reviews_endpoint_lists_reviews(self):
        Review.objects.create(
            order=self.completed_order,
            reviewer=self.buyer,
            seller=self.seller,
            rating=4,
            comment='Good seller',
        )

        response = self.client.get('/api/reviews/seller/seller/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['pagination']['count'], 1)
        self.assertEqual(len(response.data['reviews']), 1)
        self.assertEqual(response.data['reviews'][0]['rating'], 4)
        self.assertEqual(response.data['reviews'][0]['comment'], 'Good seller')
        self.assertEqual(response.data['reviews'][0]['reviewer_name'], 'buyer')
        self.assertEqual(response.data['reviews'][0]['listing_title'], 'Test Listing')

    def test_seller_reviews_endpoint_returns_empty_for_no_reviews(self):
        response = self.client.get('/api/reviews/seller/seller/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['reviews'], [])
        self.assertEqual(response.data['pagination']['count'], 0)

    def test_seller_reviews_endpoint_returns_404_for_unknown_user(self):
        response = self.client.get('/api/reviews/seller/nonexistent/')

        self.assertEqual(response.status_code, 404)

    def test_seller_reviews_are_public(self):
        """Unauthenticated users can view seller reviews."""
        Review.objects.create(
            order=self.completed_order,
            reviewer=self.buyer,
            seller=self.seller,
            rating=5,
        )

        response = self.client.get('/api/reviews/seller/seller/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['reviews']), 1)

    def test_seller_reviews_endpoint_is_paginated(self):
        for index in range(25):
            buyer = User.objects.create_user(
                username=f'review_buyer_{index}',
                password='password123',
            )
            order = Order.objects.create(
                buyer=buyer,
                seller=self.seller,
                listing=self.listing,
                listing_title=self.listing.title,
                quantity=1,
                unit_price=Decimal('50.00'),
                total_amount=Decimal('50.00'),
                commission_rate=Decimal('10.00'),
                commission_amount=Decimal('5.00'),
                seller_amount=Decimal('45.00'),
                status='completed',
            )
            Review.objects.create(
                order=order,
                reviewer=buyer,
                seller=self.seller,
                rating=5,
            )

        response = self.client.get('/api/reviews/seller/seller/?limit=10')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['reviews']), 10)
        self.assertEqual(response.data['pagination']['count'], 25)
        self.assertEqual(response.data['pagination']['next_offset'], 10)

    # SellerProfileView tests

    def test_seller_profile_returns_correct_stats(self):
        Review.objects.create(
            order=self.completed_order,
            reviewer=self.buyer,
            seller=self.seller,
            rating=4,
        )

        response = self.client.get('/api/seller/profile/seller/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['username'], 'seller')
        self.assertEqual(response.data['avg_rating'], 4.0)
        self.assertEqual(response.data['review_count'], 1)
        self.assertEqual(response.data['completed_sales'], 1)
        self.assertIn('member_since', response.data)
        self.assertIn('is_online', response.data)
        self.assertIn('active_listings', response.data)

    def test_seller_profile_avg_rating_with_multiple_reviews(self):
        # Create a second completed order for a second review
        second_order = Order.objects.create(
            buyer=self.other_buyer,
            seller=self.seller,
            listing=self.listing,
            listing_title=self.listing.title,
            quantity=1,
            unit_price=Decimal('50.00'),
            total_amount=Decimal('50.00'),
            commission_rate=Decimal('10.00'),
            commission_amount=Decimal('5.00'),
            seller_amount=Decimal('45.00'),
            status='completed',
        )
        Review.objects.create(
            order=self.completed_order, reviewer=self.buyer, seller=self.seller, rating=5,
        )
        Review.objects.create(
            order=second_order, reviewer=self.other_buyer, seller=self.seller, rating=3,
        )

        response = self.client.get('/api/seller/profile/seller/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['avg_rating'], 4.0)
        self.assertEqual(response.data['review_count'], 2)
        self.assertEqual(response.data['completed_sales'], 2)

    def test_seller_profile_without_reviews(self):
        response = self.client.get('/api/seller/profile/seller/')

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['avg_rating'])
        self.assertEqual(response.data['review_count'], 0)

    def test_non_seller_profile_returns_404(self):
        response = self.client.get('/api/seller/profile/buyer/')

        self.assertEqual(response.status_code, 404)

    def test_seller_profile_is_public(self):
        """Unauthenticated users can view seller profile."""
        response = self.client.get('/api/seller/profile/seller/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['username'], 'seller')

    def test_seller_profile_returns_404_for_unknown_user(self):
        response = self.client.get('/api/seller/profile/nonexistent/')

        self.assertEqual(response.status_code, 404)

    def test_seller_profile_active_listings_count(self):
        response = self.client.get('/api/seller/profile/seller/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['active_listings'], 1)


class SearchTests(TestCase):
    """Tests for GET /api/search/?q=<query> - game-category search."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()

        # Create games
        self.valorant = Game.objects.create(name='Valorant', slug='valorant', is_active=True)
        self.pubg = Game.objects.create(name='PUBG Mobile', slug='pubg-mobile', is_active=True)
        self.gta = Game.objects.create(
            name='GTA 5', slug='gta-5', is_active=True,
            search_keywords='gta, grand theft auto, gta v, gta5, grand theft auto 5',
        )
        self.inactive_game = Game.objects.create(
            name='Inactive Game', slug='inactive-game', is_active=False,
        )

        # Create categories
        self.accounts = Category.objects.create(name='Accounts', slug='accounts')
        self.topup = Category.objects.create(name='Top-Up', slug='top-up')
        self.boosting = Category.objects.create(name='Boosting', slug='boosting')

        # Create game-category links
        self.val_accounts = GameCategory.objects.create(
            game=self.valorant, category=self.accounts,
        )
        self.val_topup = GameCategory.objects.create(
            game=self.valorant, category=self.topup,
        )
        self.val_boosting = GameCategory.objects.create(
            game=self.valorant, category=self.boosting,
        )
        self.pubg_accounts = GameCategory.objects.create(
            game=self.pubg, category=self.accounts,
        )
        self.gta_accounts = GameCategory.objects.create(
            game=self.gta, category=self.accounts,
        )
        self.inactive_gc = GameCategory.objects.create(
            game=self.inactive_game, category=self.accounts,
        )

    # Search by game name

    def test_search_by_game_name(self):
        response = self.client.get('/api/search/?q=Valorant')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['query'], 'Valorant')
        names = [r['display_name'] for r in response.data['results']]
        self.assertIn('Valorant Accounts', names)
        self.assertIn('Valorant Top-Up', names)
        self.assertIn('Valorant Boosting', names)
        # PUBG should not appear
        self.assertNotIn('PUBG Mobile Accounts', names)

    def test_search_game_name_case_insensitive(self):
        response = self.client.get('/api/search/?q=valorant')

        self.assertEqual(response.status_code, 200)
        names = [r['display_name'] for r in response.data['results']]
        self.assertIn('Valorant Accounts', names)

    def test_search_game_name_partial_match(self):
        response = self.client.get('/api/search/?q=PUBG')

        self.assertEqual(response.status_code, 200)
        names = [r['display_name'] for r in response.data['results']]
        self.assertIn('PUBG Mobile Accounts', names)

    # Search by game keywords / aliases

    def test_search_by_keyword_alias(self):
        """Searching 'gta' should find 'GTA 5 Accounts' via search_keywords."""
        response = self.client.get('/api/search/?q=gta')

        self.assertEqual(response.status_code, 200)
        names = [r['display_name'] for r in response.data['results']]
        self.assertIn('GTA 5 Accounts', names)

    def test_search_by_full_alias(self):
        """Searching 'grand theft auto' should find GTA 5 categories."""
        response = self.client.get('/api/search/?q=grand theft auto')

        self.assertEqual(response.status_code, 200)
        names = [r['display_name'] for r in response.data['results']]
        self.assertIn('GTA 5 Accounts', names)

    def test_search_keyword_does_not_match_unrelated(self):
        response = self.client.get('/api/search/?q=gta')

        self.assertEqual(response.status_code, 200)
        names = [r['display_name'] for r in response.data['results']]
        self.assertNotIn('Valorant Accounts', names)

    # Search by category name

    def test_search_by_category_name(self):
        response = self.client.get('/api/search/?q=Accounts')

        self.assertEqual(response.status_code, 200)
        names = [r['display_name'] for r in response.data['results']]
        self.assertIn('Valorant Accounts', names)
        self.assertIn('PUBG Mobile Accounts', names)
        self.assertIn('GTA 5 Accounts', names)
        # Boosting and Top-Up should NOT appear
        self.assertNotIn('Valorant Boosting', names)
        self.assertNotIn('Valorant Top-Up', names)

    def test_search_by_category_name_case_insensitive(self):
        response = self.client.get('/api/search/?q=boosting')

        self.assertEqual(response.status_code, 200)
        names = [r['display_name'] for r in response.data['results']]
        self.assertIn('Valorant Boosting', names)

    # Exclusions

    def test_search_excludes_inactive_games(self):
        response = self.client.get('/api/search/?q=Inactive')

        self.assertEqual(response.status_code, 200)
        names = [r['display_name'] for r in response.data['results']]
        self.assertNotIn('Inactive Game Accounts', names)

    def test_search_excludes_inactive_game_when_searching_category(self):
        """Searching 'Accounts' should not return categories under inactive games."""
        response = self.client.get('/api/search/?q=Accounts')

        self.assertEqual(response.status_code, 200)
        game_names = [r['game_name'] for r in response.data['results']]
        self.assertNotIn('Inactive Game', game_names)

    # Empty / short queries

    def test_search_empty_query_returns_empty(self):
        response = self.client.get('/api/search/?q=')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'], [])

    def test_search_missing_query_returns_empty(self):
        response = self.client.get('/api/search/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'], [])

    def test_search_short_query_returns_empty(self):
        response = self.client.get('/api/search/?q=V')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['query'], 'V')
        self.assertEqual(response.data['results'], [])

    def test_search_rejects_overlong_query(self):
        response = self.client.get('/api/search/?q=' + 'x' * 81)

        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.data)

    def test_search_no_match_returns_empty(self):
        response = self.client.get('/api/search/?q=zzzznonexistent')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'], [])

    def test_search_whitespace_only_returns_empty(self):
        response = self.client.get('/api/search/?q=%20%20%20')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'], [])

    # Response structure

    def test_search_response_structure(self):
        response = self.client.get('/api/search/?q=Valorant')

        self.assertEqual(response.status_code, 200)
        self.assertIn('query', response.data)
        self.assertIn('results', response.data)
        self.assertEqual(response.data['query'], 'Valorant')

    def test_search_result_contains_expected_fields(self):
        response = self.client.get('/api/search/?q=Valorant')

        self.assertEqual(response.status_code, 200)
        result = response.data['results'][0]
        for field in ('id', 'display_name', 'game_name', 'game_slug',
                       'game_icon_url', 'category_name', 'category_slug'):
            self.assertIn(field, result, f'Missing field: {field}')

    def test_search_result_display_name_format(self):
        """display_name should be '{Game Name} {Category Name}'."""
        response = self.client.get('/api/search/?q=Valorant')

        self.assertEqual(response.status_code, 200)
        result = next(r for r in response.data['results'] if r['category_slug'] == 'accounts')
        self.assertEqual(result['display_name'], 'Valorant Accounts')
        self.assertEqual(result['game_name'], 'Valorant')
        self.assertEqual(result['game_slug'], 'valorant')
        self.assertEqual(result['category_name'], 'Accounts')
        self.assertEqual(result['category_slug'], 'accounts')

    # Results limit

    def test_search_results_limited_to_fifty(self):
        """At most 50 results should be returned."""
        game = Game.objects.create(name='ManyCategories', slug='many-categories', is_active=True)
        for i in range(55):
            cat = Category.objects.create(name=f'Cat{i}', slug=f'cat{i}')
            GameCategory.objects.create(game=game, category=cat)

        response = self.client.get('/api/search/?q=ManyCategories')

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(response.data['results']), 50)

    # Public access

    def test_search_is_public(self):
        """Search endpoint should work without authentication."""
        response = self.client.get('/api/search/?q=Valorant')

        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)
        self.assertGreater(len(response.data['results']), 0)

    # No duplicates

    def test_search_no_duplicate_results(self):
        """A game-category matching both game name and category name should appear once."""
        response = self.client.get('/api/search/?q=Valorant')

        self.assertEqual(response.status_code, 200)
        ids = [r['id'] for r in response.data['results']]
        self.assertEqual(len(ids), len(set(ids)), 'Duplicate result IDs found')



# ── Notification Tests ────────────────────────────────────────────────────────

class NotificationTests(TestCase):
    """Tests for the notification system."""

    def setUp(self):
        self.client = APIClient()
        self.buyer = User.objects.create_user(username='notif_buyer', password='testpass123')
        self.seller = User.objects.create_user(username='notif_seller', password='testpass123')
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save()

        # Create wallet with balance for buyer
        wallet, _ = Wallet.objects.get_or_create(user=self.buyer)
        wallet.balance = Decimal('10000.00')
        wallet.save()

        # Create game, category, game-category, and listing
        game = Game.objects.create(name='TestGame', slug='testgame')
        cat = Category.objects.create(name='Accounts', slug='accounts')
        gc = GameCategory.objects.create(game=game, category=cat)
        self.listing = Listing.objects.create(
            seller=self.seller,
            game_category=gc,
            title='Test Listing',
            description='test',
            price=Decimal('100.00'),
            status='active',
            quantity=10,
        )

    # ── Notification creation on order events ─────────────────────────────

    def test_buy_creates_notification_for_seller(self):
        """Buying a listing should create a new_order notification for the seller."""
        self.client.force_authenticate(user=self.buyer)
        response = self.client.post('/api/orders/buy/', {'listing_id': self.listing.id, 'quantity': 1})
        self.assertEqual(response.status_code, 201)

        notif = Notification.objects.filter(recipient=self.seller, notification_type='new_order').first()
        self.assertIsNotNone(notif)
        self.assertIn('notif_buyer', notif.title)
        self.assertIsNotNone(notif.order)

    def test_deliver_creates_notification_for_buyer(self):
        """Delivering an order should create an order_delivered notification for the buyer."""
        self.client.force_authenticate(user=self.buyer)
        resp = self.client.post('/api/orders/buy/', {'listing_id': self.listing.id, 'quantity': 1})
        order_id = resp.data['id']

        self.client.force_authenticate(user=self.seller)
        self.client.post(f'/api/orders/{order_id}/deliver/', {'delivery_note': 'Here it is'})

        notif = Notification.objects.filter(recipient=self.buyer, notification_type='order_delivered').first()
        self.assertIsNotNone(notif)
        self.assertIn('delivered', notif.title.lower())

    def test_confirm_creates_notification_for_seller(self):
        """Confirming an order should create an order_confirmed notification for the seller."""
        self.client.force_authenticate(user=self.buyer)
        resp = self.client.post('/api/orders/buy/', {'listing_id': self.listing.id, 'quantity': 1})
        order_id = resp.data['id']

        self.client.force_authenticate(user=self.seller)
        self.client.post(f'/api/orders/{order_id}/deliver/')

        self.client.force_authenticate(user=self.buyer)
        self.client.post(f'/api/orders/{order_id}/confirm/')

        notif = Notification.objects.filter(recipient=self.seller, notification_type='order_confirmed').first()
        self.assertIsNotNone(notif)
        self.assertIn('confirmed', notif.title.lower())

    def test_dispute_creates_notification_for_seller(self):
        """Disputing an order should create an order_disputed notification for the seller."""
        self.client.force_authenticate(user=self.buyer)
        resp = self.client.post('/api/orders/buy/', {'listing_id': self.listing.id, 'quantity': 1})
        order_id = resp.data['id']

        self.client.post(f'/api/orders/{order_id}/dispute/', {'reason': 'Scam'})

        notif = Notification.objects.filter(recipient=self.seller, notification_type='order_disputed').first()
        self.assertIsNotNone(notif)
        self.assertIn('disputed', notif.title.lower())

    def test_review_creates_notification_for_seller(self):
        """Leaving a review should create a new_review notification for the seller."""
        self.client.force_authenticate(user=self.buyer)
        resp = self.client.post('/api/orders/buy/', {'listing_id': self.listing.id, 'quantity': 1})
        order_id = resp.data['id']

        self.client.force_authenticate(user=self.seller)
        self.client.post(f'/api/orders/{order_id}/deliver/')

        self.client.force_authenticate(user=self.buyer)
        self.client.post(f'/api/orders/{order_id}/confirm/')

        self.client.post('/api/reviews/', {'order_id': order_id, 'rating': 5, 'comment': 'Great!'})

        notif = Notification.objects.filter(recipient=self.seller, notification_type='new_review').first()
        self.assertIsNotNone(notif)
        self.assertIn('5', notif.title)

    # ── Notification API endpoints ────────────────────────────────────────

    def test_notification_list_requires_auth(self):
        """Notification list should require authentication."""
        response = self.client.get('/api/notifications/')
        self.assertEqual(response.status_code, 401)

    def test_notification_list_returns_user_notifications(self):
        """Notification list should return only the authenticated user's notifications."""
        Notification.objects.create(
            recipient=self.seller, notification_type='new_order',
            title='Test notif', message='Test',
        )
        Notification.objects.create(
            recipient=self.buyer, notification_type='order_delivered',
            title='Other notif', message='Other',
        )

        self.client.force_authenticate(user=self.seller)
        response = self.client.get('/api/notifications/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['notifications']), 1)
        self.assertEqual(response.data['notifications'][0]['title'], 'Test notif')

    def test_notification_list_includes_unread_count(self):
        """Notification list should include unread_count."""
        Notification.objects.create(
            recipient=self.buyer, notification_type='new_order', title='N1',
        )
        Notification.objects.create(
            recipient=self.buyer, notification_type='new_order', title='N2', is_read=True,
        )

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get('/api/notifications/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['unread_count'], 1)

    def test_mark_single_notification_read(self):
        """POST notification_id should mark that specific notification as read."""
        notif = Notification.objects.create(
            recipient=self.buyer, notification_type='new_order', title='Test',
        )

        self.client.force_authenticate(user=self.buyer)
        response = self.client.post('/api/notifications/read/', {'notification_id': notif.id})

        self.assertEqual(response.status_code, 200)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_mark_all_notifications_read(self):
        """POST notification_id='all' should mark all unread notifications as read."""
        Notification.objects.create(recipient=self.buyer, notification_type='new_order', title='N1')
        Notification.objects.create(recipient=self.buyer, notification_type='new_order', title='N2')

        self.client.force_authenticate(user=self.buyer)
        response = self.client.post('/api/notifications/read/', {'notification_id': 'all'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Notification.objects.filter(recipient=self.buyer, is_read=False).count(), 0)

    def test_unread_count_endpoint(self):
        """GET /api/notifications/unread-count/ should return unread notification count."""
        Notification.objects.create(recipient=self.buyer, notification_type='new_order', title='N1')
        Notification.objects.create(recipient=self.buyer, notification_type='new_order', title='N2')
        Notification.objects.create(recipient=self.buyer, notification_type='new_order', title='N3', is_read=True)

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get('/api/notifications/unread-count/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['unread_count'], 2)

    def test_notification_serializer_fields(self):
        """Notification response should include expected fields."""
        Notification.objects.create(
            recipient=self.buyer, notification_type='new_order',
            title='Test', message='A message',
        )

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get('/api/notifications/')

        notif = response.data['notifications'][0]
        expected_fields = {'id', 'notification_type', 'title', 'message', 'is_read', 'order_id', 'order_number', 'review_id', 'created_at'}
        self.assertEqual(set(notif.keys()), expected_fields)

    def test_cannot_mark_other_users_notification_read(self):
        """User should not be able to mark another user's notification as read."""
        notif = Notification.objects.create(
            recipient=self.seller, notification_type='new_order', title='Test',
        )

        self.client.force_authenticate(user=self.buyer)
        response = self.client.post('/api/notifications/read/', {'notification_id': notif.id})

        self.assertEqual(response.status_code, 404)

    def test_notification_list_pagination(self):
        """Notification list should support pagination."""
        for i in range(5):
            Notification.objects.create(
                recipient=self.buyer, notification_type='new_order', title=f'N{i}',
            )

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get('/api/notifications/?limit=2&offset=0')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['notifications']), 2)
        self.assertEqual(response.data['pagination']['count'], 5)
        self.assertIsNotNone(response.data['pagination']['next_offset'])

    def test_notification_ordered_by_newest_first(self):
        """Notifications should be ordered by created_at descending (newest first)."""
        n1 = Notification.objects.create(recipient=self.buyer, notification_type='new_order', title='First')
        # Ensure different created_at by updating directly
        from django.utils import timezone
        import datetime
        Notification.objects.filter(pk=n1.pk).update(
            created_at=timezone.now() - datetime.timedelta(minutes=5)
        )
        n2 = Notification.objects.create(recipient=self.buyer, notification_type='new_order', title='Second')

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get('/api/notifications/')

        self.assertEqual(response.data['notifications'][0]['title'], 'Second')
        self.assertEqual(response.data['notifications'][1]['title'], 'First')


    def test_refund_creates_notification_for_buyer(self):
        """Seller refunding an order should create an order_cancelled notification for the buyer."""
        self.client.force_authenticate(user=self.buyer)
        resp = self.client.post('/api/orders/buy/', {'listing_id': self.listing.id, 'quantity': 1})
        order_id = resp.data['id']

        # Seller refunds
        self.client.force_authenticate(user=self.seller)
        self.client.post(f'/api/orders/{order_id}/refund/')

        notif = Notification.objects.filter(
            recipient=self.buyer, notification_type='order_cancelled'
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn('refund', notif.title.lower())
        self.assertIn('wallet', notif.message.lower())


class AccountSecurityFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.origin = 'http://testserver'
        self.user = User.objects.create_user(
            username='secureuser',
            email='secure@example.com',
            password='OriginalPass123!x',
        )

    def tearDown(self):
        cache.clear()

    def post_public(self, path, data):
        return self.client.post(
            path,
            data,
            format='json',
            HTTP_ORIGIN=self.origin,
        )

    @patch('core.views.send_password_reset_code')
    @patch('core.views.generate_password_reset_code', return_value='123456')
    def test_password_reset_token_is_opaque_and_unknown_email_shape_matches(self, code_mock, send_mock):
        existing = self.post_public(
            '/api/auth/password/reset-request/',
            {'email': 'secure@example.com'},
        )
        unknown = self.post_public(
            '/api/auth/password/reset-request/',
            {'email': 'missing@example.com'},
        )

        self.assertEqual(existing.status_code, 200)
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(set(existing.data.keys()), {'message', 'token'})
        self.assertEqual(set(unknown.data.keys()), {'message', 'token'})
        self.assertEqual(existing.data['message'], unknown.data['message'])
        self.assertNotEqual(existing.data['token'], unknown.data['token'])
        send_mock.assert_called_once()
        code_mock.assert_called_once()

        for response in (existing, unknown):
            with self.assertRaises(signing.BadSignature):
                signing.loads(response.data['token'], salt='core.password_reset')

    @patch('core.views.send_password_reset_code')
    @patch('core.views.generate_password_reset_code', return_value='123456')
    def test_password_reset_rejects_same_password_and_consumes_successful_challenge(self, *_mocks):
        login_response = self.post_public(
            '/api/auth/login/',
            {'email': 'secure@example.com', 'password': 'OriginalPass123!x'},
        )
        self.assertEqual(login_response.status_code, 200)
        old_refresh = login_response.cookies[settings.JWT_AUTH_COOKIE_REFRESH].value

        request_response = self.post_public(
            '/api/auth/password/reset-request/',
            {'email': 'secure@example.com'},
        )
        token = request_response.data['token']

        same_password_response = self.post_public(
            '/api/auth/password/reset-confirm/',
            {
                'token': token,
                'code': '123456',
                'new_password': 'OriginalPass123!x',
                'new_password2': 'OriginalPass123!x',
            },
        )
        self.assertEqual(same_password_response.status_code, 400)
        self.assertIn('different', same_password_response.data['error'])

        success_response = self.post_public(
            '/api/auth/password/reset-confirm/',
            {
                'token': token,
                'code': '123456',
                'new_password': 'BetterPass123!x',
                'new_password2': 'BetterPass123!x',
            },
        )
        self.assertEqual(success_response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('BetterPass123!x'))

        old_refresh_reuse = self.post_public(
            '/api/auth/refresh/',
            {'refresh': old_refresh},
        )
        self.assertEqual(old_refresh_reuse.status_code, 401)

        replay_response = self.post_public(
            '/api/auth/password/reset-confirm/',
            {
                'token': token,
                'code': '123456',
                'new_password': 'AnotherPass123!x',
                'new_password2': 'AnotherPass123!x',
            },
        )
        self.assertEqual(replay_response.status_code, 400)
        self.assertIn('invalid or expired', replay_response.data['error'])

    @patch('core.views.send_password_reset_code')
    @patch('core.views.generate_password_reset_code', return_value='123456')
    def test_password_reset_challenge_locks_after_failed_attempts(self, *_mocks):
        request_response = self.post_public(
            '/api/auth/password/reset-request/',
            {'email': 'secure@example.com'},
        )
        token = request_response.data['token']

        for _ in range(5):
            wrong_response = self.post_public(
                '/api/auth/password/reset-confirm/',
                {
                    'token': token,
                    'code': '000000',
                    'new_password': 'BetterPass123!x',
                    'new_password2': 'BetterPass123!x',
                },
            )
            self.assertEqual(wrong_response.status_code, 400)

        locked_response = self.post_public(
            '/api/auth/password/reset-confirm/',
            {
                'token': token,
                'code': '123456',
                'new_password': 'BetterPass123!x',
                'new_password2': 'BetterPass123!x',
            },
        )
        self.assertEqual(locked_response.status_code, 400)
        self.assertIn('invalid or expired', locked_response.data['error'])

    @patch('core.views.send_new_email_change_code')
    @patch('core.views.send_email_change_code')
    @patch('core.views.generate_email_change_code', side_effect=['111111', '222222'])
    def test_email_change_token_is_opaque_and_requires_code(self, *_mocks):
        self.client.force_authenticate(user=self.user)

        request_response = self.client.post(
            '/api/auth/email/request-change/',
            {'new_email': 'new-secure@example.com'},
            format='json',
            HTTP_ORIGIN=self.origin,
        )
        self.assertEqual(request_response.status_code, 200)
        token = request_response.data['token']
        with self.assertRaises(signing.BadSignature):
            signing.loads(token, salt='core.email_change')

        wrong_code_response = self.client.post(
            '/api/auth/email/confirm-change/',
            {'token': token, 'current_code': '111111', 'new_code': '000000'},
            format='json',
            HTTP_ORIGIN=self.origin,
        )
        self.assertEqual(wrong_code_response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'secure@example.com')

        success_response = self.client.post(
            '/api/auth/email/confirm-change/',
            {'token': token, 'current_code': '111111', 'new_code': '222222'},
            format='json',
            HTTP_ORIGIN=self.origin,
        )
        self.assertEqual(success_response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new-secure@example.com')

    @patch('core.views.send_new_email_change_code')
    @patch('core.views.send_email_change_code')
    @patch('core.views.generate_email_change_code', side_effect=['111111', '222222'])
    def test_email_change_challenge_locks_after_failed_attempts(self, *_mocks):
        self.client.force_authenticate(user=self.user)
        request_response = self.client.post(
            '/api/auth/email/request-change/',
            {'new_email': 'new-secure@example.com'},
            format='json',
            HTTP_ORIGIN=self.origin,
        )
        token = request_response.data['token']

        for _ in range(5):
            wrong_response = self.client.post(
                '/api/auth/email/confirm-change/',
                {'token': token, 'current_code': '111111', 'new_code': '000000'},
                format='json',
                HTTP_ORIGIN=self.origin,
            )
            self.assertEqual(wrong_response.status_code, 400)

        locked_response = self.client.post(
            '/api/auth/email/confirm-change/',
            {'token': token, 'current_code': '111111', 'new_code': '222222'},
            format='json',
            HTTP_ORIGIN=self.origin,
        )
        self.assertEqual(locked_response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'secure@example.com')

    def test_username_update_uses_django_username_validator(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.put(
            '/api/auth/profile/',
            {'username': 'bad/name'},
            format='json',
            HTTP_ORIGIN=self.origin,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('username', response.data)

    def test_profile_update_records_username_change_and_enforces_cooldown(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.put(
            '/api/auth/profile/',
            {'username': 'secureuser2'},
            format='json',
            HTTP_ORIGIN=self.origin,
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.username, 'secureuser2')
        self.assertIsNotNone(self.user.profile.username_changed_at)
        self.assertEqual(response.data['user']['username'], 'secureuser2')

        cooldown_response = self.client.put(
            '/api/auth/profile/',
            {'username': 'secureuser3'},
            format='json',
            HTTP_ORIGIN=self.origin,
        )

        self.assertEqual(cooldown_response.status_code, 400)
        self.assertIn('username', cooldown_response.data)
        self.assertIn('once every 90 days', str(cooldown_response.data['username'][0]))

    def test_profile_update_checks_fresh_locked_profile_for_cooldown(self):
        # Populate the related-object cache, then update the database row directly.
        # The view must validate against its locked UserProfile row, not this stale cache.
        self.assertIsNone(self.user.profile.username_changed_at)
        UserProfile.objects.filter(user=self.user).update(username_changed_at=timezone.now())
        self.client.force_authenticate(user=self.user)

        response = self.client.put(
            '/api/auth/profile/',
            {'username': 'secureuser2'},
            format='json',
            HTTP_ORIGIN=self.origin,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('username', response.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'secureuser')

    def test_email_change_rejects_current_or_existing_email(self):
        User.objects.create_user(
            username='othersecure',
            email='other-secure@example.com',
            password='OriginalPass123!x',
        )
        self.client.force_authenticate(user=self.user)

        current_response = self.client.post(
            '/api/auth/email/request-change/',
            {'new_email': 'secure@example.com'},
            format='json',
            HTTP_ORIGIN=self.origin,
        )
        existing_response = self.client.post(
            '/api/auth/email/request-change/',
            {'new_email': 'other-secure@example.com'},
            format='json',
            HTTP_ORIGIN=self.origin,
        )

        self.assertEqual(current_response.status_code, 400)
        self.assertEqual(existing_response.status_code, 400)
        self.assertIn('current email', str(current_response.data['new_email'][0]))
        self.assertIn('already exists', str(existing_response.data['new_email'][0]))

    def test_change_password_rejects_same_password(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            '/api/auth/password/',
            {
                'current_password': 'OriginalPass123!x',
                'new_password': 'OriginalPass123!x',
                'new_password2': 'OriginalPass123!x',
            },
            format='json',
            HTTP_ORIGIN=self.origin,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('different', response.data['error'])

    def test_avatar_upload_and_remove_update_user_profile(self):
        self.client.force_authenticate(user=self.user)

        upload_response = self.client.post(
            '/api/auth/avatar/',
            {'avatar': make_image_file(name='avatar.png')},
            format='multipart',
            HTTP_ORIGIN=self.origin,
        )

        self.assertEqual(upload_response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.avatar.name.startswith('avatars/'))
        self.assertIn('/media/avatars/', upload_response.data['user']['avatar_url'])

        remove_response = self.client.delete(
            '/api/auth/avatar/',
            HTTP_ORIGIN=self.origin,
        )

        self.assertEqual(remove_response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.avatar)
        self.assertIsNone(remove_response.data['user']['avatar_url'])

    def test_avatar_upload_rejects_missing_image(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            '/api/auth/avatar/',
            {},
            format='multipart',
            HTTP_ORIGIN=self.origin,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['error'], 'No image provided.')

