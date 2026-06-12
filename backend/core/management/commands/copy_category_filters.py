from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import GameCategory, GameCategoryFilter


class Command(BaseCommand):
    help = (
        'Copy one game-category\'s filter assignments (including order, '
        'require_selection and visible-when conditions) to every other game '
        'that has the same category. Existing assignments for the same filter '
        'are updated to match the source; extra filters on targets are left '
        'alone and only reported.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--game', required=True,
                            help='Source game slug (e.g., steam)')
        parser.add_argument('--category', required=True,
                            help='Category slug (e.g., keys)')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change without saving anything.')

    def handle(self, *args, **options):
        try:
            source = GameCategory.objects.select_related('game', 'category').get(
                game__slug=options['game'],
                category__slug=options['category'],
            )
        except GameCategory.DoesNotExist:
            raise CommandError(
                f"No game-category found for game '{options['game']}' "
                f"and category '{options['category']}'."
            )

        template = list(
            source.assigned_filters
            .select_related('filter')
            .prefetch_related('visible_when_options')
        )
        if not template:
            raise CommandError(f'{source} has no filters assigned — nothing to copy.')

        self.stdout.write(f'Source: {source}')
        for gcf in template:
            conditions = [str(opt) for opt in gcf.visible_when_options.all()]
            self.stdout.write(
                f'  - {gcf.filter} | order {gcf.order} '
                f'| require_selection {gcf.require_selection} '
                f'| visible when: {" OR ".join(conditions) if conditions else "always"}'
            )

        targets = (
            GameCategory.objects.filter(category=source.category)
            .exclude(pk=source.pk)
            .select_related('game')
            .prefetch_related('assigned_filters__filter',
                              'assigned_filters__visible_when_options')
            .order_by('game__name')
        )

        created = updated = unchanged = 0
        extras = []

        with transaction.atomic():
            for target in targets:
                existing_by_filter = {
                    gcf.filter_id: gcf for gcf in target.assigned_filters.all()
                }
                template_filter_ids = {gcf.filter_id for gcf in template}

                for gcf in template:
                    wanted_option_ids = {
                        opt.pk for opt in gcf.visible_when_options.all()
                    }
                    current = existing_by_filter.get(gcf.filter_id)
                    if current is None:
                        new_gcf = GameCategoryFilter.objects.create(
                            game_category=target,
                            filter=gcf.filter,
                            order=gcf.order,
                            require_selection=gcf.require_selection,
                        )
                        new_gcf.visible_when_options.set(wanted_option_ids)
                        created += 1
                        continue

                    current_option_ids = {
                        opt.pk for opt in current.visible_when_options.all()
                    }
                    if (current.order == gcf.order
                            and current.require_selection == gcf.require_selection
                            and current_option_ids == wanted_option_ids):
                        unchanged += 1
                        continue

                    current.order = gcf.order
                    current.require_selection = gcf.require_selection
                    current.save(update_fields=['order', 'require_selection'])
                    current.visible_when_options.set(wanted_option_ids)
                    updated += 1

                for gcf in target.assigned_filters.all():
                    if gcf.filter_id not in template_filter_ids:
                        extras.append(f'{target.game.name}: {gcf.filter}')

            if options['dry_run']:
                transaction.set_rollback(True)

        prefix = '[DRY RUN] Would have: ' if options['dry_run'] else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}{targets.count()} target game-categories — '
            f'{created} assignments created, {updated} updated to match, '
            f'{unchanged} already matching.'
        ))
        if extras:
            self.stdout.write(self.style.WARNING(
                f'{len(extras)} extra filter assignments not in the source were '
                'left untouched:'
            ))
            for line in extras[:30]:
                self.stdout.write(f'  - {line}')
            if len(extras) > 30:
                self.stdout.write(f'  ... and {len(extras) - 30} more')
