from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import fazer, fulfillment
from core.models import FazerFulfillmentTask, FazerProductLink, Listing
from core.services import get_platform_setting, set_platform_setting

VALID_KINDS = [kind for kind, _label in FazerProductLink.KIND_CHOICES]


class Command(BaseCommand):
    help = (
        'Turn Fazer auto-fulfillment ON or OFF. ON: new orders for linked '
        'listings are purchased on Fazer and delivered automatically, and '
        'every linked listing flips to Instant delivery time + wording. '
        'OFF: order processing reverts to manual and the listings revert to '
        '10-15 Minutes wording. In-flight fulfillments always finish. '
        "'pause <kind>' / 'resume <kind>' switch ONE product line "
        f'({"/".join(VALID_KINDS)}) without touching the rest — use it when '
        'the supplier turns a product line off. '
        "'status' prints the toggle, paused lines, link/task counts and the "
        'live balance.'
    )

    def add_arguments(self, parser):
        parser.add_argument('mode', choices=['on', 'off', 'status', 'pause', 'resume'])
        parser.add_argument('kinds', nargs='*',
                            help='Product line(s) for pause/resume, e.g. gift.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Show what would change without saving.')

    def handle(self, *args, **options):
        mode = options['mode']
        if mode == 'status':
            self._print_status()
            return

        kinds = options['kinds']
        if mode in ('pause', 'resume'):
            if not kinds:
                raise CommandError(
                    f'{mode} needs at least one product line: '
                    f'{", ".join(VALID_KINDS)}.'
                )
            bad = [k for k in kinds if k not in VALID_KINDS]
            if bad:
                raise CommandError(
                    f'Unknown product line(s): {", ".join(bad)}. '
                    f'Valid: {", ".join(VALID_KINDS)}.'
                )
        elif kinds:
            raise CommandError(f'{mode} takes no product line — use pause/resume.')

        # Read the raw toggle, not autofulfill_enabled() — a missing API key
        # must not silently turn the switch off on an unrelated pause/resume.
        toggle_on = get_platform_setting(fulfillment.AUTOFULFILL_SETTING_KEY) == '1'
        paused = fulfillment.paused_kinds()
        if mode == 'on':
            toggle_on = True
        elif mode == 'off':
            toggle_on = False
        elif mode == 'pause':
            paused |= set(kinds)
        else:  # resume
            paused -= set(kinds)

        if mode == 'on' and not fazer.is_configured():
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
            instant = toggle_on and link.kind not in paused
            fields = fulfillment.flip_listing_instant(listing, instant)
            if fields:
                for field in fields:
                    field_hits[field] += 1
                changed.append(listing)

        self.stdout.write(f'Linked listings: {links.count()}')
        for field, count in field_hits.items():
            self.stdout.write(f'  {count:>6}  {field} changes')

        summary = 'ON' if toggle_on else 'OFF'
        if paused:
            summary += f' (paused: {", ".join(sorted(paused))})'
        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(
                f'[DRY RUN] Would set auto-fulfillment {summary} and '
                f'update {len(changed)} listings.'
            ))
            return

        # Flip the toggles first so new purchases behave correctly while the
        # bulk text update runs.
        set_platform_setting(fulfillment.AUTOFULFILL_SETTING_KEY,
                             '1' if toggle_on else '0')
        set_platform_setting(fulfillment.PAUSED_KINDS_SETTING_KEY,
                             ','.join(sorted(paused)))

        now = timezone.now()
        for listing in changed:
            listing.updated_at = now
        Listing.objects.bulk_update(
            changed,
            ['delivery_time', 'description', 'delivery_instructions', 'updated_at'],
            batch_size=500,
        )
        self.stdout.write(self.style.SUCCESS(
            f'Auto-fulfillment is now {summary} — updated {len(changed)} listings.'
        ))

    def _print_status(self):
        toggle = get_platform_setting(fulfillment.AUTOFULFILL_SETTING_KEY)
        paused = fulfillment.paused_kinds()
        self.stdout.write(f'Toggle: {"ON" if toggle == "1" else "OFF"}')
        self.stdout.write(
            f'Paused product lines: {", ".join(sorted(paused)) if paused else "none"}'
        )
        self.stdout.write(f'API key configured: {fazer.is_configured()}')

        self.stdout.write('Links by kind (enabled):')
        for kind, _label in FazerProductLink.KIND_CHOICES:
            count = FazerProductLink.objects.filter(enabled=True, kind=kind).count()
            note = '  PAUSED (manual)' if kind in paused else ''
            self.stdout.write(f'  {count:>6}  {kind}{note}')
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
