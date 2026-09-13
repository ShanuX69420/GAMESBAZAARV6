"""Rental orders: when a rental starts, how long it runs, when it ends.

A rental is a listing on the 'rentals' category (PlayStation account access
for a fixed period). The period lives on the listing as its "Rental Period"
filter value ('7-days' ... '30-days'); the order's own title snapshot
("Elden Ring (PS4/PS5) — Rent 7 Days") is the fallback for listings whose
filter values were lost or hand-edited. The clock starts when the login is
handed over — delivered_at, which the shop flow stamps in the same
transaction that completes the order.
"""

import re
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db.models import Q

RENTAL_CATEGORY_SLUG = 'rentals'
RENTAL_PERIOD_FILTER_LABEL = 'Rental Period'
# Longest period the catalog sells; bounds how far back the timer looks.
MAX_RENTAL_DAYS = 30

PAKISTAN_TZ = ZoneInfo('Asia/Karachi')

_VALUE_DAYS_RE = re.compile(r'^(\d+)-days?$', re.I)
_TITLE_DAYS_RE = re.compile(r'\bRent\s+(\d+)\s*Days?\b', re.I)


def rental_period_filter_ids():
    """IDs of the shared "Rental Period" filter (usually exactly one)."""
    from .models import Filter
    return set(
        Filter.objects.filter(
            Q(admin_label=RENTAL_PERIOD_FILTER_LABEL) | Q(name=RENTAL_PERIOD_FILTER_LABEL)
        ).values_list('id', flat=True)
    )


def rental_period_days(listing, title='', period_filter_ids=None):
    """Rental length in days for a listing, or None if it cannot be told.

    Prefers the Rental Period filter value; then any 'N-days' filter value;
    then "Rent N Days" in the title (the order's snapshot title is passed so
    a renamed listing still resolves).
    """
    values = (getattr(listing, 'filter_values', None) or {}) if listing else {}
    if period_filter_ids:
        for fid in period_filter_ids:
            match = _VALUE_DAYS_RE.match(str(values.get(str(fid), '') or ''))
            if match:
                return int(match.group(1))
    for value in values.values():
        match = _VALUE_DAYS_RE.match(str(value or ''))
        if match:
            return int(match.group(1))
    for text in (title, getattr(listing, 'title', '') if listing else ''):
        match = _TITLE_DAYS_RE.search(text or '')
        if match:
            return int(match.group(1))
    return None


def rental_started_at(order):
    """When the buyer received the login — the moment the rental clock starts."""
    return order.delivered_at or order.completed_at


def rental_expires_at(order, days):
    started = rental_started_at(order)
    if started is None or not days:
        return None
    return started + timedelta(days=days)


def format_pakistan_time(moment):
    """'Tue 16 Sep 2026, 9:30 PM PKT' — the buyer's clock, not the server's."""
    local = moment.astimezone(PAKISTAN_TZ)
    hour = local.hour % 12 or 12
    return f'{local:%a %d %b %Y}, {hour}:{local:%M} {local:%p} PKT'
