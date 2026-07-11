from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import fazer, fulfillment
from core.models import FazerFulfillmentTask, FazerProductLink, Listing
from core.services import get_platform_setting, set_platform_setting


class Command(BaseCommand):
    help = (
        'Turn Fazer auto-fulfillment ON or OFF. ON: new orders for linked '
        'listings are purchased on Fazer and delivered automatically, and '
        'every linked listing flips to Instant delivery time + wording. '
        'OFF: order processing reverts to manual and the listings revert to '
        '10-15 Minutes wording. In-flight fulfillments always finish. '
        "'status' prints the toggle, link/task counts and the live balance."
    )

    def add_arguments(self, parser):
        parser.add_argument('mode', choices=['on', 'off', 'status'])
        parser.add_argument('--dry-run', action='store_true',
                            help='Show what would change without saving.')

    def handle(self, *args, **options):
        mode = options['mode']
        if mode == 'status':
            self._print_status()
            return

        enable = mode == 'on'
        if enable and not fazer.is_configured():
            raise CommandError(
                'FAZER_API_KEY is not configured — add it to the backend .env '
                'before turning auto-fulfillment on.'
            )

        links = (
            FazerProductLink.objects.filter(enabled=True)
            .select_related('listing')
        )
        changed = []
        field_hits = {'delivery_time': 0, 'description': 0, 'delivery_instructions': 0}
        for link in links.iterator():
            listing = link.listing
            fields = fulfillment.flip_listing_instant(listing, enable)
            if fields:
                for field in fields:
                    field_hits[field] += 1
                changed.append(listing)

        self.stdout.write(f'Linked listings: {links.count()}')
        for field, count in field_hits.items():
            self.stdout.write(f'  {count:>6}  {field} changes')

        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(
                f'[DRY RUN] Would set auto-fulfillment {mode.upper()} and '
                f'update {len(changed)} listings.'
            ))
            return

        # Flip the toggle first so new purchases behave correctly while the
        # bulk text update runs.
        set_platform_setting(fulfillment.AUTOFULFILL_SETTING_KEY, '1' if enable else '0')

        now = timezone.now()
        for listing in changed:
            listing.updated_at = now
        Listing.objects.bulk_update(
            changed,
            ['delivery_time', 'description', 'delivery_instructions', 'updated_at'],
            batch_size=500,
        )
        self.stdout.write(self.style.SUCCESS(
            f'Auto-fulfillment is now {mode.upper()} — updated {len(changed)} listings.'
        ))

    def _print_status(self):
        toggle = get_platform_setting(fulfillment.AUTOFULFILL_SETTING_KEY)
        self.stdout.write(f'Toggle: {"ON" if toggle == "1" else "OFF"}')
        self.stdout.write(f'API key configured: {fazer.is_configured()}')

        self.stdout.write('Links by kind (enabled):')
        for kind, _label in FazerProductLink.KIND_CHOICES:
            count = FazerProductLink.objects.filter(enabled=True, kind=kind).count()
            self.stdout.write(f'  {count:>6}  {kind}')
        disabled = FazerProductLink.objects.filter(enabled=False).count()
        if disabled:
            self.stdout.write(f'  {disabled:>6}  (disabled)')

        self.stdout.write('Tasks by status:')
        for status, _label in FazerFulfillmentTask.STATUS_CHOICES:
            count = FazerFulfillmentTask.objects.filter(status=status).count()
            if count:
                self.stdout.write(f'  {count:>6}  {status}')

        if fazer.is_configured():
            try:
                self.stdout.write(f'Fazer balance: ${fazer.get_balance()}')
            except fazer.FazerError as exc:
                self.stdout.write(self.style.WARNING(f'Balance check failed: {exc}'))
