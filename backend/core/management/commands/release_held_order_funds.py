from django.core.management.base import BaseCommand, CommandError

from core.services import release_due_held_order_funds


class Command(BaseCommand):
    help = 'Release buyer-protected seller payouts after the 14-day hold.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Maximum number of due held payouts to process.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='List how many held payouts are due without releasing them.',
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        if batch_size < 1:
            raise CommandError('--batch-size must be at least 1.')

        result = release_due_held_order_funds(
            batch_size=batch_size,
            dry_run=options['dry_run'],
        )

        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING(
                    f'{result["due_count"]} held payout(s) are due for release.'
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f'Released {result["released_count"]} held payout(s); '
                f'skipped {result["skipped_count"]}.'
            )
        )
