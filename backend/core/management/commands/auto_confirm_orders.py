from django.core.management.base import BaseCommand, CommandError

from core.services import auto_confirm_due_orders


class Command(BaseCommand):
    help = 'Auto-confirm delivered orders after the 72-hour buyer review window.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Maximum number of due delivered orders to process.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='List how many orders are due without completing them.',
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        if batch_size < 1:
            raise CommandError('--batch-size must be at least 1.')

        result = auto_confirm_due_orders(
            batch_size=batch_size,
            dry_run=options['dry_run'],
        )

        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING(
                    f'{result["due_count"]} delivered order(s) are due for auto-confirmation.'
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f'Auto-confirmed {result["confirmed_count"]} order(s); '
                f'skipped {result["skipped_count"]}.'
            )
        )
