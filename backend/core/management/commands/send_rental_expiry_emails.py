"""Timer-driven sender for "your rental ends soon" reminder emails.

A rental buyer gets two reminders: one when about three days remain and
one when about a day remains — enough notice to finish the game or rent
again before the login stops working. The end time is computed on the fly
(delivery time + the listing's Rental Period), so nothing about checkout or
delivery had to change and nothing is stored beyond the two "sent at"
stamps on the order.

Each stage is emailed at most once (the stamp is written in the same
transaction that queues the email). A rental first seen inside its last
24 hours gets only the 24-hour reminder — the 3-day one is skipped, never
sent late — and an already-ended rental gets nothing. Rentals extended by
hand are not tracked; the email says to ignore it if so. Safe to run every
hour: the whole scan is one indexed query over the last month's completed
rental orders.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import Order
from core.rentals import (
    MAX_RENTAL_DAYS, RENTAL_CATEGORY_SLUG, rental_expires_at,
    rental_period_days, rental_period_filter_ids,
)
from core.services import send_rental_expiry_email


STAGES = (
    # (stage, stamp field, due when remaining <= upper, but only while > lower)
    ('72h', 'rental_expiry_email_72h_sent_at', timedelta(hours=72), timedelta(hours=24)),
    ('24h', 'rental_expiry_email_24h_sent_at', timedelta(hours=24), timedelta(0)),
)


def due_stage(order, remaining):
    """Which reminder (if any) this rental is due for right now."""
    if remaining <= timedelta(0):
        return None
    for stage, field, upper, lower in STAGES:
        if lower < remaining <= upper and getattr(order, field) is None:
            return stage, field
    return None


class Command(BaseCommand):
    help = (
        'Email rental buyers ~72 h and ~24 h before their rental ends. '
        'Each reminder is sent at most once per order; safe to run hourly.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--batch-size', type=int, default=50,
                            help='Maximum emails to send per run.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report who would be emailed without sending.')

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        if batch_size < 1:
            raise CommandError('--batch-size must be at least 1')
        dry_run = options['dry_run']
        now = timezone.now()
        period_filter_ids = rental_period_filter_ids()

        # Only orders that can still be inside a reminder window: completed
        # (delivered) within the longest period sold, on the rentals
        # category, with at least one reminder unsent. Oldest first so the
        # rentals closest to ending go out before a batch cap bites.
        candidates = list(
            Order.objects.filter(
                status='completed',
                listing__game_category__category__slug=RENTAL_CATEGORY_SLUG,
                completed_at__gte=now - timedelta(days=MAX_RENTAL_DAYS + 1),
            )
            .filter(
                Q(rental_expiry_email_72h_sent_at__isnull=True)
                | Q(rental_expiry_email_24h_sent_at__isnull=True)
            )
            .exclude(buyer__email='')
            .select_related('buyer', 'listing__game_category__game',
                            'listing__game_category__category')
            .order_by('completed_at')[:500]
        )

        sent = 0
        for order in candidates:
            if sent >= batch_size:
                break
            days = rental_period_days(order.listing, order.listing_title, period_filter_ids)
            expires_at = rental_expires_at(order, days)
            if expires_at is None:
                continue
            due = due_stage(order, expires_at - now)
            if due is None:
                continue
            stage, field = due
            if dry_run:
                self.stdout.write(
                    f'Would email {order.buyer.email} ({stage} reminder) about '
                    f'order {order.order_number} ("{order.listing_title}"), '
                    f'ends {expires_at.isoformat(timespec="minutes")}'
                )
                sent += 1
                continue
            with transaction.atomic():
                locked = (
                    Order.objects.select_for_update(of=("self",))
                    .select_related('buyer', 'listing__game_category__game',
                                    'listing__game_category__category')
                    .get(pk=order.pk)
                )
                if locked.status != 'completed' or getattr(locked, field) is not None:
                    continue
                setattr(locked, field, timezone.now())
                locked.save(update_fields=[field, 'updated_at'])
                send_rental_expiry_email(
                    locked, expires_at=expires_at, days=days, stage=stage,
                )  # queued after this commit
            sent += 1

        if sent:
            label = 'Would email' if dry_run else 'Emailed'
            self.stdout.write(self.style.SUCCESS(
                f'{label} {sent} rental reminder(s).'
            ))
