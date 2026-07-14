"""Send a test Purchase event to Meta's Conversions API.

Verifies the pixel ID + access token wiring end-to-end without touching a
real order. Requires a test event code (Events Manager → Test Events tab)
so the event can never land in the production dataset:

    python manage.py meta_capi_smoke --test-event-code TEST12345

The event should appear in the Test Events tab within seconds, marked
"Server". Deduplication note: the event uses a one-off event ID, so it
never collides with real purchases.
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core import meta_capi


class Command(BaseCommand):
    help = "Send a test Purchase event to Meta's Conversions API (Test Events tab only)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--test-event-code',
            default='',
            help='Code from Events Manager → Test Events. Falls back to '
                 'META_CAPI_TEST_EVENT_CODE; required one way or the other.',
        )

    def handle(self, *args, **options):
        if not meta_capi.is_configured():
            raise CommandError(
                'META_PIXEL_ID and META_CAPI_ACCESS_TOKEN must both be set.'
            )
        test_event_code = (
            options['test_event_code'].strip()
            or settings.META_CAPI_TEST_EVENT_CODE
        )
        if not test_event_code:
            raise CommandError(
                'Refusing to send without a test event code — a smoke event '
                'must never land in the production dataset. Get one from '
                'Events Manager → Test Events and pass --test-event-code.'
            )

        now = int(time.time())
        payload = {
            'data': [{
                'event_name': 'Purchase',
                'event_time': now,
                'event_id': f'capi-smoke-{now}',
                'action_source': 'website',
                'event_source_url': settings.PUBLIC_SITE_URL,
                'user_data': {
                    'em': [meta_capi._sha256('capi-smoke@gamesbazaar.pk')],
                    'client_ip_address': '39.50.0.1',
                    'client_user_agent': 'GamesBazaar-CAPI-Smoke/1.0',
                },
                'custom_data': {'currency': 'PKR', 'value': 1.0},
            }],
            'access_token': settings.META_CAPI_ACCESS_TOKEN,
            'test_event_code': test_event_code,
        }

        if meta_capi.deliver(payload):
            # ASCII only: Windows consoles choke on fancy arrows/dashes.
            self.stdout.write(self.style.SUCCESS(
                f'Sent capi-smoke-{now} - check Events Manager > Test Events '
                f'(pixel {settings.META_PIXEL_ID}).'
            ))
        else:
            raise CommandError(
                'Delivery failed — see the log line above for Meta\'s response.'
            )
