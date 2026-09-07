"""Send Meta the Purchase event for a completed WhatsApp sale again.

For when the automatic send at completion time failed — Meta rejected it
(e.g. the buyer's number was unreadable, error 2804050) or the request never
got through. The event is rebuilt from the row as it is now, stamped with
the row's completion time, and delivered synchronously so the outcome is
printed here:

    python manage.py resend_whatsapp_purchase WA-4CUF5J [WA-... ...]
    python manage.py resend_whatsapp_purchase WA-4CUF5J --dry-run

Meta accepts an event up to seven days after its event_time, so a sale
completed longer ago than that cannot be recovered. The event ID is the
same ``wa-purchase-<ref>`` as the original, so a resend of an event Meta
did accept is deduplicated rather than double counted.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import meta_capi
from core.models import WhatsAppCheckout

MAX_EVENT_AGE = timedelta(days=7)


class Command(BaseCommand):
    help = "Send the Meta Purchase event for completed WhatsApp sales again."

    def add_arguments(self, parser):
        parser.add_argument('refs', nargs='+', metavar='REF',
                            help='WhatsApp checkout reference(s), e.g. WA-4CUF5J')
        parser.add_argument('--dry-run', action='store_true',
                            help='Show what would be sent (match keys by name) without sending.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        if not dry_run and not meta_capi.is_configured():
            raise CommandError('META_PIXEL_ID and META_CAPI_ACCESS_TOKEN must both be set.')

        failures = 0
        for ref in options['refs']:
            if not self.resend(ref.strip().upper(), dry_run):
                failures += 1
        if failures:
            raise CommandError(f'{failures} event(s) were not sent - see above.')

    def resend(self, ref, dry_run):
        checkout = WhatsAppCheckout.objects.filter(ref=ref).first()
        if checkout is None:
            self.stderr.write(f'{ref}: no such WhatsApp checkout.')
            return False
        if checkout.status != 'completed' or checkout.completed_at is None:
            self.stderr.write(f'{ref}: status is "{checkout.status}", only completed sales are sent.')
            return False
        age = timezone.now() - checkout.completed_at
        if age > MAX_EVENT_AGE:
            self.stderr.write(
                f'{ref}: completed {age.days} days ago - Meta only accepts events '
                f'up to {MAX_EVENT_AGE.days} days old.'
            )
            return False

        event = meta_capi.build_whatsapp_purchase_event(
            checkout, event_time=checkout.completed_at.timestamp(),
        )
        keys = sorted(k for k in event['user_data'] if k != 'country')
        if not meta_capi.has_match_keys(event['user_data']):
            self.stderr.write(
                f'{ref}: nothing Meta can match on - the buyer number '
                f'{checkout.buyer_phone!r} is unreadable and the row has no '
                'click-time browser data. Fix the number in the database first.'
            )
            return False

        summary = (f'{ref}: PKR {checkout.amount} on {checkout.completed_at:%Y-%m-%d}, '
                   f'match keys: {", ".join(keys)}')
        if dry_run:
            self.stdout.write(f'[dry-run] {summary}')
            return True
        if meta_capi.deliver(meta_capi.build_payload(event)):
            self.stdout.write(self.style.SUCCESS(f'Sent {summary}'))
            return True
        self.stderr.write(f'{ref}: Meta rejected it - see the log line above for the reason.')
        return False
