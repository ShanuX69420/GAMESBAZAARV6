import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.models import GameCategory

DEFAULT_FILE = Path(__file__).resolve().parents[2] / 'data' / 'seo_copy.json'
SEO_FIELDS = ('seo_title', 'seo_description', 'seo_body')


class Command(BaseCommand):
    help = (
        'Apply per-page SEO copy (title, meta description, visible body text) to '
        'game+category pages from core/data/seo_copy.json. Re-runnable: only rows '
        'whose content differs are written, and pages absent from the file are '
        'never touched. Update the JSON in the repo, deploy, then run this — '
        'no ad-hoc python over SSH.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--file', default=str(DEFAULT_FILE),
                            help=f'Path to the SEO copy JSON (default: {DEFAULT_FILE})')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change without saving anything.')

    def handle(self, *args, **options):
        path = Path(options['file'])
        if not path.exists():
            raise CommandError(f'File not found: {path}')
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            raise CommandError(f'{path.name} is not valid JSON: {exc}')

        pages = data.get('pages')
        if not isinstance(pages, list) or not pages:
            raise CommandError('JSON must contain a non-empty top-level "pages" list.')

        max_lengths = {
            field: GameCategory._meta.get_field(field).max_length
            for field in SEO_FIELDS
        }

        dry_run = options['dry_run']
        updated = unchanged = 0
        missing = []
        seen = set()

        for index, page in enumerate(pages):
            game_slug = str(page.get('game') or '').strip()
            category_slug = str(page.get('category') or '').strip()
            if not game_slug or not category_slug:
                raise CommandError(f'pages[{index}] is missing "game" or "category".')

            key = (game_slug, category_slug)
            if key in seen:
                raise CommandError(f'Duplicate entry for {game_slug}/{category_slug}.')
            seen.add(key)

            for field in SEO_FIELDS:
                value = str(page.get(field) or '')
                limit = max_lengths[field]
                if limit and len(value) > limit:
                    raise CommandError(
                        f'{game_slug}/{category_slug}: {field} is {len(value)} chars '
                        f'(max {limit}).'
                    )

            game_category = GameCategory.resolve_for_slug(game_slug, category_slug)
            if game_category is None:
                missing.append(f'{game_slug}/{category_slug}')
                continue

            # Only keys present in the JSON are applied, so a page entry can set
            # e.g. just the title without blanking an existing body.
            changed_fields = []
            for field in SEO_FIELDS:
                if field not in page:
                    continue
                new_value = str(page[field] or '').strip()
                if getattr(game_category, field) != new_value:
                    setattr(game_category, field, new_value)
                    changed_fields.append(field)

            if not changed_fields:
                unchanged += 1
                continue

            if not dry_run:
                game_category.save(update_fields=changed_fields)
            updated += 1
            verb = 'would update' if dry_run else 'updated'
            self.stdout.write(
                f'  {verb} {game_slug}/{category_slug}: {", ".join(changed_fields)}'
            )

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}{updated} updated, {unchanged} unchanged, '
            f'{len(missing)} page(s) not found.'
        ))
        if missing:
            self.stdout.write(self.style.WARNING(
                'Not found on this site (check the slugs, nothing was written):'
            ))
            for entry in missing:
                self.stdout.write(self.style.WARNING(f'  - {entry}'))
