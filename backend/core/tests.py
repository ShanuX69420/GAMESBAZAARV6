from decimal import Decimal
from io import BytesIO
from threading import Barrier, Thread
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections, IntegrityError, transaction as db_transaction
from PIL import Image
from django.test import RequestFactory, TestCase, TransactionTestCase
from rest_framework.test import APIClient

from .admin import OrderAdmin, TopUpRequestAdmin
from .models import (
    Category, Conversation, Game, GameCategory, Listing, Message, Order,
    TopUpRequest, Wallet, WalletTransaction,
)


def make_image_file(name='proof.png', image_format='PNG', content_type='image/png'):
    buffer = BytesIO()
    image = Image.new('RGB', (2, 2), color='green')
    image.save(buffer, format=image_format)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


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
        category = Category.objects.create(name='Accounts', slug='accounts')
        self.game_category = GameCategory.objects.create(game=game, category=category)

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
        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.seller_wallet,
                transaction_type='sale',
                reference_id=f'order_{order.pk}',
            ).count(),
            1,
        )
        self.assertEqual(
            WalletTransaction.objects.filter(
                wallet=self.seller_wallet,
                transaction_type='commission',
                reference_id=f'order_{order.pk}',
            ).count(),
            1,
        )


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
