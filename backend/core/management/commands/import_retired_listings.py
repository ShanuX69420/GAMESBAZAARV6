"""Load a {destination: [listing ids]} map into RetiredListing.

Used once for the 2026 catalogue retirements (offline activation 2026-08-23,
top-ups + six gift-card brands 2026-09-02, plus the top pages the earlier
region cull and duplicate sweeps deleted without a trace):

    python manage.py import_retired_listings core/data/retired_listings_2026-09-02.json

Each id gets a record whose heir_path is pinned to the map's destination
(those were verified live when the map was built). Ids that still exist as
listings are skipped — a live row always wins over a retirement record.
Re-running is safe: existing records are updated, not duplicated.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.models import Listing, RetiredListing


class Command(BaseCommand):
    help = 'Import a {destination: [listing ids]} JSON map as RetiredListing records.'

    def add_arguments(self, parser):
        parser.add_argument('path', help='JSON file: {"/games/x/y": [id, ...], ...}')
        parser.add_argument('--reason', default='catalog_retired',
                            help='Reason stored on every record (default: catalog_retired).')
        parser.add_argument('--retired-at', default='',
                            help='ISO datetime the listings were deleted (default: now).')

    def handle(self, *args, **options):
        path = Path(options['path'])
        if not path.is_file():
            raise CommandError(f'{path} does not exist.')
        try:
            mapping = json.loads(path.read_text(encoding='utf-8'))
        except ValueError as exc:
            raise CommandError(f'{path} is not valid JSON: {exc}')
        if not isinstance(mapping, dict):
            raise CommandError('Expected an object of {destination: [ids]}.')

        reason = options['reason']
        valid_reasons = {value for value, _label in RetiredListing.REASON_CHOICES}
        if reason not in valid_reasons:
            raise CommandError(f'--reason must be one of: {", ".join(sorted(valid_reasons))}.')

        # An explicit date is written on every record; otherwise new records
        # get "now" and existing ones keep the date they already have.
        explicit_retired_at = None
        if options['retired_at']:
            explicit_retired_at = parse_datetime(options['retired_at'])
            if explicit_retired_at is None:
                raise CommandError('--retired-at must be an ISO datetime.')
            if timezone.is_naive(explicit_retired_at):
                explicit_retired_at = timezone.make_aware(explicit_retired_at)
        retired_at = explicit_retired_at or timezone.now()

        wanted = {}
        for destination, ids in mapping.items():
            if not isinstance(destination, str) or not destination.startswith('/'):
                raise CommandError(f'Destination {destination!r} must be a site path.')
            if not isinstance(ids, list):
                raise CommandError(f'Ids for {destination} must be a list.')
            for listing_id in ids:
                if not isinstance(listing_id, int) or listing_id <= 0:
                    raise CommandError(f'Bad listing id {listing_id!r} under {destination}.')
                if listing_id in wanted and wanted[listing_id] != destination:
                    raise CommandError(
                        f'Listing {listing_id} appears under two destinations.'
                    )
                wanted[listing_id] = destination

        alive = set(Listing.objects.filter(pk__in=wanted).values_list('pk', flat=True))
        created = updated = 0
        for listing_id, destination in sorted(wanted.items()):
            if listing_id in alive:
                continue
            defaults = {'heir_path': destination, 'reason': reason}
            if explicit_retired_at is not None:
                defaults['retired_at'] = explicit_retired_at
            _record, was_created = RetiredListing.objects.update_or_create(
                listing_id=listing_id,
                defaults=defaults,
                create_defaults={**defaults, 'retired_at': retired_at},
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'{created} record(s) created, {updated} updated, '
            f'{len(alive)} skipped because the listing still exists.'
        ))
