import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import CategoryRegionPage, Game, GameCategory
from core.region_pages import region_filter_for, region_option_labels

DEFAULT_FILE = Path(__file__).resolve().parents[2] / 'data' / 'seo_copy.json'
SEO_FIELDS = ('seo_title', 'seo_description', 'seo_body')

# Inline links in seo_body: [text](/site/relative/path). The renderer
# (frontend/lib/seoText.js) only turns site-relative paths into links and
# leaves anything else as literal text, so a full URL here would show up as
# raw brackets on the page — reject it before it is written.
LINK_PATTERN = re.compile(r'\[([^\[\]\n]+)\]\(([^)\s]*)\)')
GAME_CATEGORY_PATH = re.compile(r'^/games/([^/?#]+)/([^/?#]+)/?(?:[?#].*)?$')
REGION_PAGE_PATH = re.compile(r'^/games/([^/?#]+)/([^/?#]+)/([^/?#]+)/?(?:[?#].*)?$')
GAME_PATH = re.compile(r'^/games/([^/?#]+)/?(?:[?#].*)?$')


def malformed_links(body):
    """hrefs in *body* that are not site-relative paths."""
    return [
        href for _text, href in LINK_PATTERN.findall(body)
        if not href.startswith('/') or href.startswith('//')
    ]


def region_page_exists(game_slug, category_slug, region):
    game_category = GameCategory.resolve_for_slug(game_slug, category_slug)
    if game_category is None:
        return False
    return game_category.region_pages.filter(region=region).exists()


def dead_link_targets(body, declared_region_paths=frozenset()):
    """/games/... links in *body* whose page does not exist on this site.
    Region pages declared in the same file count as existing (they are
    created by the same run). Other site paths (/keys, /gift-cards, ...) are
    static routes and are taken on trust."""
    dead = []
    for _text, href in LINK_PATTERN.findall(body):
        region = REGION_PAGE_PATH.match(href)
        if region:
            game_slug, category_slug, region_slug = region.groups()
            path = f'/games/{game_slug}/{category_slug}/{region_slug}'
            if path not in declared_region_paths and not region_page_exists(
                    game_slug, category_slug, region_slug):
                dead.append(href)
            continue
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
        'page is skipped so a dead link never goes live. An entry with a "region" '
        'key (an option value on the page\'s Region filter, e.g. "usa") is a '
        'region page at /games/<game>/<category>/<region>: the row that makes the '
        'page exist is created here, so the file doubles as the allow-list.'
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
        self.created = 0

        # One transaction, so a bad entry halfway through the file cannot
        # leave the site half-updated.
        with transaction.atomic():
            updated, unchanged = self.apply_pages(pages)

        prefix = '[DRY RUN] ' if self.dry_run else ''
        created_note = f', {self.created} region page(s) created' if self.created else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}{updated} updated, {unchanged} unchanged{created_note}, '
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

    @staticmethod
    def entry_key(page, index):
        game_slug = str(page.get('game') or '').strip()
        category_slug = str(page.get('category') or '').strip()
        region = str(page.get('region') or '').strip()
        if not game_slug or not category_slug:
            raise CommandError(f'pages[{index}] is missing "game" or "category".')
        return game_slug, category_slug, region

    def validate_fields(self, page, label):
        for field in SEO_FIELDS:
            value = str(page.get(field) or '')
            limit = self.max_lengths[field]
            if limit and len(value) > limit:
                raise CommandError(
                    f'{label}: {field} is {len(value)} chars (max {limit}).'
                )
            if field != 'seo_body' and LINK_PATTERN.search(value):
                raise CommandError(
                    f'{label}: {field} contains a [text](/path) link — links are '
                    'only rendered in seo_body.'
                )

        body = str(page.get('seo_body') or '')
        bad_hrefs = malformed_links(body)
        if bad_hrefs:
            raise CommandError(
                f'{label}: links must be site-relative paths such as '
                f'/games/pubg-mobile/uc, got: {", ".join(bad_hrefs)}'
            )
        return body

    def resolve_region_entry(self, game_slug, category_slug, region):
        """(game_category, label) for a region entry, or (None, reason)."""
        game_category = GameCategory.resolve_for_slug(
            game_slug, category_slug,
            queryset=GameCategory.objects.select_related('game', 'category')
            .prefetch_related('assigned_filters__filter__options'),
        )
        if game_category is None:
            return None, 'page not found'
        labels = region_option_labels(region_filter_for(game_category))
        if region not in labels:
            return None, "region is not an option on the page's Region filter"
        return game_category, labels[region]

    def apply_pages(self, pages):
        updated = unchanged = 0
        seen = set()

        # Region pages declared in this file exist once the run is through
        # (or would, in a dry run), so links to them are not dead — as long
        # as the entry itself resolves.
        declared_region_paths = set()
        for index, page in enumerate(pages):
            game_slug, category_slug, region = self.entry_key(page, index)
            if region and self.resolve_region_entry(game_slug, category_slug, region)[0]:
                declared_region_paths.add(f'/games/{game_slug}/{category_slug}/{region}')
        declared_region_paths = frozenset(declared_region_paths)

        for index, page in enumerate(pages):
            game_slug, category_slug, region = self.entry_key(page, index)
            label = '/'.join(part for part in (game_slug, category_slug, region) if part)

            key = (game_slug, category_slug, region)
            if key in seen:
                raise CommandError(f'Duplicate entry for {label}.')
            seen.add(key)

            body = self.validate_fields(page, label)

            if region:
                game_category, reason = self.resolve_region_entry(
                    game_slug, category_slug, region)
                if game_category is None:
                    self.missing.append(f'{label} ({reason})')
                    continue
                target = game_category.region_pages.filter(region=region).first()
                is_new = target is None
                if is_new:
                    target = CategoryRegionPage(game_category=game_category, region=region)
            else:
                target = GameCategory.resolve_for_slug(game_slug, category_slug)
                is_new = False
                if target is None:
                    self.missing.append(label)
                    continue

            # Only checked once the page itself resolves: on the local demo DB
            # most pages are "not found" anyway, and a dead link there is noise.
            dead = dead_link_targets(body, declared_region_paths) if 'seo_body' in page else []
            if dead:
                self.dead_links.extend((label, href) for href in dead)
                continue

            # Only keys present in the JSON are applied, so a page entry can set
            # e.g. just the title without blanking an existing body.
            changed_fields = []
            for field in SEO_FIELDS:
                if field not in page:
                    continue
                new_value = str(page[field] or '').strip()
                if getattr(target, field) != new_value:
                    setattr(target, field, new_value)
                    changed_fields.append(field)
            if region and 'order' in page:
                try:
                    order = int(page['order'])
                except (TypeError, ValueError):
                    raise CommandError(f'{label}: "order" must be a whole number.')
                if target.order != order:
                    target.order = order
                    changed_fields.append('order')

            if is_new:
                self.created += 1
                if not self.dry_run:
                    target.save()
                verb = 'would create' if self.dry_run else 'created'
                self.stdout.write(f'  {verb} region page {label}')
                continue

            if not changed_fields:
                unchanged += 1
                continue

            if not self.dry_run:
                target.save(update_fields=changed_fields)
            updated += 1
            verb = 'would update' if self.dry_run else 'updated'
            self.stdout.write(f'  {verb} {label}: {", ".join(changed_fields)}')

        return updated, unchanged
