"""Stock-aware filter options for the game+category page.

The admin assigns a filter with every option a listing MAY carry (PSN gift
cards list 40-odd regions; Fazer sources most of them on demand). Buyers are
only offered the options at least one active listing on the page DOES carry:
a choice that can only answer "nothing in stock" is noise, the same way empty
sibling tabs and empty "shop by region" links are hidden. The /keys section
facets (views.facet_data) already work this way.

Nothing is deleted or rewritten: the FilterOption rows stay, and an option
reappears by itself the moment a listing with it comes back on. The sell form
asks for the full list with ?all_options=1 — a new listing may open a region
nothing carries yet.
"""

from .models import Listing


def stocked_filter_values(game_category):
    """{filter id (str): {option values}} carried by the page's active
    listings. One query: DISTINCT collapses the page's listings to their
    filter combinations (a few dozen at most), and the default ordering is
    cleared first — with it, Postgres would have to keep created_at in the
    DISTINCT and nothing would collapse."""
    stocked = {}
    combinations = (
        Listing.objects
        .filter(game_category=game_category, status='active')
        .order_by()
        .values_list('filter_values', flat=True)
        .distinct()
    )
    for filter_values in combinations:
        for filter_id, value in (filter_values or {}).items():
            if value in (None, ''):
                continue
            stocked.setdefault(str(filter_id), set()).add(str(value))
    return stocked


def trim_filters_to_stock(filters_payload, stocked, keep=None):
    """The serialized filters with every option no active listing carries
    dropped, and any filter left without options dropped with it (a dropdown
    that only says "All Region" is not a filter).

    `keep` = {filter id (str): value} the buyer already selected: that value
    stays listed even without stock, so the dropdown shows their choice over
    the empty state instead of a blank "All …" that looks unfiltered.
    """
    keep = keep or {}
    trimmed = []
    for filter_payload in filters_payload:
        filter_id = str(filter_payload['id'])
        allowed = stocked.get(filter_id, set())
        kept_value = keep.get(filter_id)
        options = [
            option for option in filter_payload['options']
            if option['value'] in allowed or option['value'] == kept_value
        ]
        if not options:
            continue
        trimmed.append({**filter_payload, 'options': options})
    return trimmed
