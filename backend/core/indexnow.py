"""IndexNow client: tells Bing (and every other IndexNow search engine) which
pages of the site changed, so they are re-crawled within hours instead of
whenever the sitemap is next read.

Why it exists: ChatGPT's web search reads Bing's index, and ChatGPT is the
shop's biggest buyer channel. Bing's crawl budget for a young site is small,
so we push the URLs that actually changed — new listings, price moves,
stock-outs, retired pages — instead of waiting for it to notice.

How it works: the site proves it owns the key by serving it as a text file at
/<key>.txt (frontend/public/). One POST carries up to 10,000 URLs; a 200 or
202 reply means the batch was accepted and shared with every engine in the
protocol. The key is public by design (the file is world-readable) but still
lives in the backend .env so it is configured in one place — leave it unset
and everything here is a no-op.

Change detection rides on Listing.updated_at. Anything that saves a listing
through the ORM stamps it; the daily price/stock syncs in tools/ stamp it by
hand on the rows they bulk-update (bulk_update/update skip auto_now). A
changed listing affects two public pages: its own /listing/<id> page and its
game+category page. The last successful ping time is kept in PlatformSetting,
so a restart or redeploy never loses the cursor.
"""

import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.utils import timezone

from .models import CategoryRegionPage, GameCategory, Listing, PlatformSetting
from .region_pages import region_filter_for, region_option_labels, stocked_region_page_paths
from .services import set_platform_setting

logger = logging.getLogger(__name__)

INDEXNOW_ENDPOINT = 'https://api.indexnow.org/indexnow'
# Protocol maximum per POST.
MAX_URLS_PER_REQUEST = 10000
# Same explicit UA rule as jazzcash.py — some edges drop python-requests' default.
USER_AGENT = 'GamesBazaar/1.0'
TIMEOUT_SECONDS = 30
LAST_PING_SETTING_KEY = 'indexnow_last_ping_at'
# First ever run (or a lost cursor) looks back this far.
DEFAULT_LOOKBACK = timedelta(hours=24)


class IndexNowError(Exception):
    """IndexNow did not accept a batch (network error or non-2xx reply)."""


def is_enabled():
    return bool(settings.INDEXNOW_KEY)


def site_url():
    return settings.PUBLIC_SITE_URL.rstrip('/')


def site_host():
    return urlsplit(site_url()).netloc


def key_location():
    return f'{site_url()}/{settings.INDEXNOW_KEY}.txt'


def absolute_url(path):
    """Turn a site path (or an already absolute URL) into the canonical URL —
    no trailing slash, matching the sitemap and the pages' canonical tags."""
    value = str(path or '/').strip()
    if value.startswith(('http://', 'https://')):
        return value
    if not value.startswith('/'):
        value = '/' + value
    value = value.rstrip('/')
    return site_url() + value


def listing_url(listing_id):
    return f'{site_url()}/listing/{listing_id}'


def category_page_url(game_category):
    return f'{site_url()}/games/{game_category.game.slug}/{game_category.effective_slug}'


def region_page_url(region_page):
    return f'{site_url()}{region_page.path}'


def changed_region_page_urls(changed_rows):
    """Region pages touched by changed listings: a listing whose Region value
    matches an allow-listed region page changes that page too (its stock,
    tiles and the from-price in its title). `changed_rows` is an iterable of
    (game_category_id, filter_values) pairs."""
    by_category = {}
    for game_category_id, filter_values in changed_rows:
        by_category.setdefault(game_category_id, []).append(filter_values or {})
    if not by_category:
        return []

    region_rows = (CategoryRegionPage.objects
                   .filter(game_category_id__in=by_category)
                   .select_related('game_category__game', 'game_category__category')
                   .prefetch_related('game_category__assigned_filters__filter__options')
                   .order_by('game_category__game__slug', 'game_category_id', 'order', 'region'))
    urls = []
    seen_filters = {}
    for row in region_rows:
        game_category = row.game_category
        if game_category.pk not in seen_filters:
            seen_filters[game_category.pk] = region_filter_for(game_category)
        region_filter = seen_filters[game_category.pk]
        if region_filter is None or row.region not in region_option_labels(region_filter):
            continue
        key = str(region_filter.id)
        if any(values.get(key) == row.region for values in by_category[game_category.pk]):
            urls.append(region_page_url(row))
    return urls


def last_ping_at():
    value = (PlatformSetting.objects
             .filter(key=LAST_PING_SETTING_KEY)
             .values_list('value', flat=True)
             .first())
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


def changed_pages_since(since):
    """Public URLs affected by listings updated at or after `since`.

    Returns (category_urls, listing_urls). Category pages come first because
    they are the pages that rank; if a batch ever has to be cut, cut listings.
    Listings of hidden (inactive) games are skipped — their pages are noindexed.
    """
    rows = (Listing.objects
            .filter(updated_at__gte=since, game_category__game__is_active=True)
            .order_by('pk')
            .values_list('pk', 'game_category_id', 'filter_values'))
    listing_ids = []
    category_ids = set()
    changed_rows = []
    for pk, game_category_id, filter_values in rows:
        listing_ids.append(pk)
        category_ids.add(game_category_id)
        changed_rows.append((game_category_id, filter_values))

    categories = (GameCategory.objects
                  .filter(pk__in=category_ids)
                  .select_related('game', 'category')
                  .order_by('game__slug', 'order', 'pk'))
    category_urls = [category_page_url(gc) for gc in categories]
    # Region pages count as category pages: they rank (or should), and a
    # changed listing moves their stock and title just like the brand page's.
    category_urls += changed_region_page_urls(changed_rows)
    return (
        category_urls,
        [listing_url(pk) for pk in listing_ids],
    )


def indexable_category_page_urls():
    """Every game+category page the sitemap lists: active game, live stock —
    plus the allow-listed region pages that have stock."""
    categories = (GameCategory.objects
                  .filter(game__is_active=True, listings__status='active')
                  .distinct()
                  .select_related('game', 'category')
                  .order_by('game__slug', 'order', 'pk'))
    urls = [category_page_url(gc) for gc in categories]
    urls += [absolute_url(path) for path in stocked_region_page_paths()]
    return urls


def _chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def submit(urls):
    """Send URLs to IndexNow. Returns the list actually sent (deduplicated,
    same-host only). Raises IndexNowError if any batch is refused — callers
    must then NOT advance their change cursor, so the batch is retried."""
    if not is_enabled():
        raise IndexNowError('INDEXNOW_KEY is not set.')

    host = site_host()
    accepted = []
    seen = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        if urlsplit(url).netloc != host:
            logger.warning('IndexNow: skipping %s (not on %s)', url, host)
            continue
        accepted.append(url)

    for batch in _chunks(accepted, MAX_URLS_PER_REQUEST):
        _post(batch, host)
    return accepted


def _post(batch, host):
    payload = {
        'host': host,
        'key': settings.INDEXNOW_KEY,
        'keyLocation': key_location(),
        'urlList': batch,
    }
    try:
        response = requests.post(
            INDEXNOW_ENDPOINT,
            json=payload,
            headers={
                'Content-Type': 'application/json; charset=utf-8',
                'User-Agent': USER_AGENT,
            },
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise IndexNowError(f'IndexNow request failed: {exc}') from exc

    if response.status_code not in (200, 202):
        raise IndexNowError(
            f'IndexNow refused {len(batch)} URL(s): HTTP {response.status_code} '
            f'{response.text[:200]!r}'
        )
    logger.info('IndexNow accepted %d URL(s) (HTTP %s)', len(batch), response.status_code)


def ping_changes(since=None, dry_run=False):
    """Submit every page changed since the last successful ping (or `since`).

    Returns (since, category_urls, listing_urls). The cursor moves to the
    start of this run only after IndexNow accepts the batch, so a failed ping
    is retried in full next time. Nothing is sent when nothing changed, but
    the cursor still advances.
    """
    started_at = timezone.now()
    if since is None:
        since = last_ping_at() or (started_at - DEFAULT_LOOKBACK)

    category_urls, listing_urls = changed_pages_since(since)
    if dry_run:
        return since, category_urls, listing_urls

    urls = category_urls + listing_urls
    if urls:
        submit(urls)
    set_platform_setting(LAST_PING_SETTING_KEY, started_at.isoformat())
    return since, category_urls, listing_urls
