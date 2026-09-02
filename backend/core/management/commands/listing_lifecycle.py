"""Maintenance for the listing lifecycle (core/listing_lifecycle.py).

  --backfill                 stamp unavailable_since = updated_at on every off
                             listing that has no stamp (the one-time transition
                             when the feature shipped, and a safety net after
                             any bulk update that skipped save()); clear stale
                             stamps on active listings.
  --set-reason R --ids 1,2   mark off listings as gone for good with reason R
                             (game_gone, region_gone, discontinued, hand_retired,
                             superseded). Their pages redirect on the next request.
  --report                   how many listings sit in each state, and where the
                             gone ones redirect.
  --report --paths           print only /listing/<id> for the gone and unindexed
                             ones, one per line — feed it to indexnow_ping --paths
                             so Bing recrawls the redirects.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F
from django.utils import timezone

from core import listing_lifecycle
from core.models import PERMANENT_RETIRE_REASONS, Listing


class Command(BaseCommand):
    help = 'Backfill, tag or report the listing lifecycle states.'

    def add_arguments(self, parser):
        parser.add_argument('--backfill', action='store_true',
                            help='Stamp unstamped off listings from updated_at; '
                                 'clear stamps left on active ones.')
        parser.add_argument('--set-reason', default='',
                            help='Permanent reason to put on the listings in --ids.')
        parser.add_argument('--ids', default='',
                            help='Comma-separated listing ids for --set-reason.')
        parser.add_argument('--report', action='store_true',
                            help='Count listings per lifecycle state.')
        parser.add_argument('--paths', action='store_true',
                            help='With --report: print the redirecting/404 listing paths only.')

    def handle(self, *args, **options):
        did_something = False
        if options['backfill']:
            self.backfill()
            did_something = True
        if options['set_reason'] or options['ids']:
            self.set_reason(options['set_reason'], options['ids'])
            did_something = True
        if options['report']:
            self.report(paths_only=options['paths'])
            did_something = True
        if not did_something:
            raise CommandError('Nothing to do: pass --backfill, --set-reason/--ids or --report.')

    def backfill(self):
        stamped = Listing.objects.exclude(status='active').filter(
            unavailable_since__isnull=True,
        ).update(unavailable_since=F('updated_at'))
        cleared = Listing.objects.filter(status='active').exclude(
            unavailable_since__isnull=True, retire_reason='',
        ).update(unavailable_since=None, retire_reason='')
        self.stdout.write(self.style.SUCCESS(
            f'Stamped {stamped} off listing(s) from updated_at; '
            f'cleared stale stamps on {cleared} active listing(s).'
        ))

    def set_reason(self, reason, ids):
        if reason not in PERMANENT_RETIRE_REASONS:
            raise CommandError(
                f'--set-reason must be one of: {", ".join(sorted(PERMANENT_RETIRE_REASONS))}.'
            )
        try:
            listing_ids = sorted({int(part) for part in ids.split(',') if part.strip()})
        except ValueError:
            raise CommandError('--ids must be comma-separated integers.')
        if not listing_ids:
            raise CommandError('--set-reason needs --ids.')
        rows = list(Listing.objects.filter(pk__in=listing_ids))
        missing = sorted(set(listing_ids) - {row.pk for row in rows})
        if missing:
            raise CommandError(f'No such listing(s): {missing}')
        still_active = sorted(row.pk for row in rows if row.status == 'active')
        if still_active:
            raise CommandError(
                f'Listing(s) {still_active} are active. Switch them off first '
                f'(status inactive), then tag them.'
            )
        now = timezone.now()
        for row in rows:
            row.retire_reason = reason
            if row.unavailable_since is None:
                row.unavailable_since = now
            row.save(update_fields=['retire_reason', 'unavailable_since'])
        self.stdout.write(self.style.SUCCESS(
            f'Tagged {len(rows)} listing(s) as {reason}; their pages redirect from now on.'
        ))

    def report(self, paths_only=False):
        now = timezone.now()
        counts = {'active': 0, 'paused': 0, 'gone': 0, 'unindexed': 0}
        detail = []
        qs = Listing.objects.select_related(
            'game_category__game', 'game_category__category',
        ).order_by('pk')
        counts['active'] = qs.filter(status='active').count()
        for listing in qs.exclude(status='active'):
            state = listing_lifecycle.lifecycle_for_listing(listing, now=now)
            counts[state['state']] += 1
            if state['state'] in ('gone', 'unindexed'):
                detail.append((listing.pk, state['state'], state.get('reason', ''),
                               state.get('redirect_to') or '(404)'))
        if paths_only:
            for pk, _state, _reason, _target in detail:
                self.stdout.write(listing_lifecycle.listing_path(pk))
            return
        self.stdout.write(
            f"active {counts['active']}  paused {counts['paused']}  "
            f"gone {counts['gone']}  unindexed {counts['unindexed']}"
        )
        for pk, state, reason, target in detail:
            self.stdout.write(f'  #{pk:<7} {state:<9} {reason:<14} -> {target}')
