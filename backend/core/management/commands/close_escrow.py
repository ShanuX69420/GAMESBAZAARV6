"""One-off cutover for the 2026-08 shop conversion: retire escrow.

Completes every order stuck in the old 'delivered' state (crediting the house
seller) and releases every payout still held under the retired 14-day buyer
protection. Idempotent — the sale wallet transaction is keyed per order, so
running it twice cannot double-credit. Leaves historical 'disputed' orders
alone (resolve those from the Django admin actions).
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Order
from core.services import complete_order_now, release_order_funds_to_seller_once


class Command(BaseCommand):
    help = "Complete 'delivered' orders and release held payouts (escrow retirement cutover)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change without touching anything.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        delivered_ids = list(
            Order.objects.filter(status='delivered').values_list('pk', flat=True)
        )
        held_ids = list(
            Order.objects.filter(
                status='completed',
                buyer_protection_enabled=True,
                seller_payout_released_at__isnull=True,
            ).values_list('pk', flat=True)
        )
        disputed_count = Order.objects.filter(status='disputed').count()

        self.stdout.write(
            f'{len(delivered_ids)} delivered order(s) to complete, '
            f'{len(held_ids)} held payout(s) to release, '
            f'{disputed_count} disputed order(s) left for admin.'
        )
        if dry_run:
            return

        for order_id in delivered_ids:
            with transaction.atomic():
                order = (
                    Order.objects.select_for_update()
                    .select_related('seller')
                    .get(pk=order_id)
                )
                if order.status != 'delivered':
                    continue
                complete_order_now(order)
                self.stdout.write(f'Completed order #{order.order_number}')

        for order_id in held_ids:
            with transaction.atomic():
                order = (
                    Order.objects.select_for_update()
                    .select_related('seller')
                    .get(pk=order_id)
                )
                if order.status != 'completed' or order.seller_payout_released_at:
                    continue
                _, released = release_order_funds_to_seller_once(
                    order,
                    sale_description=f'Order completed: {order.listing_title} (x{order.quantity})',
                    commission_description=f'Commission ({order.commission_rate}%): {order.listing_title}',
                    ledger_description=f'Commission collected: {order.listing_title} (x{order.quantity})',
                )
                if released:
                    self.stdout.write(f'Released payout for order #{order.order_number}')

        self.stdout.write(self.style.SUCCESS('Escrow cutover done.'))
