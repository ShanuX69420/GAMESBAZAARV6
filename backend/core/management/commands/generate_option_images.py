"""Compose and store the product picture for tile-based options.

    python manage.py generate_option_images --game playstation
    python manage.py generate_option_images --all --missing      # daily hook
    python manage.py generate_option_images --game playstation --force
    python manage.py generate_option_images --game playstation --out /tmp/cards --dry-run

Only brands listed in core/data/option_image_brands.json are handled; every
other game is refused with the configured list. Options whose name is not
amount-shaped (subscriptions, bundles) are reported and left alone. By
default only options with at least one active listing get a picture (the
tiles buyers see) and options that already have one are skipped; `--force`
redraws them.
"""
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q

from core.models import CategoryOption
from core.option_images import (
    image_filename, load_brands, load_regions, parse_option_name, render_option_image,
)
from core.storage_backends import CLOUDFLARE_R2_NAME_PREFIX


class Command(BaseCommand):
    help = 'Generate the 3:2 product picture (CategoryOption.image) for tile-based options.'

    def add_arguments(self, parser):
        parser.add_argument('--game', action='append', default=[],
                            help='Game slug (repeatable). Must be in option_image_brands.json.')
        parser.add_argument('--all', action='store_true',
                            help='Every game listed in option_image_brands.json.')
        parser.add_argument('--category', default='',
                            help='Only this category slug (default: every category with options).')
        group = parser.add_mutually_exclusive_group()
        group.add_argument('--missing', action='store_true', default=True,
                           help='Only options without a picture (default).')
        group.add_argument('--force', action='store_true',
                           help='Redraw every option, replacing existing pictures.')
        parser.add_argument('--include-empty', action='store_true',
                            help='Also options with no active listing.')
        parser.add_argument('--limit', type=int, default=0, help='Stop after N pictures.')
        parser.add_argument('--out', default='',
                            help='Also write each WebP to this directory (for a look before trusting it).')
        parser.add_argument('--dry-run', action='store_true',
                            help='Render (and --out) but do not store anything on the options.')

    @staticmethod
    def store(opt, filename, data):
        """Attach the picture to the option. The filename carries a content
        hash, so an identical object already in the bucket (rendered on
        another machine, or an unchanged design under --force) is reused
        instead of uploaded again under a suffixed name."""
        field = CategoryOption._meta.get_field('image')
        stored_name = f'{CLOUDFLARE_R2_NAME_PREFIX}{field.upload_to}{filename}'
        if opt.image and opt.image.name != stored_name:
            # R2 never overwrites (file_overwrite off): drop the old object
            # so the bucket does not collect orphans.
            opt.image.delete(save=False)
        if field.storage.exists(stored_name):
            opt.image.name = stored_name
            opt.save(update_fields=['image'])
            return
        opt.image.save(filename, ContentFile(data), save=True)

    def handle(self, *args, **options):
        brands = load_brands()
        regions = load_regions()
        slugs = list(brands) if options['all'] else options['game']
        if not slugs:
            raise CommandError('Pass --game <slug> (repeatable) or --all.')
        unknown = [s for s in slugs if s not in brands]
        if unknown:
            raise CommandError(
                f"No brand config for: {', '.join(unknown)}. "
                f"Configured: {', '.join(sorted(brands))} (core/data/option_image_brands.json)."
            )

        out_dir = Path(options['out']) if options['out'] else None
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)

        qs = (
            CategoryOption.objects
            .filter(game_category__game__slug__in=slugs)
            .select_related('game_category__game', 'game_category__category')
            .annotate(active_count=Count('listings', filter=Q(listings__status='active')))
            .order_by('game_category__game__slug', 'game_category__category__slug', 'order', 'name')
        )
        if options['category']:
            qs = qs.filter(game_category__category__slug=options['category'])
        if not options['include_empty']:
            qs = qs.filter(active_count__gt=0)

        made = skipped = 0
        unparsed, unknown_regions = [], set()
        for opt in qs.iterator():
            if opt.image and not options['force']:
                skipped += 1
                continue
            parsed = parse_option_name(opt.name)
            if not parsed:
                unparsed.append(
                    f'{opt.game_category.game.slug}/{opt.game_category.category.slug}: {opt.name}')
                continue
            region = regions.get(parsed['region']) if parsed['region'] else None
            if parsed['region'] and region is None:
                unknown_regions.add(parsed['region'])

            brand = brands[opt.game_category.game.slug]
            data = render_option_image(brand, parsed, region)
            filename = image_filename(opt.game_category.game.slug, parsed,
                                      (region or {}).get('name'), data)
            if out_dir:
                (out_dir / filename).write_bytes(data)
            if not options['dry_run']:
                self.store(opt, filename, data)
            made += 1
            self.stdout.write(f'{opt.name:<28} -> {filename} ({len(data) // 1024} KB)')
            if options['limit'] and made >= options['limit']:
                break

        verb = 'rendered' if options['dry_run'] else 'stored'
        self.stdout.write(self.style.SUCCESS(f'{made} picture(s) {verb}, {skipped} already had one.'))
        if unknown_regions:
            self.stdout.write(self.style.WARNING(
                'Regions without a flag (text-only badge); add them to '
                f"option_image_regions.json: {', '.join(sorted(unknown_regions))}"))
        if unparsed:
            self.stdout.write(self.style.WARNING(
                f'{len(unparsed)} option name(s) not amount-shaped, left without a picture:'))
            for line in unparsed[:40]:
                self.stdout.write(f'  {line}')
        if made and not options['dry_run']:
            self.stdout.write('Browse responses are cached briefly; the pictures show once the '
                              'cached page entry expires.')
