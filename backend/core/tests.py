from decimal import Decimal
from io import BytesIO
from threading import Barrier, Thread
from urllib.parse import urlsplit
from unittest.mock import patch

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections, IntegrityError, transaction as db_transaction
from PIL import Image
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.urls import resolve
from rest_framework import permissions
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.test import APIClient

from .admin import OrderAdmin, TopUpRequestAdmin
from .models import (
    Category, Conversation, Filter, FilterOption, Game, GameCategory, GameCategoryFilter,
    Listing, Message, Order, Review,
    PlatformLedgerEntry, SellerCommissionOverride, TopUpRequest, Wallet, WalletTransaction,
)
from .serializers import WalletTransactionSerializer


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


THROTTLE_TEST_REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_RATES': {
        'auth_login': '1/min',
        'auth_refresh': '1/min',
        'auth_register': '1/min',
        'chat_start': '1/min',
        'chat_message': '1/min',
        'chat_upload': '1/min',
        'topup_request': '1/min',
        'heartbeat': '1/min',
        'search': '1/min',
    },
}


class ApiThrottleConfigurationTests(TestCase):
    def test_sensitive_endpoints_have_scoped_throttles(self):
        cases = {
            '/api/auth/login/': 'auth_login',
            '/api/auth/refresh/': 'auth_refresh',
            '/api/auth/register/': 'auth_register',
            '/api/chat/start/': 'chat_start',
            '/api/chat/1/send/': 'chat_message',
            '/api/chat/1/send-image/': 'chat_upload',
            '/api/wallet/top-up/': 'topup_request',
            '/api/heartbeat/': 'heartbeat',
            '/api/search/': 'search',
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
        User.objects.create_user(username='buyer', password='password123')

        first = self.client.post(
            '/api/auth/login/',
            {'username': 'buyer', 'password': 'wrong-password'},
            format='json',
            HTTP_ORIGIN='http://localhost:3000',
        )
        second = self.client.post(
            '/api/auth/login/',
            {'username': 'buyer', 'password': 'wrong-password'},
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

    def test_search_is_rate_limited(self):
        first = self.client.get('/api/search/?q=Valorant')
        second = self.client.get('/api/search/?q=Valorant')

        self.assertEqual(first.status_code, 200)
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
            {'username': 'cookiebuyer', 'password': 'password123'},
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
            'total_count': 5,
        })

        second_page = self.client.get('/api/listings/mine/?limit=2&offset=2')

        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(len(second_page.data['listings']), 2)
        self.assertEqual(second_page.data['pagination']['next_offset'], 4)
        self.assertEqual(second_page.data['pagination']['previous_offset'], 0)


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
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['unread_count'], 1)
        self.assertEqual(response.data[0]['last_message']['content'], 'latest buyer message')
        self.assertEqual(response.data[0]['other_user']['id'], self.seller.id)

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
        self.assertEqual(response.data[0]['id'], old_conversation.id)
        self.assertEqual(response.data[0]['last_message']['content'], 'old chat is newest now')
        self.assertEqual(response.data[1]['id'], newer_conversation.id)

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

    def test_buyer_orders_are_paginated(self):
        for index in range(25):
            self.create_order(index)

        self.client.force_authenticate(user=self.buyer)
        response = self.client.get('/api/orders/mine/?limit=10')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['orders']), 10)
        self.assertEqual(response.data['pagination']['count'], 25)
        self.assertEqual(response.data['pagination']['next_offset'], 10)

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


class ChatWebSocketTicketIntegrationTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.buyer = User.objects.create_user(username='buyer', password='password123')
        self.seller = User.objects.create_user(username='seller', password='password123')
        self.intruder = User.objects.create_user(username='intruder', password='password123')
        self.conversation = Conversation.objects.create()
        self.conversation.participants.add(self.buyer, self.seller)
        self.other_conversation = Conversation.objects.create()
        self.other_conversation.participants.add(self.buyer, self.intruder)

    def test_websocket_accepts_scoped_ticket_and_rejects_raw_jwt(self):
        from asgiref.sync import async_to_sync
        from channels.testing import WebsocketCommunicator
        from gamesbazaar.asgi import application
        from rest_framework_simplejwt.tokens import AccessToken

        from .services import create_chat_ws_ticket

        async def run_ticket_flow():
            ticket = create_chat_ws_ticket(self.buyer, self.conversation.id)
            communicator = WebsocketCommunicator(
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
            jwt_communicator = WebsocketCommunicator(
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
            communicator = WebsocketCommunicator(
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
            communicator = WebsocketCommunicator(
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
            communicator = WebsocketCommunicator(
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
            communicator = WebsocketCommunicator(
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
            communicator = WebsocketCommunicator(
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

