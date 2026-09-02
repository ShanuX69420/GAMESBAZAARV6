import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Game, GameCategory

DEFAULT_FILE = Path(__file__).resolve().parents[2] / 'data' / 'seo_copy.json'
SEO_FIELDS = ('seo_title', 'seo_description', 'seo_body')

# Inline links in seo_body: [text](/site/relative/path). The renderer
# (frontend/lib/seoText.js) only turns site-relative paths into links and
# leaves anything else as literal text, so a full URL here would show up as
# raw brackets on the page — reject it before it is written.
LINK_PATTERN = re.compile(r'\[([^\[\]\n]+)\]\(([^)\s]*)\)')
GAME_CATEGORY_PATH = re.compile(r'^/games/([^/?#]+)/([^/?#]+)/?(?:[?#].*)?$')
GAME_PATH = re.compile(r'^/games/([^/?#]+)/?(?:[?#].*)?$')


def malformed_links(body):
    """hrefs in *body* that are not site-relative paths."""
    return [
        href for _text, href in LINK_PATTERN.findall(body)
        if not href.startswith('/') or href.startswith('//')
    ]


def dead_link_targets(body):
    """/games/... links in *body* whose page does not exist on this site.
    Other site paths (/keys, /gift-cards, ...) are static routes and are
    taken on trust."""
    dead = []
    for _text, href in LINK_PATTERN.findall(body):
        page = GAME_CATEGORY_PATH.match(href)
        if page:
            if GameCategory.resolve_for_slug(page.group(1), page.group(2)) is None:
                dead.append(href)
            continue
        game = GAME_PATH.match(href)
        if game and not Game.objects.filter(slug=game.group(1), is_active=True).exists():
            dead.append(href)
    return dead


class Command(BaseCommand):
    help = (
        'Apply per-page SEO copy (title, meta description, visible body text) to '
        'game+category pages from core/data/seo_copy.json. Re-runnable: only rows '
        'whose content differs are written, and pages absent from the file are '
        'never touched. Update the JSON in the repo, deploy, then run this — '
        'no ad-hoc python over SSH. seo_body may link other pages with '
        '[text](/games/<game>/<category>); a page whose links point at a missing '
        'page is skipped so a dead link never goes live.'
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

        self.max_lengths = {
            field: GameCategory._meta.get_field(field).max_length
            for field in SEO_FIELDS
        }
        self.dry_run = options['dry_run']
        self.missing = []
        self.dead_links = []

        # One transaction, so a bad entry halfway through the file cannot
        # leave the site half-updated.
        with transaction.atomic():
            updated, unchanged = self.apply_pages(pages)

        prefix = '[DRY RUN] ' if self.dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}{updated} updated, {unchanged} unchanged, '
            f'{len(self.missing)} page(s) not found, '
            f'{len(self.dead_links)} page(s) skipped for dead links.'
        ))
        if self.missing:
            self.stdout.write(self.style.WARNING(
                'Not found on this site (check the slugs, nothing was written):'
            ))
            for entry in self.missing:
                self.stdout.write(self.style.WARNING(f'  - {entry}'))
        if self.dead_links:
            self.stdout.write(self.style.WARNING(
                'Links to pages that do not exist on this site (the page was '
                'skipped, fix the link and re-run):'
            ))
            for entry, href in self.dead_links:
                self.stdout.write(self.style.WARNING(f'  - {entry}: {href}'))

    def apply_pages(self, pages):
        updated = unchanged = 0
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
                limit = self.max_lengths[field]
                if limit and len(value) > limit:
                    raise CommandError(
                        f'{game_slug}/{category_slug}: {field} is {len(value)} chars '
                        f'(max {limit}).'
                    )
                if field != 'seo_body' and LINK_PATTERN.search(value):
                    raise CommandError(
                        f'{game_slug}/{category_slug}: {field} contains a [text](/path) '
                        'link — links are only rendered in seo_body.'
                    )

            body = str(page.get('seo_body') or '')
            bad_hrefs = malformed_links(body)
            if bad_hrefs:
                raise CommandError(
                    f'{game_slug}/{category_slug}: links must be site-relative paths '
                    f'such as /games/pubg-mobile/uc, got: {", ".join(bad_hrefs)}'
                )

            game_category = GameCategory.resolve_for_slug(game_slug, category_slug)
            if game_category is None:
                self.missing.append(f'{game_slug}/{category_slug}')
                continue

            # Only checked once the page itself resolves: on the local demo DB
            # most pages are "not found" anyway, and a dead link there is noise.
            dead = dead_link_targets(body) if 'seo_body' in page else []
            if dead:
                self.dead_links.extend(
                    (f'{game_slug}/{category_slug}', href) for href in dead
                )
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

            if not self.dry_run:
                game_category.save(update_fields=changed_fields)
            updated += 1
            verb = 'would update' if self.dry_run else 'updated'
            self.stdout.write(
                f'  {verb} {game_slug}/{category_slug}: {", ".join(changed_fields)}'
            )

        return updated, unchanged
