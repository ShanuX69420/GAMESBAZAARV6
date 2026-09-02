"""Listing lifecycle: what a listing's URL does once the listing stops selling.

Before 2026-09-02 an inactive listing 404'd the moment a price sync switched
it off, and a deleted one vanished without a trace — 229 inactive pages and
1,400+ deleted ones were throwing away their search history (SEO fix #1,
marketing/seo/seo-fix-plan.md). Every listing URL now lands in one of four
states, decided per request:

  active     — the normal page.
  paused     — switched off recently with no permanent reason: the page keeps
               its URL, title and Product schema (availability OutOfStock),
               loses the buy button, shows the sibling options, and stays out
               of the sitemap. Lasts at most PAUSE_DAYS.
  gone       — off for good (a retire_reason, an active twin exists, or the
               pause ran out) or deleted: 308 to the heir.
  unindexed  — was buyable for under a day, so no search engine ever saw it:
               plain 404 (Shayan 2026-09-02: never show something permanently
               gone as "out of stock", and don't redirect ghosts).

The heir is the closest live page: the active twin (same game + category +
option, or the same title for standard listings), else the category page,
else the game's busiest page, else the section page.

Shayan's rule of thumb from the same review: many inactive listings are
PERMANENTLY gone (supplier renames seed a twin, editions get discontinued),
so anything that knows it is permanent must say so through retire_reason.
"""

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from .models import Game, GameCategory, Listing, RetiredListing

# How long an out-of-stock page keeps serving before it redirects.
PAUSE_DAYS = 30
# Listings buyable for less than this were never crawled: 404, not redirect.
# One day, not a week — the GSC export shows listings that were live for
# three days ranking on page one ("330 Minecoins", 18 impressions).
NEVER_INDEXED_MAX_ACTIVE = timedelta(days=1)

# Base category slug -> the section page that lists every game in it.
SECTION_BY_CATEGORY = {
    'keys': '/keys',
    'accounts': '/accounts',
    'gift-cards': '/gift-cards',
    'currency': '/gift-cards',
    'rentals': '/rentals',
    'subscriptions': '/subscriptions',
    'top-ups': '/subscriptions',
}

_STATE_ACTIVE = {'state': 'active'}


def listing_path(listing_id):
    return f'/listing/{listing_id}'


def category_path(game_slug, category_slug):
    return f'/games/{game_slug}/{category_slug}'


def section_path(category_kind):
    return SECTION_BY_CATEGORY.get(category_kind, '/')


def _gone(reason, redirect_to):
    return {'state': 'gone', 'reason': reason, 'redirect_to': redirect_to}


def _unindexed(reason):
    return {'state': 'unindexed', 'reason': reason or 'never_indexed', 'redirect_to': None}


def find_active_twin(game_category, *, option_id=None, title='', exclude_id=None):
    """The active listing that sells the same thing on the same page.

    Offer-mode listings are twins when they share the option; standard ones
    when the title matches (it carries game, edition, method and region).
    Cheapest first, so a redirect lands on the best price.
    """
    if game_category is None:
        return None
    qs = Listing.objects.filter(game_category=game_category, status='active')
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    if option_id is not None:
        qs = qs.filter(option_id=option_id)
    else:
        cleaned = ' '.join(str(title or '').split())
        if not cleaned:
            return None
        qs = qs.filter(title__iexact=cleaned)
    return qs.order_by('price', 'pk').first()


def _category_has_stock(game_category):
    return Listing.objects.filter(game_category=game_category, status='active').exists()


def busiest_page(game):
    """The game's category page with the most active listings, if any."""
    if game is None:
        return None
    return (
        GameCategory.objects.filter(game=game)
        .annotate(live=Count('listings', filter=Q(listings__status='active')))
        .filter(live__gt=0)
        .select_related('category')
        .order_by('-live', 'order', 'pk')
        .first()
    )


def resolve_heir(*, game_slug, category_slug, category_kind='', option_id=None,
                 title='', exclude_id=None, game_category=None):
    """Closest live page for a listing that is (or is about to be) gone."""
    gc = game_category
    if gc is None and game_slug and category_slug:
        gc = GameCategory.resolve_for_slug(
            game_slug, category_slug,
            queryset=GameCategory.objects.select_related('game', 'category'),
        )
    if gc is not None and not gc.game.is_active:
        gc = None

    if gc is not None:
        twin = find_active_twin(gc, option_id=option_id, title=title, exclude_id=exclude_id)
        if twin is not None:
            return listing_path(twin.pk)
        if _category_has_stock(gc):
            return category_path(gc.game.slug, gc.effective_slug)
        category_kind = category_kind or gc.category.slug
        game = gc.game
    else:
        game = Game.objects.filter(slug=game_slug, is_active=True).first() if game_slug else None

    page = busiest_page(game)
    if page is not None:
        return category_path(game.slug, page.effective_slug)
    return section_path(category_kind)


def lifecycle_for_listing(listing, now=None):
    """State of a listing row that still exists. Never writes."""
    if listing.status == 'active':
        return dict(_STATE_ACTIVE)

    now = now or timezone.now()
    since = listing.unavailable_since or now
    if since - listing.created_at < NEVER_INDEXED_MAX_ACTIVE:
        return _unindexed(listing.retire_reason)

    gc = listing.game_category
    heir_kwargs = dict(
        game_slug=gc.game.slug, category_slug=gc.effective_slug,
        category_kind=gc.category.slug, option_id=listing.option_id,
        title=listing.title, exclude_id=listing.pk,
        game_category=gc if gc.game.is_active else None,
    )
    twin = find_active_twin(gc, option_id=listing.option_id, title=listing.title,
                            exclude_id=listing.pk) if gc.game.is_active else None
    if twin is not None:
        return _gone('superseded', listing_path(twin.pk))
    if listing.retire_reason:
        return _gone(listing.retire_reason, resolve_heir(**heir_kwargs))
    if now - since >= timedelta(days=PAUSE_DAYS):
        return _gone('expired', resolve_heir(**heir_kwargs))

    return {
        'state': 'paused',
        'reason': '',
        'redirect_to': None,
        'unavailable_since': since.isoformat(),
        'pause_ends_at': (since + timedelta(days=PAUSE_DAYS)).isoformat(),
        # Where "browse the rest" points: the category page while it has
        # stock, otherwise the same fallback chain the redirect would use.
        'browse_path': resolve_heir(**heir_kwargs),
    }


def lifecycle_for_retired(record, now=None):
    """State of a listing that was deleted (a RetiredListing record)."""
    if (
        record.listing_created_at is not None
        and record.active_until is not None
        and record.active_until - record.listing_created_at < NEVER_INDEXED_MAX_ACTIVE
    ):
        return _unindexed(record.reason)
    heir = record.heir_path or resolve_heir(
        game_slug=record.game_slug, category_slug=record.category_slug,
        category_kind=record.category_kind, option_id=record.option_id,
        title=record.title, exclude_id=record.listing_id,
    )
    return _gone(record.reason, heir)


def alternatives(listing, limit=8):
    """Sibling options shown on a paused page: the other active listings on
    the same category page — one per option in offer mode (cheapest offer,
    tile order), cheapest first otherwise."""
    qs = (
        Listing.objects.filter(game_category=listing.game_category, status='active')
        .exclude(pk=listing.pk)
    )
    if listing.game_category.listing_mode == 'offer':
        from .views import option_display_key  # lazy: views imports this module

        best_by_option = {}
        for row in qs.select_related('option').order_by('price', 'pk'):
            if row.option_id is None or row.option_id in best_by_option:
                continue
            best_by_option[row.option_id] = row
        rows = sorted(best_by_option.values(),
                      key=lambda row: option_display_key(row.option))
    else:
        rows = list(qs.order_by('price', 'pk')[:limit])
    return [
        {
            'id': row.pk,
            'title': row.title,
            'price': str(row.price),
            'option_name': row.option.name if row.option_id else None,
        }
        for row in rows[:limit]
    ]


def stamp_unavailable(listing, now=None):
    """First sighting of an off listing nobody stamped (bulk updates skip
    save()): start its clock now. Conditional so two requests can't disagree."""
    now = now or timezone.now()
    updated = Listing.objects.filter(
        pk=listing.pk, unavailable_since__isnull=True,
    ).exclude(status='active').update(unavailable_since=now)
    if updated:
        listing.unavailable_since = now
    return bool(updated)


def clear_stale_stamp(listing):
    """An active listing still carrying a stamp was revived by a bulk update
    that forgot to clear it; without this its next pause would look expired."""
    Listing.objects.filter(pk=listing.pk, status='active').update(
        unavailable_since=None, retire_reason='',
    )
    listing.unavailable_since = None
    listing.retire_reason = ''


def snapshot_retirement(listing, reason='deleted', heir_path='', now=None):
    """Leave a RetiredListing record for a listing about to be deleted."""
    now = now or timezone.now()
    gc = listing.game_category
    if listing.status == 'active':
        active_until = now
    else:
        active_until = listing.unavailable_since or listing.updated_at or now
    record, _created = RetiredListing.objects.update_or_create(
        listing_id=listing.pk,
        defaults={
            'title': listing.title,
            'game_slug': gc.game.slug,
            'category_slug': gc.effective_slug,
            'category_kind': gc.category.slug,
            'option_id': listing.option_id,
            'filter_values': listing.filter_values or {},
            'heir_path': heir_path,
            'reason': listing.retire_reason or reason,
            'listing_created_at': listing.created_at,
            'active_until': active_until,
            'retired_at': now,
        },
    )
    return record


def gone_payload(listing_id, lifecycle):
    """API body for a listing that no longer has a page. Deliberately a 200:
    the frontend's fetch cache never replaces a cached 200 with a 404, so a
    non-200 here would leave the OLD listing page served forever (landmine
    memory gamesbazaar-next-fetch-cache-stale-404)."""
    return {'id': listing_id, 'status': 'retired', 'lifecycle': lifecycle}
