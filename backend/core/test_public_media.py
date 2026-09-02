"""Stable public-media addresses (avatars).

Ahrefs' first crawl (2026-09-02) flagged ~2,000 pages with a broken image:
the store avatar's 24h-signed R2 URL was baked into cached page HTML and had
expired by the time the crawler fetched the page. Avatars now resolve through
/api/media/avatars/<name>, which never expires and redirects to a fresh
signed URL on every hit.
"""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.storage import storages
from django.test import RequestFactory, TestCase
from rest_framework.test import APIClient

from .models import Category, Game, GameCategory, Listing, Message, Conversation
from .storage_backends import (
    CLOUDFLARE_R2_NAME_PREFIX,
    PUBLIC_MEDIA_REDIRECT_CACHE_SECONDS,
    PUBLIC_MEDIA_SIGNED_URL_SECONDS,
    public_avatar_url,
    public_media_name,
)

R2_AVATAR = f'{CLOUDFLARE_R2_NAME_PREFIX}avatars/profile-green-bg.webp'
SIGNED = 'https://signed-r2.example/avatars/profile-green-bg.webp?X-Amz-Signature=abc'


def patch_storage_url(**kwargs):
    """Patch url() on whichever storage backend is active: local dev runs the
    real R2 backend, CI runs FileSystemStorage."""
    return patch.object(type(storages['default']), 'url', **kwargs)


def set_avatar(user, name):
    """Point a profile at a stored file by name without touching storage."""
    profile = user.profile
    profile.avatar = name
    profile.save(update_fields=['avatar'])
    return profile


class PublicAvatarUrlTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='store', password='password123')

    def test_r2_avatar_gets_a_stable_unsigned_address(self):
        profile = set_avatar(self.user, R2_AVATAR)

        self.assertEqual(public_media_name(profile.avatar, 'avatars'), 'profile-green-bg.webp')
        self.assertEqual(public_avatar_url(profile.avatar), '/api/media/avatars/profile-green-bg.webp')

        request = RequestFactory().get('/api/listings/1/')
        self.assertEqual(
            public_avatar_url(profile.avatar, request=request),
            'http://testserver/api/media/avatars/profile-green-bg.webp',
        )

    def test_legacy_local_avatar_keeps_its_plain_media_address(self):
        profile = set_avatar(self.user, 'avatars/old-avatar.png')

        self.assertIsNone(public_media_name(profile.avatar, 'avatars'))
        self.assertEqual(public_avatar_url(profile.avatar), '/media/avatars/old-avatar.png')

    def test_missing_avatar_is_none(self):
        self.assertIsNone(public_avatar_url(self.user.profile.avatar))
        self.assertIsNone(public_avatar_url(None))

    def test_r2_object_outside_the_avatar_folder_is_not_given_a_public_name(self):
        profile = set_avatar(self.user, f'{CLOUDFLARE_R2_NAME_PREFIX}chat_images/secret.webp')
        self.assertIsNone(public_media_name(profile.avatar, 'avatars'))


class PublicMediaEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(username='store', password='password123')

    def test_redirects_to_a_freshly_signed_r2_url_with_a_short_public_cache(self):
        set_avatar(self.user, R2_AVATAR)

        with patch_storage_url(return_value=SIGNED) as mock_url:
            response = self.client.get('/api/media/avatars/profile-green-bg.webp')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], SIGNED)
        self.assertEqual(
            response['Cache-Control'],
            f'public, max-age={PUBLIC_MEDIA_REDIRECT_CACHE_SECONDS}',
        )
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        # Signed for much longer than the redirect may be cached, with the
        # image itself marked cacheable and typed for the browser.
        self.assertEqual(mock_url.call_args.args[0], R2_AVATAR)
        self.assertEqual(mock_url.call_args.kwargs['expire'], PUBLIC_MEDIA_SIGNED_URL_SECONDS)
        self.assertEqual(
            mock_url.call_args.kwargs['parameters'],
            {
                'ResponseCacheControl': f'public, max-age={PUBLIC_MEDIA_SIGNED_URL_SECONDS}',
                'ResponseContentType': 'image/webp',
            },
        )

    def test_head_works_like_get(self):
        set_avatar(self.user, R2_AVATAR)

        with patch_storage_url(return_value=SIGNED):
            response = self.client.head('/api/media/avatars/profile-green-bg.webp')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], SIGNED)

    def test_signed_url_is_reused_briefly_so_browsers_can_cache_the_image(self):
        set_avatar(self.user, R2_AVATAR)

        with patch_storage_url(return_value=SIGNED) as mock_url:
            first = self.client.get('/api/media/avatars/profile-green-bg.webp')
            second = self.client.get('/api/media/avatars/profile-green-bg.webp')

        self.assertEqual(first['Location'], second['Location'])
        self.assertEqual(mock_url.call_count, 1)

    def test_legacy_local_avatar_redirects_to_its_media_path(self):
        set_avatar(self.user, 'avatars/old-avatar.png')

        response = self.client.get('/api/media/avatars/old-avatar.png')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'http://testserver/media/avatars/old-avatar.png')

    def test_unknown_name_is_404_and_never_signed(self):
        set_avatar(self.user, R2_AVATAR)

        with patch_storage_url() as mock_url:
            response = self.client.get('/api/media/avatars/does-not-exist.webp')

        self.assertEqual(response.status_code, 404)
        mock_url.assert_not_called()

    def test_unknown_kind_is_404(self):
        set_avatar(self.user, R2_AVATAR)

        response = self.client.get('/api/media/chat_images/profile-green-bg.webp')

        self.assertEqual(response.status_code, 404)

    def test_cannot_sign_a_private_object_that_is_not_an_avatar(self):
        # A chat image with the same basename exists in the bucket, but no
        # profile points at it as an avatar -> nothing to resolve.
        set_avatar(self.user, R2_AVATAR)
        other = User.objects.create_user(username='buyer', password='password123')
        conversation = Conversation.objects.create()
        conversation.participants.add(self.user, other)
        Message.objects.create(
            conversation=conversation,
            sender=other,
            content='',
            image=f'{CLOUDFLARE_R2_NAME_PREFIX}chat_images/leak.webp',
        )

        with patch_storage_url() as mock_url:
            response = self.client.get('/api/media/avatars/leak.webp')

        self.assertEqual(response.status_code, 404)
        mock_url.assert_not_called()

    def test_unsafe_content_type_is_404(self):
        set_avatar(self.user, f'{CLOUDFLARE_R2_NAME_PREFIX}avatars/payload.svg')

        with patch_storage_url() as mock_url:
            response = self.client.get('/api/media/avatars/payload.svg')

        self.assertEqual(response.status_code, 404)
        mock_url.assert_not_called()


class AvatarPayloadTests(TestCase):
    """Every place the API hands out an avatar uses the stable address."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.seller = User.objects.create_user(
            username='store', password='password123', email='store@example.com',
        )
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])
        set_avatar(self.seller, R2_AVATAR)

        game = Game.objects.create(name='Steam', slug='steam')
        category = Category.objects.create(name='Gift Cards', slug='gift-cards')
        game_category = GameCategory.objects.create(game=game, category=category)
        self.listing = Listing.objects.create(
            seller=self.seller,
            game_category=game_category,
            title='5 USD (Argentina)',
            price=Decimal('1710.00'),
            status='active',
        )

    def test_listing_detail_carries_the_stable_seller_avatar(self):
        with patch_storage_url() as mock_url:
            response = self.client.get(f'/api/listings/{self.listing.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['seller_avatar_url'],
            'http://testserver/api/media/avatars/profile-green-bg.webp',
        )
        # No signature is minted while rendering the page payload.
        mock_url.assert_not_called()

    def test_category_browse_carries_the_stable_seller_avatar(self):
        with patch_storage_url() as mock_url:
            response = self.client.get('/api/games/steam/gift-cards/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['listings'][0]['seller_avatar_url'],
            'http://testserver/api/media/avatars/profile-green-bg.webp',
        )
        mock_url.assert_not_called()

    def test_seller_profile_carries_the_stable_avatar_fresh_and_cached(self):
        with patch_storage_url() as mock_url:
            fresh = self.client.get('/api/seller/profile/store/')
            cached = self.client.get('/api/seller/profile/store/')

        self.assertEqual(fresh.status_code, 200)
        expected = 'http://testserver/api/media/avatars/profile-green-bg.webp'
        self.assertEqual(fresh.data['avatar_url'], expected)
        self.assertEqual(cached.data['avatar_url'], expected)
        mock_url.assert_not_called()

    def test_me_endpoint_carries_the_stable_avatar(self):
        self.client.force_authenticate(user=self.seller)

        with patch_storage_url() as mock_url:
            response = self.client.get('/api/auth/me/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['avatar_url'],
            'http://testserver/api/media/avatars/profile-green-bg.webp',
        )
        mock_url.assert_not_called()
