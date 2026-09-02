"""Public media bucket: permanent, unsigned URLs for avatars, icons and review
photos (the durable fix behind test_public_media's redirect shim)."""
from io import StringIO
from unittest.mock import Mock, PropertyMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIClient

from .models import Category, CategoryOption, Game, GameCategory, ReviewImage, UserProfile
from .storage_backends import (
    CLOUDFLARE_R2_NAME_PREFIX,
    PUBLIC_MEDIA_OBJECT_CACHE_CONTROL,
    CloudflareR2PublicStorage,
    CloudflareR2Storage,
    cached_media_url,
    get_public_media_storage,
    is_public_media_storage,
    public_avatar_url,
)

R2_SETTINGS = dict(
    CLOUDFLARE_R2_ENABLED=True,
    CLOUDFLARE_R2_BUCKET_NAME='gamesbazaar-media',
    CLOUDFLARE_R2_ACCESS_KEY_ID='access-key-id',
    CLOUDFLARE_R2_SECRET_ACCESS_KEY='secret-access-key',
    CLOUDFLARE_R2_ENDPOINT_URL='https://account-id.r2.cloudflarestorage.com',
    CLOUDFLARE_R2_PUBLIC_URL_EXPIRATION_SECONDS=86400,
    CLOUDFLARE_R2_PRIVATE_URL_EXPIRATION_SECONDS=300,
    CLOUDFLARE_R2_PUBLIC_BUCKET_NAME='gamesbazaarpublic',
    CLOUDFLARE_R2_PUBLIC_MEDIA_HOST='media.gamesbazaar.pk',
    CLOUDFLARE_R2_PUBLIC_MEDIA_ENABLED=True,
)
PUBLIC_MEDIA_STORAGES = {
    'default': {'BACKEND': 'core.storage_backends.CloudflareR2Storage'},
    'public_media': {'BACKEND': 'core.storage_backends.CloudflareR2PublicStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
PRIVATE_ONLY_STORAGES = {
    'default': {'BACKEND': 'core.storage_backends.CloudflareR2Storage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
AVATAR = f'{CLOUDFLARE_R2_NAME_PREFIX}avatars/profile-green-bg.webp'


def set_avatar(user, name):
    profile = user.profile
    profile.avatar = name
    profile.save(update_fields=['avatar'])
    return profile


@override_settings(STORAGES=PUBLIC_MEDIA_STORAGES, **R2_SETTINGS)
class PublicStorageTests(TestCase):
    def test_public_storage_urls_are_plain_and_permanent(self):
        storage = CloudflareR2PublicStorage()

        self.assertTrue(is_public_media_storage(storage))
        self.assertEqual(storage.bucket_name, 'gamesbazaarpublic')
        self.assertEqual(
            storage.url('r2/game_icons/steam.webp'),
            'https://media.gamesbazaar.pk/r2/game_icons/steam.webp',
        )
        # Even when a caller passes the signing knobs, nothing is signed.
        self.assertEqual(
            storage.url('r2/avatars/a.webp', parameters={'ResponseCacheControl': 'x'}, expire=60),
            'https://media.gamesbazaar.pk/r2/avatars/a.webp',
        )
        # Legacy local files keep their nginx-served path.
        self.assertEqual(storage.url('avatars/old.png'), '/media/avatars/old.png')
        self.assertEqual(
            storage.object_parameters['CacheControl'],
            PUBLIC_MEDIA_OBJECT_CACHE_CONTROL,
        )

    def test_private_storage_is_not_public(self):
        self.assertFalse(is_public_media_storage(CloudflareR2Storage()))
        self.assertFalse(is_public_media_storage(None))

    def test_public_media_fields_resolve_to_the_public_bucket(self):
        for model, field in (
            (UserProfile, 'avatar'),
            (Game, 'icon'),
            (CategoryOption, 'icon'),
            (ReviewImage, 'image'),
        ):
            with self.subTest(model=model.__name__):
                storage = model._meta.get_field(field).storage
                self.assertTrue(is_public_media_storage(storage))
                self.assertEqual(storage.bucket_name, 'gamesbazaarpublic')

    def test_cached_media_url_and_avatar_url_return_the_permanent_address(self):
        user = User.objects.create_user(username='store', password='password123')
        profile = set_avatar(user, AVATAR)
        request = RequestFactory().get('/api/listings/1/')

        expected = 'https://media.gamesbazaar.pk/r2/avatars/profile-green-bg.webp'
        with patch.object(CloudflareR2Storage, 'url') as private_url:
            self.assertEqual(cached_media_url(profile.avatar, request=request), expected)
            self.assertEqual(public_avatar_url(profile.avatar, request=request), expected)
            self.assertEqual(public_avatar_url(profile.avatar), expected)
        private_url.assert_not_called()


@override_settings(STORAGES=PRIVATE_ONLY_STORAGES, **{**R2_SETTINGS, 'CLOUDFLARE_R2_PUBLIC_MEDIA_ENABLED': False})
class PublicStorageFallbackTests(TestCase):
    def test_fields_fall_back_to_the_default_storage_until_the_bucket_is_switched_on(self):
        storage = get_public_media_storage()
        self.assertFalse(is_public_media_storage(storage))
        self.assertIsInstance(storage.__class__, type)
        self.assertEqual(storage.bucket_name, 'gamesbazaar-media')
        self.assertFalse(is_public_media_storage(UserProfile._meta.get_field('avatar').storage))


@override_settings(STORAGES=PUBLIC_MEDIA_STORAGES, **R2_SETTINGS)
class PublicMediaPayloadTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(username='store', password='password123')
        set_avatar(self.user, AVATAR)

    def test_redirect_shim_sends_old_links_to_the_permanent_address(self):
        with patch.object(CloudflareR2Storage, 'url') as private_url:
            response = self.client.get('/api/media/avatars/profile-green-bg.webp')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response['Location'],
            'https://media.gamesbazaar.pk/r2/avatars/profile-green-bg.webp',
        )
        self.assertEqual(response['Cache-Control'], 'public, max-age=86400')
        private_url.assert_not_called()

    def test_category_payload_carries_permanent_icon_and_avatar_urls(self):
        self.user.profile.seller_status = 'approved'
        self.user.profile.save(update_fields=['seller_status'])
        game = Game.objects.create(name='Steam', slug='steam', icon='r2/game_icons/steam.webp')
        category = Category.objects.create(name='Gift Cards', slug='gift-cards')
        game_category = GameCategory.objects.create(
            game=game, category=category, listing_mode='offer',
        )
        option = CategoryOption.objects.create(
            game_category=game_category, name='5 USD', icon='r2/option_icons/5usd.webp',
        )
        from decimal import Decimal
        from .models import Listing
        Listing.objects.create(
            seller=self.user, game_category=game_category, option=option,
            title='5 USD', price=Decimal('1710.00'), status='active',
        )

        with patch.object(CloudflareR2Storage, 'url') as private_url:
            response = self.client.get('/api/games/steam/gift-cards/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['options'][0]['icon_url'],
            'https://media.gamesbazaar.pk/r2/option_icons/5usd.webp',
        )
        self.assertEqual(
            response.data['listings'][0]['seller_avatar_url'],
            'https://media.gamesbazaar.pk/r2/avatars/profile-green-bg.webp',
        )
        private_url.assert_not_called()

        with patch.object(CloudflareR2Storage, 'url') as private_url:
            games = self.client.get('/api/games/')
        steam = next(g for g in games.data if g['slug'] == 'steam')
        self.assertEqual(steam['icon_url'], 'https://media.gamesbazaar.pk/r2/game_icons/steam.webp')
        private_url.assert_not_called()


@override_settings(STORAGES=PUBLIC_MEDIA_STORAGES, **R2_SETTINGS)
class MigratePublicMediaCommandTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(username='store', password='password123')
        set_avatar(user, AVATAR)
        Game.objects.create(name='Steam', slug='steam', icon='r2/game_icons/steam.webp')
        Game.objects.create(name='Old', slug='old', icon='game_icons/legacy.png')
        Game.objects.create(name='Lost', slug='lost', icon='r2/game_icons/lost.webp')
        Game.objects.create(name='Done', slug='done', icon='r2/game_icons/done.webp')

    def run_command(self, *args, public_has=(), private_has=()):
        client = Mock()
        out, err = StringIO(), StringIO()
        with (
            patch.object(CloudflareR2PublicStorage, 'exists', side_effect=lambda n: n in public_has),
            patch.object(CloudflareR2Storage, 'exists', side_effect=lambda n: n in private_has),
            patch.object(CloudflareR2PublicStorage, 'connection', new_callable=PropertyMock) as connection,
        ):
            connection.return_value = Mock(meta=Mock(client=client))
            call_command('migrate_public_media', *args, stdout=out, stderr=err)
        return client, out.getvalue(), err.getvalue()

    def test_copies_missing_objects_with_permanent_cache_headers(self):
        private_has = {AVATAR, 'r2/game_icons/steam.webp', 'r2/game_icons/done.webp'}
        client, out, err = self.run_command(
            public_has={'r2/game_icons/done.webp'},
            private_has=private_has,
        )

        copied = {call.kwargs['Key'] for call in client.copy_object.call_args_list}
        self.assertEqual(copied, {AVATAR, 'r2/game_icons/steam.webp'})
        sample = client.copy_object.call_args_list[0].kwargs
        self.assertEqual(sample['Bucket'], 'gamesbazaarpublic')
        self.assertEqual(sample['CopySource'], {'Bucket': 'gamesbazaar-media', 'Key': sample['Key']})
        self.assertEqual(sample['CacheControl'], PUBLIC_MEDIA_OBJECT_CACHE_CONTROL)
        self.assertEqual(sample['ContentType'], 'image/webp')
        self.assertEqual(sample['MetadataDirective'], 'REPLACE')
        self.assertIn('Copied 2 object(s); 1 already public; 1 on local disk; 1 missing', out)
        self.assertIn('r2/game_icons/lost.webp', err)

    def test_dry_run_copies_nothing(self):
        client, out, _ = self.run_command(
            '--dry-run',
            private_has={AVATAR, 'r2/game_icons/steam.webp', 'r2/game_icons/lost.webp', 'r2/game_icons/done.webp'},
        )

        client.copy_object.assert_not_called()
        self.assertIn('Would copy 4 object(s)', out)

    def test_refuses_to_run_without_the_public_bucket_settings(self):
        with override_settings(CLOUDFLARE_R2_PUBLIC_BUCKET_NAME=''):
            with self.assertRaises(CommandError):
                call_command('migrate_public_media', stdout=StringIO())
