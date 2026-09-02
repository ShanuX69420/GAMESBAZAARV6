"""IndexNow: changed listing + game-category pages are pushed to Bing, the
change cursor only advances once a batch is accepted, and nothing leaves the
box without INDEXNOW_KEY."""

from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

import requests
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from . import indexnow
from .models import Category, Game, GameCategory, Listing, PlatformSetting
from .services import set_platform_setting


def accepted(status=200):
    response = Mock()
    response.status_code = status
    response.text = ''
    return response


def refused(status=422):
    response = Mock()
    response.status_code = status
    response.text = 'Unprocessable Entity'
    return response


@override_settings(INDEXNOW_KEY='testkey123', PUBLIC_SITE_URL='https://www.example.pk')
class IndexNowFixture(TestCase):
    def setUp(self):
        cache.clear()
        self.seller = User.objects.create_user(username='inseller', password='password123')
        self.game = Game.objects.create(name='IN Game', slug='in-game')
        self.category = Category.objects.create(name='IN Top-ups', slug='top-ups')
        self.gc = GameCategory.objects.create(game=self.game, category=self.category)

    def make_listing(self, game_category=None, status='active'):
        return Listing.objects.create(
            seller=self.seller,
            game_category=game_category or self.gc,
            title='IN item',
            price=Decimal('100.00'),
            status=status,
        )

    @staticmethod
    def age(listing, hours):
        # update() skips auto_now — exactly how the daily syncs behave.
        Listing.objects.filter(pk=listing.pk).update(
            updated_at=timezone.now() - timedelta(hours=hours))

    def run_command(self, *args):
        out = StringIO()
        call_command('indexnow_ping', *args, stdout=out)
        return out.getvalue()

    @staticmethod
    def cursor():
        return PlatformSetting.objects.filter(key=indexnow.LAST_PING_SETTING_KEY).first()


class IndexNowPingCommandTests(IndexNowFixture):
    @override_settings(INDEXNOW_KEY='')
    def test_off_without_key(self):
        self.make_listing()
        with patch('core.indexnow.requests.post') as post:
            output = self.run_command()
        post.assert_not_called()
        self.assertIn('INDEXNOW_KEY is not set', output)
        self.assertIsNone(self.cursor())

    def test_first_run_submits_pages_changed_in_the_last_day(self):
        fresh = self.make_listing()
        stale = self.make_listing()
        self.age(stale, hours=30)

        with patch('core.indexnow.requests.post', return_value=accepted()) as post:
            output = self.run_command()

        post.assert_called_once()
        kwargs = post.call_args.kwargs
        payload = kwargs['json']
        self.assertEqual(payload['host'], 'www.example.pk')
        self.assertEqual(payload['key'], 'testkey123')
        self.assertEqual(payload['keyLocation'], 'https://www.example.pk/testkey123.txt')
        self.assertEqual(payload['urlList'], [
            'https://www.example.pk/games/in-game/top-ups',
            f'https://www.example.pk/listing/{fresh.pk}',
        ])
        self.assertEqual(kwargs['headers']['User-Agent'], indexnow.USER_AGENT)
        self.assertIn('Submitted 2 URL', output)
        self.assertIsNotNone(self.cursor())

    def test_later_runs_only_send_changes_since_the_last_ping(self):
        old = self.make_listing()
        self.age(old, hours=2)
        set_platform_setting(indexnow.LAST_PING_SETTING_KEY,
                             (timezone.now() - timedelta(hours=1)).isoformat())
        new = self.make_listing()

        with patch('core.indexnow.requests.post', return_value=accepted(202)) as post:
            self.run_command()

        self.assertEqual(post.call_args.kwargs['json']['urlList'], [
            'https://www.example.pk/games/in-game/top-ups',
            f'https://www.example.pk/listing/{new.pk}',
        ])

    def test_retired_listing_is_still_reported_so_engines_recheck_it(self):
        listing = self.make_listing()
        listing.status = 'inactive'
        listing.save(update_fields=['status', 'updated_at'])

        with patch('core.indexnow.requests.post', return_value=accepted()) as post:
            self.run_command()

        self.assertIn(f'https://www.example.pk/listing/{listing.pk}',
                      post.call_args.kwargs['json']['urlList'])

    def test_hidden_game_changes_send_nothing_but_still_advance_cursor(self):
        hidden = Game.objects.create(name='Hidden Game', slug='hidden-game', is_active=False)
        hidden_gc = GameCategory.objects.create(game=hidden, category=self.category)
        self.make_listing(hidden_gc)

        with patch('core.indexnow.requests.post') as post:
            output = self.run_command()

        post.assert_not_called()
        self.assertIn('Nothing changed', output)
        self.assertIsNotNone(self.cursor())

    def test_refused_batch_keeps_cursor_so_it_is_retried(self):
        self.make_listing()
        with patch('core.indexnow.requests.post', return_value=refused()):
            with self.assertRaises(CommandError):
                self.run_command()
        self.assertIsNone(self.cursor())

    def test_network_error_keeps_cursor(self):
        self.make_listing()
        with patch('core.indexnow.requests.post', side_effect=requests.ConnectionError('down')):
            with self.assertRaises(CommandError):
                self.run_command()
        self.assertIsNone(self.cursor())

    def test_dry_run_lists_urls_and_sends_nothing(self):
        listing = self.make_listing()
        with patch('core.indexnow.requests.post') as post:
            output = self.run_command('--dry-run')
        post.assert_not_called()
        self.assertIn('Dry run', output)
        self.assertIn(f'https://www.example.pk/listing/{listing.pk}', output)
        self.assertIsNone(self.cursor())

    def test_since_hours_widens_the_window(self):
        old = self.make_listing()
        self.age(old, hours=40)
        with patch('core.indexnow.requests.post', return_value=accepted()) as post:
            self.run_command('--since-hours', '48')
        self.assertIn(f'https://www.example.pk/listing/{old.pk}',
                      post.call_args.kwargs['json']['urlList'])

    def test_paths_are_submitted_as_canonical_site_urls(self):
        with patch('core.indexnow.requests.post', return_value=accepted()) as post:
            output = self.run_command(
                '--paths', '/games/in-game/top-ups/', 'keys', 'https://www.example.pk/about')
        self.assertEqual(post.call_args.kwargs['json']['urlList'], [
            'https://www.example.pk/games/in-game/top-ups',
            'https://www.example.pk/keys',
            'https://www.example.pk/about',
        ])
        self.assertIn('Submitted 3 URL', output)
        # Hand submissions do not touch the change cursor.
        self.assertIsNone(self.cursor())

    def test_all_category_pages_covers_only_indexable_pages(self):
        self.make_listing()  # in-game/top-ups has stock
        empty_category = Category.objects.create(name='IN Keys', slug='keys')
        empty_gc = GameCategory.objects.create(game=self.game, category=empty_category)
        self.make_listing(empty_gc, status='inactive')  # no live stock -> noindexed
        hidden = Game.objects.create(name='Hidden Game', slug='hidden-game', is_active=False)
        self.make_listing(GameCategory.objects.create(game=hidden, category=self.category))

        with patch('core.indexnow.requests.post', return_value=accepted()) as post:
            self.run_command('--all-category-pages')

        self.assertEqual(post.call_args.kwargs['json']['urlList'],
                         ['https://www.example.pk/games/in-game/top-ups'])


@override_settings(INDEXNOW_KEY='testkey123', PUBLIC_SITE_URL='https://www.example.pk')
class IndexNowSubmitTests(TestCase):
    def test_dedupes_drops_foreign_hosts_and_chunks_at_protocol_limit(self):
        urls = [f'https://www.example.pk/listing/{i}'
                for i in range(indexnow.MAX_URLS_PER_REQUEST + 1)]
        urls += urls[:5]  # duplicates
        urls.append('https://evil.example.com/listing/1')

        with patch('core.indexnow.requests.post', return_value=accepted()) as post:
            sent = indexnow.submit(urls)

        self.assertEqual(len(sent), indexnow.MAX_URLS_PER_REQUEST + 1)
        self.assertNotIn('https://evil.example.com/listing/1', sent)
        self.assertEqual(post.call_count, 2)
        first, second = (call.kwargs['json']['urlList'] for call in post.call_args_list)
        self.assertEqual(len(first), indexnow.MAX_URLS_PER_REQUEST)
        self.assertEqual(len(second), 1)

    def test_category_url_uses_display_slug_when_renamed(self):
        game = Game.objects.create(name='Slug Game', slug='slug-game')
        category = Category.objects.create(name='Top-ups', slug='top-ups')
        gc = GameCategory.objects.create(game=game, category=category)
        self.assertEqual(indexnow.category_page_url(gc),
                         'https://www.example.pk/games/slug-game/top-ups')
        gc.display_slug = 'subscriptions'
        self.assertEqual(indexnow.category_page_url(gc),
                         'https://www.example.pk/games/slug-game/subscriptions')
