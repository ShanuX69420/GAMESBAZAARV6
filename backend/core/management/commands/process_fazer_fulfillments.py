from datetime import timedelta

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from core import fazer, fulfillment
from core.models import FazerFulfillmentTask, FazerProductLink
from core.services import send_transactional_email

LOW_BALANCE_ALERT_CACHE_KEY = 'fazer-low-balance-alert:v1'
# The timer keeps each task short — placement plus a brief poll; anything
# still processing is picked up again on the next tick via next_poll_at.
TIMER_POLL_BUDGET_SECONDS = 10


class Command(BaseCommand):
    help = (
        'Drive pending Fazer auto-fulfillment tasks: place supplier orders '
        'that the on-commit worker missed (restart/crash), poll processing '
        'orders, and deliver completed ones. Safe to run every minute — '
        'claims are atomic and idempotency keys make supplier replays free.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--batch-size', type=int, default=20)
        parser.add_argument('--dry-run', action='store_true',
                            help='List due tasks without processing them.')

    def handle(self, *args, **options):
        now = timezone.now()
        due = (
            Q(status='queued',
              created_at__lt=now - fulfillment.QUEUED_PICKUP_DELAY)
            | Q(status='placing',
                claimed_at__lt=now - fulfillment.PLACING_STALE_AFTER)
            | Q(status='processing', next_poll_at__lte=now)
        )
        task_ids = list(
            FazerFulfillmentTask.objects.filter(due)
            .order_by('created_at')
            .values_list('pk', flat=True)[:options['batch_size']]
        )

        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(
                f'[DRY RUN] {len(task_ids)} task(s) due: {task_ids}'
            ))
            return

        processed = 0
        for task_id in task_ids:
            fulfillment.process_fulfillment_task(
                task_id, poll_budget_seconds=TIMER_POLL_BUDGET_SECONDS,
            )
            processed += 1

        self._maybe_alert_low_balance()

        if processed:
            self.stdout.write(self.style.SUCCESS(f'Processed {processed} task(s).'))

    def _maybe_alert_low_balance(self):
        """Warn the linked-listing sellers once a day when the Fazer USD
        balance drops below the configured floor."""
        from decimal import Decimal, InvalidOperation

        from django.conf import settings

        if not fulfillment.autofulfill_enabled():
            return
        if not cache.add(LOW_BALANCE_ALERT_CACHE_KEY, '1', 24 * 60 * 60):
            return  # already alerted in the last 24h
        try:
            balance = Decimal(str(fazer.get_balance()))
        except (fazer.FazerError, InvalidOperation):
            return
        if balance >= settings.FAZER_LOW_BALANCE_USD:
            cache.delete(LOW_BALANCE_ALERT_CACHE_KEY)  # don't burn today's slot
            return

        seller_ids = (
            FazerProductLink.objects.filter(enabled=True)
            .values_list('listing__seller', flat=True).distinct()
        )
        from django.contrib.auth import get_user_model
        for seller in get_user_model().objects.filter(pk__in=seller_ids):
            send_transactional_email(
                seller,
                subject='GamesBazaar — Fazer balance is running low',
                message_body=(
                    f'Your Fazer USD balance is ${balance} — below the '
                    f'${settings.FAZER_LOW_BALANCE_USD} warning level. '
                    'Top it up so automatic deliveries keep working.'
                ),
                status_text='Low Balance',
                status_class='warning',
            )
        self.stdout.write(self.style.WARNING(f'Low Fazer balance: ${balance}'))
