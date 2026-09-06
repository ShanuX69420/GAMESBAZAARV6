"""Warm the frontend's page cache after a build.

`npm run build` throws away every incrementally rendered page, so the first
visitor to each game+category page pays the whole server render — about 0.6 s
measured on production, against about 0.09 s once that page is cached. This
command asks for every page that has stock, once, so the cache is already hot
when the first visitor arrives.

Run it AFTER `npm run build` and the `gamesbazaar-frontend` restart — see
"Warm the page cache" in `GamesBazaar_Deployment_Runbook.md`. It talks straight
to the Next server on 127.0.0.1:3000 (nginx caches `/api/` and `/_next/image`,
never page HTML) and sends the public Host header, so what gets cached is
byte-for-byte what a visitor would have rendered.

Only the two dynamic routes need warming: `/games/<game>/<category>` and
`/games/<game>/<category>/<region>`, which declare `generateStaticParams()`
returning `[]`. The section pages (/keys, /accounts, ...) and /games take no
route params, so `npm run build` prerenders them itself and they are already
warm when the server starts. /listing/<id> still renders per request, so
asking for those here would only burn CPU.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import requests
from django.core.management.base import BaseCommand, CommandError

from core import indexnow

# The Next server itself: no TLS, no nginx, no public bandwidth.
DEFAULT_BASE = 'http://127.0.0.1:3000'
# The box has 1 vCPU. Three in flight keeps Node busy while the other two wait
# on Django without starving the visitors browsing at the same time.
DEFAULT_CONCURRENCY = 3
DEFAULT_TIMEOUT = 30
# Same explicit-UA rule as jazzcash.py/indexnow.py, and it names itself in logs.
USER_AGENT = 'GamesBazaar-CacheWarmer/1.0'
MAX_PROBLEMS_LISTED = 20
SLOWEST_LISTED = 5


def warmable_paths():
    """Site paths of every page worth warming: exactly the set the sitemap
    lists — a game+category page on an active game with at least one active
    listing, plus the allow-listed region pages that have stock.

    Shared with IndexNow on purpose: one definition of "a page that has stock"
    keeps the sitemap, the search-engine push and the warmer from drifting
    apart.
    """
    site = indexnow.site_url()
    paths = []
    for url in indexnow.indexable_category_page_urls():
        path = url[len(site):] if url.startswith(site) else urlsplit(url).path
        paths.append(path or '/')
    return list(dict.fromkeys(paths))


def percentile(sorted_values, fraction):
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(fraction * len(sorted_values)))
    return sorted_values[index]


class Command(BaseCommand):
    help = (
        'Request every stocked game+category and region page once so the '
        'frontend page cache is warm. Run after npm run build + restart.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--base', default=DEFAULT_BASE,
                            help=f'Frontend origin to request (default {DEFAULT_BASE}).')
        parser.add_argument('--host', default=None,
                            help='Host header to send (default: the host of PUBLIC_SITE_URL).')
        parser.add_argument('--concurrency', type=int, default=DEFAULT_CONCURRENCY,
                            help=f'Requests in flight (default {DEFAULT_CONCURRENCY}).')
        parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT,
                            help=f'Per-request timeout in seconds (default {DEFAULT_TIMEOUT}).')
        parser.add_argument('--limit', type=int, default=None,
                            help='Warm only the first N pages (for a quick check).')
        parser.add_argument('--paths', nargs='+', metavar='PATH',
                            help='Warm these site paths instead of every stocked page.')
        parser.add_argument('--dry-run', action='store_true',
                            help='List the pages that would be warmed, request nothing.')

    def handle(self, *args, **options):
        base = options['base'].rstrip('/')
        host = options['host'] or urlsplit(indexnow.site_url()).netloc
        concurrency = max(1, options['concurrency'])

        paths = options['paths'] or warmable_paths()
        paths = [path if path.startswith('/') else '/' + path for path in paths]
        if options['limit'] is not None:
            paths = paths[:options['limit']]

        if not paths:
            self.stdout.write('Nothing to warm: no page has stock.')
            return

        if options['dry_run']:
            self.stdout.write(f'Dry run: would warm {len(paths)} page(s) at {base} (Host: {host}):')
            for path in paths[:MAX_PROBLEMS_LISTED]:
                self.stdout.write(f'  {path}')
            if len(paths) > MAX_PROBLEMS_LISTED:
                self.stdout.write(f'  ... and {len(paths) - MAX_PROBLEMS_LISTED} more')
            return

        self.stdout.write(
            f'Warming {len(paths)} page(s) at {base} (Host: {host}, '
            f'{concurrency} at a time)...'
        )
        started = time.monotonic()
        results = self.warm(base, host, paths, concurrency, options['timeout'])
        self.report(results, time.monotonic() - started)

    def warm(self, base, host, paths, concurrency, timeout):
        headers = {
            'Host': host,
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml',
        }

        # One session per worker thread: requests' Session is not thread-safe,
        # and each one then keeps its own keep-alive connection to Next.
        local = threading.local()
        sessions = []

        def fetch(path):
            session = getattr(local, 'session', None)
            if session is None:
                session = local.session = requests.Session()
                sessions.append(session)
            start = time.monotonic()
            try:
                # Redirects are NOT followed: every path here comes from the
                # database, so a redirect means the list is out of step with
                # the routes and is worth seeing rather than papering over.
                # The body must be read in full — Next only stores the cache
                # entry once the render has finished streaming.
                response = session.get(base + path, headers=headers,
                                       timeout=timeout, allow_redirects=False)
                length = len(response.content)
            except requests.RequestException as exc:
                return {'path': path, 'status': None, 'cache': None,
                        'seconds': time.monotonic() - start, 'bytes': 0,
                        'error': str(exc)}
            return {
                'path': path,
                'status': response.status_code,
                'cache': (response.headers.get('x-nextjs-cache') or '').upper() or None,
                'seconds': time.monotonic() - start,
                'bytes': length,
                'error': None,
            }

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(fetch, paths))
        for session in sessions:
            session.close()
        return results

    def report(self, results, elapsed):
        # Classify by status FIRST: Next serves its not-found page from the
        # cache too, so a 404 comes back with `x-nextjs-cache: HIT` and would
        # otherwise be reported as a warm page as well as a failure.
        served = [r for r in results
                  if r['error'] is None and 200 <= (r['status'] or 0) < 300]
        rendered = [r for r in served if r['cache'] == 'MISS']
        already_warm = [r for r in served if r['cache'] in ('HIT', 'STALE')]
        uncacheable = [r for r in served if r['cache'] is None]
        redirects = [r for r in results
                     if r['error'] is None and r['status'] and 300 <= r['status'] < 400]
        failures = [r for r in results
                    if r['error'] is not None or (r['status'] or 0) >= 400]
        succeeded = len(served)

        self.stdout.write('')
        self.stdout.write(f'Warmed {succeeded}/{len(results)} page(s) in {elapsed:.0f}s '
                          f'({elapsed / max(1, len(results)):.2f}s each).')
        self.stdout.write(f'  rendered now (MISS):   {len(rendered)}')
        self.stdout.write(f'  already warm (HIT):    {len(already_warm)}')
        if uncacheable:
            self.stdout.write(self.style.WARNING(
                f'  served but NOT cached:  {len(uncacheable)} '
                '(route is still dynamic — warming it does nothing)'))
        if redirects:
            self.stdout.write(self.style.WARNING(f'  redirected:            {len(redirects)}'))
        if failures:
            self.stdout.write(self.style.ERROR(f'  failed:                {len(failures)}'))

        timings = sorted(r['seconds'] for r in results if r['error'] is None)
        if timings:
            self.stdout.write(
                f'  render time: p50 {percentile(timings, 0.5):.2f}s  '
                f'p90 {percentile(timings, 0.9):.2f}s  max {timings[-1]:.2f}s'
            )
            slowest = sorted((r for r in results if r['error'] is None),
                             key=lambda r: r['seconds'], reverse=True)[:SLOWEST_LISTED]
            for result in slowest:
                self.stdout.write(f'    {result["seconds"]:6.2f}s  {result["path"]}')

        for result in (redirects + failures)[:MAX_PROBLEMS_LISTED]:
            detail = result['error'] or f'HTTP {result["status"]}'
            self.stdout.write(f'  {result["path"]}: {detail}')
        extra = len(redirects) + len(failures) - MAX_PROBLEMS_LISTED
        if extra > 0:
            self.stdout.write(f'  ... and {extra} more')

        if succeeded == 0:
            # Every single request failed: the frontend is down or the wrong
            # --base was given. A deploy should stop and look.
            raise CommandError('Nothing could be warmed — is gamesbazaar-frontend running?')
