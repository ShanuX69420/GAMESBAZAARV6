"""The post-deploy cache warmer: it asks for every page that has stock, once,
against the local Next server, and says loudly when it could not."""

from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

import requests
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from .management.commands import warm_page_cache
from .models import Category, Game, GameCategory, Listing


def page(status=200, cache='MISS', body=b'<html></html>'):
    response = Mock()
    response.status_code = status
    response.headers = {'x-nextjs-cache': cache} if cache else {}
    response.content = body
    return response


@override_settings(PUBLIC_SITE_URL='https://www.example.pk')
class WarmPageCacheTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(username='warmseller', password='password123')
        self.category = Category.objects.create(name='Warm Keys', slug='keys')
        self.game = Game.objects.create(name='Warm Game', slug='warm-game')
        self.gc = GameCategory.objects.create(game=self.game, category=self.category)
        self.make_listing(self.gc)

    def make_listing(self, game_category, status='active'):
        return Listing.objects.create(
            seller=self.seller,
            game_category=game_category,
            title='Warm item',
            price=Decimal('100.00'),
            status=status,
        )

    def run_command(self, session, **options):
        out = StringIO()
        with patch.object(warm_page_cache.requests, 'Session', return_value=session):
            call_command('warm_page_cache', stdout=out, stderr=out, **options)
        return out.getvalue()

    # --- which pages get warmed ---------------------------------------------

    def test_paths_are_site_relative_not_absolute_urls(self):
        self.assertEqual(warm_page_cache.warmable_paths(), ['/games/warm-game/keys'])

    def test_page_without_stock_is_not_warmed(self):
        empty_game = Game.objects.create(name='Empty Game', slug='empty-game')
        GameCategory.objects.create(game=empty_game, category=self.category)
        self.assertEqual(warm_page_cache.warmable_paths(), ['/games/warm-game/keys'])

    def test_inactive_game_is_not_warmed(self):
        dark_game = Game.objects.create(name='Dark Game', slug='dark-game', is_active=False)
        dark_gc = GameCategory.objects.create(game=dark_game, category=self.category)
        self.make_listing(dark_gc)
        self.assertEqual(warm_page_cache.warmable_paths(), ['/games/warm-game/keys'])

    # --- the requests themselves --------------------------------------------

    def test_requests_the_local_next_server_with_the_public_host(self):
        session = Mock()
        session.get.return_value = page()
        self.run_command(session)

        session.get.assert_called_once()
        url, kwargs = session.get.call_args[0][0], session.get.call_args[1]
        self.assertEqual(url, 'http://127.0.0.1:3000/games/warm-game/keys')
        self.assertEqual(kwargs['headers']['Host'], 'www.example.pk')
        # A redirect would mean the URL list disagrees with the routes.
        self.assertFalse(kwargs['allow_redirects'])

    def test_reports_freshly_rendered_and_already_warm_pages(self):
        other = Game.objects.create(name='Other Game', slug='other-game')
        self.make_listing(GameCategory.objects.create(game=other, category=self.category))
        session = Mock()
        session.get.side_effect = [page(cache='MISS'), page(cache='HIT')]

        output = self.run_command(session, concurrency=1)

        self.assertIn('Warmed 2/2', output)
        self.assertIn('rendered now (MISS):   1', output)
        self.assertIn('already warm (HIT):    1', output)

    def test_uncached_200_is_flagged_as_a_still_dynamic_route(self):
        session = Mock()
        session.get.return_value = page(cache=None)
        output = self.run_command(session)
        self.assertIn('served but NOT cached', output)

    def test_failures_are_listed_but_do_not_stop_the_run(self):
        other = Game.objects.create(name='Other Game', slug='other-game')
        self.make_listing(GameCategory.objects.create(game=other, category=self.category))
        session = Mock()
        session.get.side_effect = [page(), requests.ConnectionError('boom')]

        output = self.run_command(session, concurrency=1)

        self.assertIn('Warmed 1/2', output)
        self.assertIn('failed:                1', output)
        self.assertIn('boom', output)

    def test_cached_not_found_page_counts_as_a_failure_not_a_warm_page(self):
        # Next serves its own not-found page from the cache, so a 404 arrives
        # with `x-nextjs-cache: HIT` — that is a broken URL, not a warm page.
        session = Mock()
        session.get.return_value = page(status=404, cache='HIT')
        with self.assertRaises(CommandError):
            self.run_command(session)

    def test_every_request_failing_is_a_command_error(self):
        session = Mock()
        session.get.side_effect = requests.ConnectionError('refused')
        with self.assertRaises(CommandError):
            self.run_command(session)

    def test_dry_run_requests_nothing(self):
        session = Mock()
        output = self.run_command(session, dry_run=True)
        session.get.assert_not_called()
        self.assertIn('/games/warm-game/keys', output)

    def test_explicit_paths_skip_the_stock_lookup(self):
        session = Mock()
        session.get.return_value = page()
        self.run_command(session, paths=['/games/anything/keys'])
        self.assertEqual(session.get.call_args[0][0],
                         'http://127.0.0.1:3000/games/anything/keys')

    def test_limit_caps_the_run(self):
        other = Game.objects.create(name='Other Game', slug='other-game')
        self.make_listing(GameCategory.objects.create(game=other, category=self.category))
        session = Mock()
        session.get.return_value = page()
        self.run_command(session, limit=1)
        self.assertEqual(session.get.call_count, 1)
