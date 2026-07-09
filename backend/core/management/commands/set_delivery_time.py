from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count
from django.utils import timezone

from core.models import Listing
from core.management.commands.import_listings import MANUAL_DELIVERY_TIMES


class Command(BaseCommand):
    help = (
        'Bulk-set the delivery time on manual (non-auto-delivery) listings. '
        'Auto-delivery/Instant listings are never touched. By default every '
        'manual listing is updated; narrow with --only-from or --seller.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--to', default='10-15 Minutes',
                            help='Target delivery time (default: 10-15 Minutes)')
        parser.add_argument('--only-from', dest='only_from',
                            help='Only update listings whose current delivery '
                                 'time equals this value (e.g., "1-2 Hours")')
        parser.add_argument('--seller',
                            help='Only update listings owned by this username')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change without saving anything.')

    def handle(self, *args, **options):
        target = options['to']
        if target not in MANUAL_DELIVERY_TIMES:
            raise CommandError(
                f'"{target}" is not a valid manual delivery time. '
                f'Choose one of: {MANUAL_DELIVERY_TIMES}'
            )

        qs = (
            Listing.objects
            .filter(is_auto_delivery=False)
            .exclude(delivery_time='Instant')
            .exclude(delivery_time=target)
        )
        if options['only_from']:
            qs = qs.filter(delivery_time=options['only_from'])
        if options['seller']:
            qs = qs.filter(seller__username=options['seller'])

        breakdown = (
            qs.values('delivery_time')
            .annotate(cnt=Count('id'))
            .order_by('-cnt')
        )
        for row in breakdown:
            self.stdout.write(f"  {row['cnt']:>6}  \"{row['delivery_time']}\" -> \"{target}\"")

        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(
                f'[DRY RUN] Would have updated {qs.count()} listings.'
            ))
            return

        updated = qs.update(delivery_time=target, updated_at=timezone.now())
        self.stdout.write(self.style.SUCCESS(f'Updated {updated} listings.'))
