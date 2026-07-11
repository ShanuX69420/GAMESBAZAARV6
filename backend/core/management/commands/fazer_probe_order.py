"""Calibration probe: place ONE real (cheap) Fazer order and dump the raw
completed payload so parse_delivered_codes can be verified against reality
before auto-fulfillment goes live. Spends real supplier balance — requires
an explicit --yes."""

import json
import time

from django.core.management.base import BaseCommand, CommandError

from core import fazer, fulfillment
from core.models import FazerProductLink

PROBE_POLL_SECONDS = 3
PROBE_TIMEOUT_SECONDS = 180


class Command(BaseCommand):
    help = (
        'Place one REAL supplier order against Fazer and print the raw '
        'completed response plus what the code parser extracts. Use the '
        'cheapest gift card/key for calibration. Requires --yes to spend.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--listing', type=int,
                            help='Use this listing\'s Fazer link as the target.')
        parser.add_argument('--kind', choices=['gamekey', 'giftcard', 'topup'])
        parser.add_argument('--category-id',
                            help='Fazer game_id (gamekey) or category_id.')
        parser.add_argument('--offer', help='Exact offer name to buy.')
        parser.add_argument('--field', action='append', default=[],
                            help='Top-up checkout field, e.g. --field player_id=123.')
        parser.add_argument('--yes', action='store_true',
                            help='Actually place the order (spends real money).')

    def handle(self, *args, **options):
        if not fazer.is_configured():
            raise CommandError('FAZER_API_KEY is not configured.')

        if options['listing']:
            link = FazerProductLink.objects.filter(
                listing_id=options['listing'],
            ).first()
            if link is None:
                raise CommandError(f'Listing {options["listing"]} has no Fazer link.')
            kind, category_id, offer_name = link.kind, link.fazer_category_id, link.offer_name
        else:
            kind, category_id, offer_name = (
                options['kind'], options['category_id'], options['offer'],
            )
            if not (kind and category_id and offer_name):
                raise CommandError('Pass --listing OR all of --kind/--category-id/--offer.')

        fields = {}
        for pair in options['field']:
            key, _, value = pair.partition('=')
            fields[key.strip()] = value.strip()
        if kind == 'topup' and not fields:
            raise CommandError('Top-up probes need --field player_id=... (or user_id).')

        # Resolve the live offer.
        if kind == 'gamekey':
            offers = fazer.list_gamekey_offers(category_id)
            sku_field = 'key_id'
        elif kind == 'giftcard':
            offers = fazer.list_giftcard_offers(category_id)
            sku_field = 'card_id'
        else:
            offers = fazer.list_topup_offers(category_id).get('offers') or []
            sku_field = 'offer_id'

        offer = fulfillment._match_offer(offers, offer_name, sku_field=sku_field)
        if offer is None:
            names = ', '.join(str(o.get('name')) for o in offers[:20])
            raise CommandError(f'Offer "{offer_name}" not found. Available: {names}')

        self.stdout.write(f'Target: {kind} {category_id} / {offer.get("name")}')
        self.stdout.write(f'Cost:   ${offer.get("price_usd")}   '
                          f'(balance: ${fazer.get_balance()})')

        if not options['yes']:
            self.stdout.write(self.style.WARNING(
                'Dry probe only — re-run with --yes to place this REAL order.'
            ))
            return

        idempotency_key = f'probe-{int(time.time())}'
        if kind == 'gamekey':
            supplier_order = fazer.create_gamekey_order(
                game_id=category_id, key_id=offer['key_id'], quantity=1,
                idempotency_key=idempotency_key,
            )
        elif kind == 'giftcard':
            supplier_order = fazer.create_giftcard_order(
                category_id=category_id, card_id=offer['card_id'], quantity=1,
                idempotency_key=idempotency_key,
            )
        else:
            supplier_order = fazer.create_topup_order(
                category_id=category_id, offer_id=offer['offer_id'],
                fields=fields, idempotency_key=idempotency_key,
            )

        order_id = supplier_order['id']
        self.stdout.write(f'Placed supplier order {order_id} '
                          f'(status {supplier_order.get("status")}) — polling…')

        deadline = time.monotonic() + PROBE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            supplier_order = fazer.get_order(order_id)
            status = str(supplier_order.get('status'))
            if status in fazer.COMPLETED_STATUSES | fazer.FAILED_STATUSES:
                break
            time.sleep(PROBE_POLL_SECONDS)

        self.stdout.write('--- RAW ORDER JSON ' + '-' * 40)
        self.stdout.write(json.dumps(supplier_order, indent=2, ensure_ascii=False))
        self.stdout.write('--- PARSED CODES ' + '-' * 42)
        codes = fulfillment.parse_delivered_codes(supplier_order)
        if codes:
            for line in codes:
                self.stdout.write(f'  {line}')
            self.stdout.write(self.style.SUCCESS(
                f'{len(codes)} code line(s) extracted — parser looks good.'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                'NO codes extracted — extend CODE_VALUE_KEYS/CODE_CONTAINER_KEYS '
                'in core/fulfillment.py to match the raw JSON above.'
            ))
