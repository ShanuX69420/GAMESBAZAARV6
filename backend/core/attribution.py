"""First-touch acquisition attribution.

The frontend stashes the first visit's referrer + landing page in
localStorage (lib/attribution.js) and sends it when an account gets
created — email register, Google sign-in, or guest checkout. This module
turns that raw pair into a stable source label and writes it onto the
UserProfile exactly once. Orders snapshot the label at purchase time so
the admin list answers "where did this sale come from?" without joins.

Everything here is best-effort: attribution must never break a signup,
so bad payloads are dropped, never raised.
"""

import datetime as _datetime
from urllib.parse import parse_qs, urlsplit

from django.utils import timezone
from django.utils.dateparse import parse_datetime

MAX_URL_LENGTH = 500
MAX_SOURCE_LENGTH = 32

# utm_source values seen in the wild → our label. Unrecognized values are
# kept as-is (sanitized) — a future campaign tag shouldn't need a deploy.
UTM_SOURCE_LABELS = {
    'chatgpt.com': 'chatgpt',
    'chatgpt': 'chatgpt',
    'google': 'google',
    'facebook': 'facebook',
    'instagram': 'instagram',
    'ig': 'instagram',
    'tiktok': 'tiktok',
    'youtube': 'youtube',
    'twitter': 'twitter',
    'x': 'twitter',
    'whatsapp': 'whatsapp',
}

# Referrer host → label. Checked in order; first suffix match wins, so the
# specific Google properties must come before the generic google catch-all.
REFERRER_HOST_LABELS = [
    ('gemini.google.com', 'gemini'),
    ('googleadservices.com', 'google-ads'),
    ('google.', 'google'),
    ('bing.com', 'bing'),
    ('duckduckgo.com', 'duckduckgo'),
    ('search.yahoo.com', 'yahoo'),
    ('chatgpt.com', 'chatgpt'),
    ('chat.openai.com', 'chatgpt'),
    ('perplexity.ai', 'perplexity'),
    ('copilot.microsoft.com', 'copilot'),
    ('facebook.com', 'facebook'),
    ('fb.me', 'facebook'),
    ('fb.watch', 'facebook'),
    ('messenger.com', 'facebook'),
    ('instagram.com', 'instagram'),
    ('tiktok.com', 'tiktok'),
    ('youtube.com', 'youtube'),
    ('youtu.be', 'youtube'),
    ('twitter.com', 'twitter'),
    ('x.com', 'twitter'),
    ('t.co', 'twitter'),
    ('whatsapp.com', 'whatsapp'),
    ('wa.me', 'whatsapp'),
    ('reddit.com', 'reddit'),
]


def _clean_url(value, *, require_path=False):
    """Return a trusted, truncated URL/path string, or ''."""
    if not isinstance(value, str):
        return ''
    value = value.strip()
    if not value:
        return ''
    if require_path:
        # Landing pages are client-supplied paths — same trust rule as
        # WhatsAppCheckoutView: a leading single slash or nothing.
        if not value.startswith('/') or value.startswith('//'):
            return ''
    return value[:MAX_URL_LENGTH]


def _referrer_host(referrer):
    try:
        host = urlsplit(referrer).hostname or ''
    except ValueError:
        return ''
    host = host.lower()
    return host[4:] if host.startswith('www.') else host


def derive_source(referrer, landing_page):
    """Compress a (referrer, landing page) pair into one source label.

    Priority: explicit utm_source on the landing URL beats the referrer
    (ChatGPT tags links but its app opens Safari with no referrer), click
    ids beat the generic referrer, then the referrer host map, then
    'direct' / 'other'.
    """
    query = ''
    try:
        query = urlsplit(landing_page).query
    except ValueError:
        pass
    params = parse_qs(query)

    utm = (params.get('utm_source') or [''])[0].strip().lower()
    if utm:
        label = UTM_SOURCE_LABELS.get(utm)
        if label:
            return label
        sanitized = ''.join(c for c in utm if c.isalnum() or c in '-_.')
        if sanitized:
            return sanitized[:MAX_SOURCE_LENGTH]
    if params.get('gclid'):
        return 'google-ads'
    if params.get('fbclid'):
        return 'facebook'

    host = _referrer_host(referrer)
    if not host:
        return 'direct'
    for pattern, label in REFERRER_HOST_LABELS:
        if pattern.endswith('.'):
            # Prefix pattern: 'google.' catches google.com, google.com.pk,
            # images.google.com — any host where a label equals 'google'.
            if host.startswith(pattern) or ('.' + host).find('.' + pattern) != -1:
                return label
        elif host == pattern or host.endswith('.' + pattern):
            return label
    return 'other'


def _first_seen(raw_ts):
    """Client's first-visit timestamp, clamped to something believable."""
    now = timezone.now()
    if not isinstance(raw_ts, str):
        return now
    parsed = parse_datetime(raw_ts.strip())
    if parsed is None:
        return now
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, _datetime.timezone.utc)
    if parsed > now or (now - parsed).days > 400:
        return now
    return parsed


def apply_first_touch(user, attribution):
    """Write first-touch attribution onto a freshly created user's profile.

    Write-once: acquisition_first_seen_at doubles as the captured flag, so
    a second call (or a login path re-posting the stash) never overwrites.
    Missing or malformed payloads leave the profile blank ("unknown") —
    that is distinct from 'direct', which means the client captured a
    first visit and genuinely saw no referrer.
    """
    profile = getattr(user, 'profile', None)
    if profile is None or profile.acquisition_first_seen_at is not None:
        return
    if not isinstance(attribution, dict):
        return

    referrer = _clean_url(attribution.get('referrer'))
    landing_page = _clean_url(attribution.get('landing_page'), require_path=True)
    if not referrer and not landing_page:
        return

    profile.acquisition_source = derive_source(referrer, landing_page)
    profile.acquisition_referrer = referrer
    profile.acquisition_landing_page = landing_page
    profile.acquisition_first_seen_at = _first_seen(attribution.get('first_seen_at'))
    profile.save(update_fields=[
        'acquisition_source', 'acquisition_referrer',
        'acquisition_landing_page', 'acquisition_first_seen_at',
    ])
