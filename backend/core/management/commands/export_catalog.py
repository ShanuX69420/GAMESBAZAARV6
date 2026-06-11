import json

from django.core.management.base import BaseCommand

from core.models import GameCategory


class Command(BaseCommand):
    help = (
        'Export the live game/category/filter catalog as JSON. Used to build '
        'the bulk-listing spreadsheet template and to validate filled sheets '
        'before import (see import_listings).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--output', default='-',
            help='File path to write to, or "-" for stdout (default).',
        )

    def handle(self, *args, **options):
        game_categories = (
            GameCategory.objects.filter(game__is_active=True)
            .select_related('game', 'category')
            .prefetch_related('options', 'assigned_filters__filter__options')
            .order_by('game__name', 'order')
        )

        catalog = []
        for gc in game_categories:
            catalog.append({
                'game': gc.game.name,
                'game_slug': gc.game.slug,
                'category': gc.category.name,
                'category_slug': gc.category.slug,
                'listing_mode': gc.listing_mode,
                'allow_auto_delivery': gc.allow_auto_delivery,
                'options': [
                    {'id': opt.id, 'name': opt.name}
                    for opt in gc.options.all()
                ],
                'filters': [
                    {
                        'id': gcf.filter_id,
                        'name': gcf.filter.name,
                        'options': [
                            {'label': fo.label, 'value': fo.value}
                            for fo in gcf.filter.options.all()
                        ],
                    }
                    for gcf in gc.assigned_filters.all()
                ],
            })

        payload = json.dumps(catalog, indent=2, ensure_ascii=False)
        if options['output'] == '-':
            self.stdout.write(payload)
        else:
            with open(options['output'], 'w', encoding='utf-8') as fh:
                fh.write(payload)
            self.stdout.write(self.style.SUCCESS(
                f'Wrote {len(catalog)} game/category entries to {options["output"]}'
            ))
