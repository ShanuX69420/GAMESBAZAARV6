import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import fulfillment
from core.models import FazerProductLink, Listing
from core.services import get_platform_setting

VALID_KINDS = {kind for kind, _ in FazerProductLink.KIND_CHOICES}


class Command(BaseCommand):
    help = (
        'Upsert Listing↔Fazer product links from a JSON file pushed by the '
        'PC-side sync (tools/fazer_push_links.py). Newly linked listings '
        'automatically pick up the current auto-fulfillment state (Instant '
        'timing + wording when the toggle is ON) — that is how freshly '
        'seeded Fazer products become auto-delivered with no extra wiring.'
    )

    def add_arguments(self, parser):
        parser.add_argument('path', nargs='?', default='/tmp/fazer_links.json')
        parser.add_argument('--prune', action='store_true',
                            help='Disable links whose listing is absent from the file '
                                 '(their listings revert to manual wording).')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        try:
            with open(options['path'], encoding='utf-8') as fh:
                payload = json.load(fh)
        except (OSError, ValueError) as exc:
            raise CommandError(f'Could not read {options["path"]}: {exc}')

        rows = payload.get('links') if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise CommandError('Payload must be a list of link rows or {"links": [...]}.')

        toggle_on = get_platform_setting(fulfillment.AUTOFULFILL_SETTING_KEY) == '1'
        now = timezone.now()

        created = updated = skipped = 0
        flip_on = []   # listings newly linked/re-enabled while the toggle is ON
        seen_listing_ids = set()

        for row in rows:
            listing_id = row.get('listing_id')
            kind = row.get('kind')
            if kind not in VALID_KINDS or not listing_id:
                skipped += 1
                self.stderr.write(f'  skip: bad row {str(row)[:120]}')
                continue
            listing = Listing.objects.filter(pk=listing_id).first()
            if listing is None:
                skipped += 1
                self.stderr.write(f'  skip: listing {listing_id} not found')
                continue

            seen_listing_ids.add(listing.pk)
            defaults = {
                'kind': kind,
                'fazer_category_id': str(row.get('fazer_category_id') or '')[:100],
                'offer_name': str(row.get('offer_name') or '')[:200],
                'fazer_region': str(row.get('fazer_region') or '')[:8],
                'checkout_fields': row.get('checkout_fields') or [],
                'enabled': True,
                'last_synced_at': now,
            }
            # Keep the previous sku/cost when the push couldn't resolve them
            # (supplier fetch failed) — the cost is the price-sanity baseline.
            if row.get('sku_id'):
                defaults['last_sku_id'] = str(row['sku_id'])[:100]
            if row.get('cost_usd'):
                defaults['last_cost_usd'] = row['cost_usd']
            if not defaults['fazer_category_id'] or not defaults['offer_name']:
                skipped += 1
                self.stderr.write(f'  skip: listing {listing_id} missing ids')
                continue
            if kind == 'gift' and not defaults['fazer_region']:
                skipped += 1
                self.stderr.write(f'  skip: gift listing {listing_id} has no region')
                continue

            if options['dry_run']:
                exists = FazerProductLink.objects.filter(listing_id=listing.pk).first()
                created += 0 if exists else 1
                updated += 1 if exists else 0
                continue

            link, was_created = FazerProductLink.objects.update_or_create(
                listing_id=listing.pk, defaults=defaults,
            )
            if was_created:
                created += 1
            else:
                updated += 1
            if toggle_on and listing.delivery_time != 'Instant':
                flip_on.append(listing)

        pruned_listings = []
        if options['prune']:
            stale = (
                FazerProductLink.objects.filter(enabled=True)
                .exclude(listing_id__in=seen_listing_ids)
                .select_related('listing')
            )
            for link in stale:
                pruned_listings.append(link.listing)
            if not options['dry_run'] and pruned_listings:
                stale.update(enabled=False, updated_at=now)

        # Bring listing timing/wording in line with the toggle for anything
        # that just gained or lost its link.
        changed = []
        for listing in flip_on:
            if fulfillment.flip_listing_instant(listing, True):
                changed.append(listing)
        for listing in pruned_listings:
            if fulfillment.flip_listing_instant(listing, False):
                changed.append(listing)
        if not options['dry_run'] and changed:
            for listing in changed:
                listing.updated_at = now
            Listing.objects.bulk_update(
                changed,
                ['delivery_time', 'description', 'delivery_instructions', 'updated_at'],
                batch_size=500,
            )

        prefix = '[DRY RUN] ' if options['dry_run'] else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Links: {created} created, {updated} updated, '
            f'{skipped} skipped, {len(pruned_listings)} pruned; '
            f'{len(changed)} listings re-flipped (toggle {"ON" if toggle_on else "OFF"}).'
        ))
