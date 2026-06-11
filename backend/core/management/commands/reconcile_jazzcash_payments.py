from django.core.management.base import BaseCommand, CommandError

from core import jazzcash
from core.payments import reconcile_pending_jazzcash_payments, STATUS_INQUIRY_MIN_AGE


class Command(BaseCommand):
    help = (
        'Settle pending JazzCash payments via the mandatory Status Inquiry API '
        'and expire transactions that were never confirmed. Run on a schedule '
        '(e.g., every 10-15 minutes) alongside the IPN webhook.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=50,
            help='Maximum number of pending payments to check.',
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        if batch_size < 1:
            raise CommandError('--batch-size must be at least 1.')

        if not jazzcash.is_configured():
            self.stdout.write(self.style.WARNING(
                'JazzCash is not configured; nothing to reconcile.'
            ))
            return

        result = reconcile_pending_jazzcash_payments(
            batch_size=batch_size,
            min_age=STATUS_INQUIRY_MIN_AGE,
        )

        self.stdout.write(self.style.SUCCESS(
            f'Checked {result["checked"]} payment(s): '
            f'{result["completed"]} completed, {result["failed"]} failed, '
            f'{result["expired"]} expired, {result["still_pending"]} still pending.'
        ))
