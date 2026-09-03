"""Allow-listed region pages (/games/<game>/<category>/<region>).

A region page is the game+category page with its Region filter pinned to one
option value. The allow-list lives in CategoryRegionPage rows (seeded from
seo_copy.json entries that carry a "region" key); everything else here reads
the same Listing rows the brand page reads — a region page has stock exactly
when listings on the page carry that region in filter_values.

Shared by the browse API (brand page "shop by region" row + the region page
itself), the sitemap feed and IndexNow, so all three agree on which region
pages exist and which have stock.
"""

from django.db.models import Count, Q

from .models import CategoryRegionPage, Listing


def region_filter_for(game_category):
    """The page's Region filter (the assigned filter named "Region"), or None.
    Uses .all() so a view's prefetch cache is reused."""
    for assignment in game_category.assigned_filters.all():
        if assignment.filter.name.strip().lower() == 'region':
            return assignment.filter
    return None


def region_option_labels(region_filter):
    """{option value: label} for the Region filter, e.g. {'usa': 'USA'}."""
    if region_filter is None:
        return {}
    return {opt.value: opt.label for opt in region_filter.options.all()}


def region_listing_filter(filter_id, region):
    return Q(filter_values__contains={str(filter_id): region})


def active_region_listings(game_category, filter_id, region):
    return Listing.objects.filter(
        region_listing_filter(filter_id, region),
        game_category=game_category,
        status='active',
    )


def region_pages_payload(game_category, region_filter, rows=None):
    """The page's allow-listed regions with live stock counts, in display
    order. A row whose region is no longer an option on the Region filter is
    left out — without an option it has no label, and no listing can be
    filtered to it, so the page effectively no longer exists.

    One aggregate query for every region on the page.
    """
    if region_filter is None:
        return []
    rows = list(game_category.region_pages.all() if rows is None else rows)
    labels = region_option_labels(region_filter)
    rows = [row for row in rows if row.region in labels]
    if not rows:
        return []

    filter_id = str(region_filter.id)
    counts = Listing.objects.filter(
        game_category=game_category, status='active',
    ).aggregate(**{
        f'region_{index}': Count(
            'pk', filter=region_listing_filter(filter_id, row.region))
        for index, row in enumerate(rows)
    })
    brand_path = f'/games/{game_category.game.slug}/{game_category.effective_slug}'
    return [
        {
            'region': row.region,
            'label': labels[row.region],
            'path': f'{brand_path}/{row.region}',
            'listing_count': counts[f'region_{index}'],
        }
        for index, row in enumerate(rows)
    ]


def all_region_pages_payload():
    """Every allow-listed region page on an active game, with stock counts,
    plus the slugs the sitemap needs. Ordered by game, page, display order."""
    rows = (CategoryRegionPage.objects
            .filter(game_category__game__is_active=True)
            .select_related('game_category__game', 'game_category__category')
            .prefetch_related('game_category__assigned_filters__filter__options')
            .order_by('game_category__game__slug', 'game_category__order',
                      'game_category_id', 'order', 'region'))
    by_page = {}
    for row in rows:
        by_page.setdefault(row.game_category_id, (row.game_category, []))[1].append(row)

    payload = []
    for game_category, page_rows in by_page.values():
        region_filter = region_filter_for(game_category)
        for entry in region_pages_payload(game_category, region_filter, page_rows):
            payload.append({
                'game_slug': game_category.game.slug,
                'category_slug': game_category.effective_slug,
                **entry,
            })
    return payload


def stocked_region_page_paths():
    """Site paths of the region pages the sitemap lists (allow-listed, active
    game, at least one active listing in that region)."""
    return [
        entry['path'] for entry in all_region_pages_payload()
        if entry['listing_count'] > 0
    ]
