import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Category, Game, GameCategory


def write_copy_file(directory, pages):
    path = Path(directory) / 'seo_copy.json'
    path.write_text(json.dumps({'pages': pages}), encoding='utf-8')
    return str(path)


class SeedSeoTextTests(TestCase):
    """seed_seo_text command + the SEO fields riding the category endpoint."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.game = Game.objects.create(name='PUBG Mobile', slug='pubg-mobile')
        self.category = Category.objects.create(name='UC', slug='uc')
        self.game_category = GameCategory.objects.create(
            game=self.game, category=self.category,
        )
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def run_command(self, pages, **options):
        out = StringIO()
        call_command(
            'seed_seo_text',
            file=write_copy_file(self.tmpdir.name, pages),
            stdout=out,
            **options,
        )
        return out.getvalue()

    def test_seeds_fields_and_api_returns_them(self):
        self.run_command([{
            'game': 'pubg-mobile',
            'category': 'uc',
            'seo_title': 'Buy PUBG Mobile UC in Pakistan',
            'seo_description': 'UC top-ups with JazzCash at PKR prices.',
            'seo_body': '## Heading\n\nParagraph one.',
        }])

        self.game_category.refresh_from_db()
        self.assertEqual(self.game_category.seo_title, 'Buy PUBG Mobile UC in Pakistan')

        response = self.client.get('/api/games/pubg-mobile/uc/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['seo_title'], 'Buy PUBG Mobile UC in Pakistan')
        self.assertEqual(response.data['seo_description'],
                         'UC top-ups with JazzCash at PKR prices.')
        self.assertEqual(response.data['seo_body'], '## Heading\n\nParagraph one.')

    def test_rerun_is_idempotent_and_partial_entries_keep_other_fields(self):
        pages = [{
            'game': 'pubg-mobile',
            'category': 'uc',
            'seo_title': 'Title v1',
            'seo_body': 'Body v1',
        }]
        first = self.run_command(pages)
        self.assertIn('1 updated', first)

        second = self.run_command(pages)
        self.assertIn('0 updated, 1 unchanged', second)

        # An entry that only carries a title must not blank the stored body.
        self.run_command([{
            'game': 'pubg-mobile',
            'category': 'uc',
            'seo_title': 'Title v2',
        }])
        self.game_category.refresh_from_db()
        self.assertEqual(self.game_category.seo_title, 'Title v2')
        self.assertEqual(self.game_category.seo_body, 'Body v1')

    def test_resolves_display_slug_renames(self):
        # Free Fire renames "Top Ups" to "Diamonds"; the URL slug is the
        # display slug, and that's what the copy file uses.
        game = Game.objects.create(name='Free Fire', slug='free-fire')
        category = Category.objects.create(name='Top Ups', slug='top-ups')
        renamed = GameCategory.objects.create(
            game=game, category=category, display_name='Diamonds',
        )

        self.run_command([{
            'game': 'free-fire',
            'category': 'diamonds',
            'seo_title': 'Free Fire Diamonds in Pakistan',
        }])
        renamed.refresh_from_db()
        self.assertEqual(renamed.seo_title, 'Free Fire Diamonds in Pakistan')

    def test_unknown_page_is_reported_but_does_not_fail(self):
        output = self.run_command([
            {'game': 'pubg-mobile', 'category': 'uc', 'seo_title': 'Real page'},
            {'game': 'no-such-game', 'category': 'uc', 'seo_title': 'Ghost page'},
        ])
        self.assertIn('1 page(s) not found', output)
        self.assertIn('no-such-game/uc', output)
        self.game_category.refresh_from_db()
        self.assertEqual(self.game_category.seo_title, 'Real page')

    def test_overlong_field_fails_before_writing_anything(self):
        with self.assertRaises(CommandError):
            self.run_command([{
                'game': 'pubg-mobile',
                'category': 'uc',
                'seo_title': 'x' * 500,
            }])
        self.game_category.refresh_from_db()
        self.assertEqual(self.game_category.seo_title, '')

    def test_dry_run_writes_nothing(self):
        output = self.run_command(
            [{'game': 'pubg-mobile', 'category': 'uc', 'seo_title': 'Dry title'}],
            dry_run=True,
        )
        self.assertIn('would update', output)
        self.game_category.refresh_from_db()
        self.assertEqual(self.game_category.seo_title, '')
