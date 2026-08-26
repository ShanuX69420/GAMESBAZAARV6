"""Timer-driven sender for post-purchase review-request emails.

Buyers of digital goods get their item in minutes and rarely come back to
review, so the shop asks them by email: a completed order earns one "How was
your order?" email with a no-login review link (the same /review/<token>
page WhatsApp sales use). The delay before asking depends on what was
bought — top-ups and gift cards are redeemed within minutes of delivery, so
they are asked the same day; accounts and keys need time to be logged into
or activated first, so they wait a full day.

Each order is emailed at most once (review_email_sent_at is stamped in the
same transaction that queues the email) and only while the purchase is
recent enough to still be fresh in the buyer's mind. A buyer is never
asked more than once per window either — top-up buyers often make several
purchases in a burst, and five identical emails at once reads as spam;
their other orders simply age out of the window unasked. Safe to run
every 15 minutes.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import Order, Review
from core.services import send_review_request_email


QUICK_DELAY = timedelta(hours=3)
DEFAULT_DELAY = timedelta(hours=24)
# Category slugs whose goods are consumed immediately after delivery.
# top-up/top-ups/subscription are all live spellings of the top-ups
# category (see HOME_POPULAR_SECTIONS in core/views.py).
QUICK_CATEGORY_SLUGS = {'top-up', 'top-ups', 'subscription', 'gift-cards', 'currency'}


def review_email_delay(order):
    """How long after completion this order's buyer should be asked."""
    listing = order.listing
    if listing is None:
        return DEFAULT_DELAY
    slug = listing.game_category.category.slug
    return QUICK_DELAY if slug in QUICK_CATEGORY_SLUGS else DEFAULT_DELAY


class Command(BaseCommand):
    help = (
        'Email buyers of recently completed orders a no-login review link. '
        'Each order is emailed at most once; safe to run every 15 minutes.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--batch-size', type=int, default=50,
                            help='Maximum emails to send per run.')
        parser.add_argument('--max-age-days', type=int, default=7,
                            help='Never email for orders completed longer ago than this.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report who would be emailed without sending.')

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        if batch_size < 1:
            raise CommandError('--batch-size must be at least 1')
        dry_run = options['dry_run']
        now = timezone.now()

        # SQL narrows to the quick delay (the earliest any order qualifies);
        # the per-category delay is applied per order below. Oldest first so
        # nothing starves behind orders still inside their settling window.
        candidates = list(
            Order.objects.filter(
                status='completed',
                review_email_sent_at__isnull=True,
                review__isnull=True,
                completed_at__gte=now - timedelta(days=options['max_age_days']),
                completed_at__lte=now - QUICK_DELAY,
            )
            .exclude(buyer__email='')
            .select_related('buyer', 'listing__game_category__category')
            .order_by('completed_at')[:500]
        )

        # One email per buyer per window, no matter how many orders qualify.
        already_asked = set(
            Order.objects.filter(
                review_email_sent_at__gte=now - timedelta(days=options['max_age_days']),
            ).values_list('buyer_id', flat=True)
        )

        sent = 0
        for order in candidates:
            if sent >= batch_size:
                break
            if order.buyer_id in already_asked:
                continue
            if order.completed_at > now - review_email_delay(order):
                continue
            if dry_run:
                self.stdout.write(
                    f'Would email {order.buyer.email} about order '
                    f'{order.order_number} ("{order.listing_title}")'
                )
                already_asked.add(order.buyer_id)
                sent += 1
                continue
            with transaction.atomic():
                locked = (
                    Order.objects.select_for_update()
                    .select_related('buyer')
                    .get(pk=order.pk)
                )
                if (
                    locked.status != 'completed'
                    or locked.review_email_sent_at is not None
                    or Review.objects.filter(order=locked).exists()
                ):
                    continue
                locked.ensure_review_token()
                locked.review_email_sent_at = timezone.now()
                locked.save(update_fields=[
                    'review_token', 'review_email_sent_at', 'updated_at',
                ])
                send_review_request_email(locked)  # queued after this commit
            already_asked.add(order.buyer_id)
            sent += 1

        if sent:
            label = 'Would email' if dry_run else 'Emailed'
            self.stdout.write(self.style.SUCCESS(
                f'{label} {sent} buyer(s) asking for a review.'
            ))
