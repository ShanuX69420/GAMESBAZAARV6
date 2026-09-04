"""Product pictures for tile-based options: the composer, the
generate_option_images command and the image_url the browse API exposes."""
import io
import tempfile
from decimal import Decimal
from pathlib import Path

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from PIL import Image
from rest_framework.test import APIClient

from .models import Category, CategoryOption, Game, GameCategory, Listing
from .option_images import (
    image_filename, load_brands, load_regions, parse_option_name, render_option_image,
)
from .tests import assert_storage_name_under, local_media_storage_settings


class OptionNameParsingTests(SimpleTestCase):
    def test_amount_currency_region(self):
        self.assertEqual(parse_option_name('50 USD (USA)'),
                         {'amount': '50', 'currency': 'USD', 'region': 'USA'})
        self.assertEqual(parse_option_name('1,000 INR (India)'),
                         {'amount': '1000', 'currency': 'INR', 'region': 'India'})
        self.assertEqual(parse_option_name('10 EUR'),
                         {'amount': '10', 'currency': 'EUR', 'region': ''})
        self.assertEqual(parse_option_name('60 UC'),
                         {'amount': '60', 'currency': 'UC', 'region': ''})

    def test_non_amount_names_are_rejected(self):
        for name in ('Plus — 1 Month', 'Bundle', '', None):
            self.assertIsNone(parse_option_name(name), name)

    def test_every_configured_region_has_its_flag_file(self):
        flag_dir = Path(__file__).resolve().parent / 'data' / 'flags'
        for label, region in load_regions().items():
            if region.get('iso'):
                self.assertTrue((flag_dir / f"{region['iso']}.png").exists(),
                                f'{label}: missing flags/{region["iso"]}.png')

    def test_every_brand_has_its_logo_file(self):
        logo_dir = Path(__file__).resolve().parent / 'data' / 'brand_logos'
        for slug, brand in load_brands().items():
            self.assertTrue((logo_dir / brand['logo']).exists(), f'{slug}: missing logo')


class OptionImageRenderTests(SimpleTestCase):
    def render(self, name):
        parsed = parse_option_name(name)
        region = load_regions().get(parsed['region']) if parsed['region'] else None
        return render_option_image(load_brands()['playstation'], parsed, region)

    def test_card_is_a_small_3_by_2_webp(self):
        data = self.render('50 USD (USA)')
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.format, 'WEBP')
        self.assertEqual(image.size, (900, 600))
        self.assertLess(len(data), 40 * 1024)

    def test_long_amounts_and_flagless_regions_still_render(self):
        for name in ('1500000 IDR (Indonesia)', '10 EUR', '5 USD (Atlantis)'):
            image = Image.open(io.BytesIO(self.render(name)))
            self.assertEqual(image.size, (900, 600), name)

    def test_filename_is_descriptive_and_content_hashed(self):
        parsed = parse_option_name('50 USD (USA)')
        name = image_filename('playstation', parsed, 'USA', b'one')
        self.assertRegex(name, r'^playstation-usa-50-usd-[0-9a-f]{8}\.webp$')
        self.assertNotEqual(name, image_filename('playstation', parsed, 'USA', b'two'))


@local_media_storage_settings(tempfile.mkdtemp())
class GenerateOptionImagesCommandTests(TestCase):
    def setUp(self):
        cache.clear()
        self.seller = User.objects.create_user(username='store', password='password123')
        self.seller.profile.seller_status = 'approved'
        self.seller.profile.save(update_fields=['seller_status'])
        self.game = Game.objects.create(name='PlayStation', slug='playstation')
        self.category = Category.objects.create(name='Gift Cards', slug='gift-cards')
        self.game_category = GameCategory.objects.create(
            game=self.game, category=self.category, listing_mode='offer')
        self.stocked = CategoryOption.objects.create(
            game_category=self.game_category, name='50 USD (USA)', order=0)
        self.empty = CategoryOption.objects.create(
            game_category=self.game_category, name='10 EUR (Austria)', order=1)
        self.odd = CategoryOption.objects.create(
            game_category=self.game_category, name='Plus — 1 Month', order=2)
        for option in (self.stocked, self.odd):
            Listing.objects.create(
                seller=self.seller, game_category=self.game_category, option=option,
                title=option.name, price=Decimal('1000.00'), status='active')

    def run_command(self, *args):
        out = io.StringIO()
        call_command('generate_option_images', *args, stdout=out)
        return out.getvalue()

    def reload(self):
        self.stocked.refresh_from_db()
        self.empty.refresh_from_db()
        self.odd.refresh_from_db()

    def test_pictures_only_for_stocked_amount_shaped_options(self):
        output = self.run_command('--game', 'playstation')
        self.reload()

        self.assertTrue(self.stocked.image)
        assert_storage_name_under(self, self.stocked.image.name, 'option_images/')
        self.assertIn('playstation-usa-50-usd-', self.stocked.image.name)
        self.assertFalse(self.empty.image)
        self.assertFalse(self.odd.image)
        self.assertIn('1 picture(s) stored', output)
        self.assertIn('Plus — 1 Month', output)

    def test_rerun_skips_existing_and_include_empty_fills_the_rest(self):
        self.run_command('--game', 'playstation')
        self.reload()
        first_name = self.stocked.image.name

        output = self.run_command('--game', 'playstation')
        self.assertIn('0 picture(s) stored, 1 already had one', output)

        self.run_command('--game', 'playstation', '--include-empty')
        self.reload()
        self.assertEqual(self.stocked.image.name, first_name)
        self.assertTrue(self.empty.image)
        self.assertIn('playstation-austria-10-eur-', self.empty.image.name)

    def test_force_redraws_and_leaves_no_orphan_file(self):
        self.run_command('--game', 'playstation')
        self.reload()
        first_name = self.stocked.image.name
        storage = self.stocked.image.storage

        output = self.run_command('--game', 'playstation', '--force')
        self.reload()

        self.assertIn('1 picture(s) stored', output)
        self.assertTrue(self.stocked.image)
        # Unchanged design → same content hash → the same name is reused;
        # the file exists exactly once either way.
        self.assertTrue(storage.exists(self.stocked.image.name))
        if self.stocked.image.name != first_name:
            self.assertFalse(storage.exists(first_name))

    def test_dry_run_and_out_dir_store_nothing(self):
        out_dir = tempfile.mkdtemp()
        self.run_command('--game', 'playstation', '--dry-run', '--out', out_dir)
        self.reload()

        self.assertFalse(self.stocked.image)
        written = list(Path(out_dir).glob('playstation-usa-50-usd-*.webp'))
        self.assertEqual(len(written), 1)

    def test_unconfigured_brand_is_refused(self):
        Game.objects.create(name='Mystery', slug='mystery')
        with self.assertRaises(CommandError) as ctx:
            call_command('generate_option_images', '--game', 'mystery')
        self.assertIn('playstation', str(ctx.exception))

    def test_browse_api_exposes_image_url(self):
        client = APIClient()
        before = client.get('/api/games/playstation/gift-cards/')
        self.assertEqual(before.status_code, 200)
        by_name = {opt['name']: opt for opt in before.data['options']}
        self.assertIsNone(by_name['50 USD (USA)']['image_url'])

        self.run_command('--game', 'playstation')
        cache.clear()

        after = client.get('/api/games/playstation/gift-cards/')
        by_name = {opt['name']: opt for opt in after.data['options']}
        self.assertIn('playstation-usa-50-usd-', by_name['50 USD (USA)']['image_url'])
        self.assertTrue(by_name['50 USD (USA)']['image_url'].endswith('.webp'))
        self.assertIsNone(by_name['Plus — 1 Month']['image_url'])
