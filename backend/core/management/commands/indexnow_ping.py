"""Timer-driven IndexNow ping: tells Bing (and the other IndexNow engines)
which public pages changed since the last run.

Default mode detects changes from Listing.updated_at — every listing saved,
repriced, retired or revived since the last successful ping, plus the
game+category page each of them sits on. Safe to run every 30 minutes: the
cursor only moves once IndexNow accepts the batch, and an empty window sends
nothing at all.

One-off modes for hand use:
  --paths /games/pubg/top-ups ...   submit specific pages (e.g. after an SEO
                                    copy reseed, which does not touch listings)
  --all-category-pages              every indexable game+category page — the
                                    initial catch-up push
  --since-hours 48                  widen the change window for one run
  --dry-run                         print what would be sent, send nothing

Without INDEXNOW_KEY in the environment the command is a no-op, so the timer
can be installed before the key is configured.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import indexnow

MAX_URLS_LISTED = 200


class Command(BaseCommand):
    help = (
        'Tell Bing and the other IndexNow engines which pages changed. '
        'Safe to run every 30 minutes; no-op without INDEXNOW_KEY.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--since-hours', type=float, default=None,
                            help='Look back this many hours instead of since the last ping.')
        parser.add_argument('--paths', nargs='+', metavar='PATH',
                            help='Submit these site paths or URLs instead of detecting changes.')
        parser.add_argument('--all-category-pages', action='store_true',
                            help='Submit every indexable game+category page (one-off catch-up).')
        parser.add_argument('--dry-run', action='store_true',
                            help='Print what would be submitted without sending anything.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        if not indexnow.is_enabled() and not dry_run:
            self.stdout.write('IndexNow is off: INDEXNOW_KEY is not set. Nothing sent.')
            return

        fixed = [indexnow.absolute_url(path) for path in (options['paths'] or [])]
        if options['all_category_pages']:
            fixed += indexnow.indexable_category_page_urls()

        try:
            if fixed:
                self.submit_fixed(fixed, dry_run)
            else:
                self.submit_changes(options['since_hours'], dry_run)
        except indexnow.IndexNowError as exc:
            raise CommandError(str(exc)) from exc

    def submit_fixed(self, urls, dry_run):
        urls = list(dict.fromkeys(urls))
        if dry_run:
            self.stdout.write(f'Dry run: would submit {len(urls)} URL(s):')
            self.list_urls(urls)
            return
        sent = indexnow.submit(urls)
        self.stdout.write(f'Submitted {len(sent)} URL(s).')

    def submit_changes(self, since_hours, dry_run):
        since = timezone.now() - timedelta(hours=since_hours) if since_hours else None
        since, category_urls, listing_urls = indexnow.ping_changes(since=since, dry_run=dry_run)
        total = len(category_urls) + len(listing_urls)
        window = f'changed since {since.isoformat(timespec="seconds")}'
        label = (f'{total} URL(s) ({len(category_urls)} category page(s), '
                 f'{len(listing_urls)} listing page(s)) {window}')

        if dry_run:
            self.stdout.write(f'Dry run: would submit {label}:')
            self.list_urls(category_urls + listing_urls)
            return
        if not total:
            self.stdout.write(f'Nothing {window}; nothing sent.')
            return
        self.stdout.write(f'Submitted {label}.')

    def list_urls(self, urls):
        for url in urls[:MAX_URLS_LISTED]:
            self.stdout.write(f'  {url}')
        if len(urls) > MAX_URLS_LISTED:
            self.stdout.write(f'  ... and {len(urls) - MAX_URLS_LISTED} more')
