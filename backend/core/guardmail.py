"""Fetch login-verification codes from the shared guard mailbox.

Email-guard offline-activation accounts get their codes from ONE dedicated
mailbox that this module reads over IMAP. The platforms only email a code
when a login is attempted, so the flow is: buyer starts the login → the
platform emails the code → buyer presses the button / types !code → the
newest fresh code email for that account is parsed and the code handed over.

How an email is tied to an account differs per platform:
- Steam allows the same contact email on many accounts, and its guard email
  names the account login in the body — one mailbox serves every account,
  matched by login.
- Ubisoft/EA/Epic allow only ONE account per email address. Each such
  account stores its own guard_email — a Gmail dot/plus alias of the mailbox,
  or an address auto-forwarded into it — and emails are matched by To: address.
"""

import email
import email.header
import email.utils
import imaplib
import logging
import re
from datetime import timedelta, timezone as dt_timezone

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Newest emails first, but never trawl the whole mailbox.
MAX_MESSAGES_SCANNED = 30

# Under daphne all sync work shares one thread per process — an IMAP call
# that hangs without a timeout would stall every chat/HTTP request on the
# site until the OS gives up. Bound it like every other external call.
IMAP_TIMEOUT_SECONDS = 10

# The code sits alone on its own line in Steam's plain-text part.
_CODE_LINE_RE = re.compile(r'^\s*([A-Z0-9]{5})\s*$', re.MULTILINE)
_HTML_TAG_RE = re.compile(r'<[^>]+>')

# Ubisoft/EA/Epic codes are plain digits: alone on a line, or right after the
# word "code" (EA puts it in the subject: "Your EA Security Code is: NNNNNN").
_DIGIT_AFTER_CODE_RE = re.compile(r'code\D{0,20}(\d{4,8})', re.IGNORECASE)
_DIGIT_LINE_RE = re.compile(r'^\s*(\d{4,8})\s*$', re.MULTILINE)

# Only LOGIN-code templates may ever be parsed. With email guard the mailbox
# IS the account's second factor — email-change / password-reset / recovery
# mails must never reach a buyer, regardless of what their bodies contain.
# Two gates, both fail closed: a hard blocklist of account-security words,
# then a per-platform allowlist of the login-code template's subject.
# 'remov'/'disabl' guard against 2FA-removal emails, which carry a code too.
_SUBJECT_BLOCK_RE = re.compile(
    r'password|reset|recover|chang|delet|remov|disabl', re.IGNORECASE)

PLATFORM_MAIL = {
    'steam': {
        # "Your Steam account: Access from new computer/browser/device";
        # some variants say "Steam Guard".
        'search_from': 'steampowered.com',
        'sender_domains': ('steampowered.com',),
        'subject_allow': re.compile(r'access from|steam guard', re.IGNORECASE),
    },
    # Non-Steam platforms have no 'search_from': Gmail's IMAP SEARCH matches
    # whole tokens, not substrings (FROM "ubi" finds nothing from ubisoft.com),
    # so their search keys on the account's unique To: alias instead and the
    # sender is verified by _sender_domain_ok after fetching.
    'ubisoft': {
        # live-verified 2026-07-16: "Ubisoft Account Security Code"
        # from updates@account.ubisoft.com
        'sender_domains': ('ubisoft.com', 'ubi.com'),
        'subject_allow': re.compile(r'\bcode\b', re.IGNORECASE),
    },
    'ea': {
        # "Your EA Security Code is: NNNNNN"
        'sender_domains': ('ea.com',),
        'subject_allow': re.compile(r'security code', re.IGNORECASE),
    },
    'epic': {
        # Sign-in codes come from help@accts.epicgames.com (subdomain match).
        # Subject kept broad like Ubisoft's until live-verified.
        'sender_domains': ('epicgames.com',),
        'subject_allow': re.compile(r'\bcode\b', re.IGNORECASE),
    },
}


class GuardMailError(Exception):
    """The guard mailbox could not be read (config/network/auth)."""


def is_configured():
    return bool(
        settings.GUARD_EMAIL_IMAP_HOST
        and settings.GUARD_EMAIL_IMAP_USER
        and settings.GUARD_EMAIL_IMAP_PASSWORD
    )


def subject_allowed(platform, subject):
    """True only for the platform's login-code email template.
    Account-security emails (email change, password reset, recovery)
    always return False — blocklist first, then the allowlist."""
    text = str(subject or '')
    if _SUBJECT_BLOCK_RE.search(text):
        return False
    return bool(PLATFORM_MAIL[platform]['subject_allow'].search(text))


def is_login_code_subject(subject):
    """Steam shorthand for subject_allowed (kept for its long-proven name)."""
    return subject_allowed('steam', subject)


def extract_generic_code(subject, body):
    """The digit code in a Ubisoft/EA/Epic email — subject first (EA puts
    it there), then body. Only called for emails already matched to an
    account by To: address and vetted by subject_allowed."""
    for text in (str(subject or ''), str(body or '')):
        match = _DIGIT_AFTER_CODE_RE.search(text) or _DIGIT_LINE_RE.search(text)
        if match:
            return match.group(1)
    return None


def _sender_domain_ok(message, domains):
    """The From: address really is the platform (the IMAP FROM search only
    matches substrings — 'ea.com' would also match sea.com)."""
    address = email.utils.parseaddr(str(message.get('From', '')))[1].lower()
    domain = address.rsplit('@', 1)[-1]
    return any(domain == d or domain.endswith('.' + d) for d in domains)


def _addressed_to(message, guard_email):
    """Ubisoft/EA/Epic: the email was sent to this account's registered
    address (dot/plus aliases and forwards keep the original To: header)."""
    needle = str(guard_email).strip().lower()
    if not needle:
        return False
    headers = ' '.join(
        str(message.get(h, '') or '')
        for h in ('To', 'Cc', 'Delivered-To', 'X-Original-To')
    )
    return needle in headers.lower()


def _subject(message):
    parts = []
    try:
        decoded = email.header.decode_header(message.get('Subject', ''))
    except (TypeError, ValueError):
        return ''
    for value, charset in decoded:
        if isinstance(value, bytes):
            try:
                parts.append(value.decode(charset or 'utf-8', errors='replace'))
            except LookupError:
                parts.append(value.decode('utf-8', errors='replace'))
        else:
            parts.append(value)
    return ' '.join(parts)


def extract_code(body, login):
    """The Steam Guard code in one email body addressed to ``login``, or
    None. The body must name the account — that is the only thing tying a
    code to an account in a shared mailbox."""
    if not body or str(login).lower() not in body.lower():
        return None
    for match in _CODE_LINE_RE.finditer(body):
        code = match.group(1)
        if code.lower() != str(login).lower():  # a 5-char login is not a code
            return code
    return None


def _body_text(message):
    """Plain text of an email: the text/plain part, or tag-stripped HTML."""
    plain, html = [], []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        content_type = part.get_content_type()
        if content_type not in ('text/plain', 'text/html'):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or 'utf-8'
        try:
            text = payload.decode(charset, errors='replace')
        except LookupError:
            text = payload.decode('utf-8', errors='replace')
        (plain if content_type == 'text/plain' else html).append(text)
    if plain:
        return '\n'.join(plain)
    return _HTML_TAG_RE.sub('\n', '\n'.join(html))


def _sent_at(message):
    try:
        sent = email.utils.parsedate_to_datetime(message.get('Date', ''))
    except (TypeError, ValueError):
        return None
    if sent is None:
        return None
    if timezone.is_naive(sent):
        sent = timezone.make_aware(sent, dt_timezone.utc)
    return sent


def fetch_latest_code(account):
    """The newest fresh login code for an OfflineAccount, or None when no
    fresh code email exists yet (buyer must attempt the login first).
    Raises GuardMailError when the mailbox cannot be read."""
    if not is_configured():
        raise GuardMailError('guard mailbox is not configured')

    spec = PLATFORM_MAIL[account.platform]
    cutoff = timezone.now() - timedelta(
        minutes=settings.GUARD_EMAIL_MAX_AGE_MINUTES)
    since = cutoff.strftime('%d-%b-%Y')  # IMAP SINCE is day-granular

    if account.platform == 'steam':
        criteria = f'(FROM "{spec["search_from"]}" SINCE {since})'
    else:
        # One account per address: the unique To: alias is the search key
        # (see the PLATFORM_MAIL note on Gmail's token-only FROM search).
        alias = str(account.guard_email).replace('"', '').strip()
        criteria = f'(TO "{alias}" SINCE {since})'

    conn = None
    try:
        conn = imaplib.IMAP4_SSL(settings.GUARD_EMAIL_IMAP_HOST,
                                 settings.GUARD_EMAIL_IMAP_PORT,
                                 timeout=IMAP_TIMEOUT_SECONDS)
        conn.login(settings.GUARD_EMAIL_IMAP_USER,
                   settings.GUARD_EMAIL_IMAP_PASSWORD)
        conn.select('INBOX', readonly=True)
        status, data = conn.search(None, criteria)
        if status != 'OK':
            raise GuardMailError(f'IMAP search failed: {status}')
        message_ids = data[0].split()

        for msg_id in reversed(message_ids[-MAX_MESSAGES_SCANNED:]):
            status, fetched = conn.fetch(msg_id, '(BODY.PEEK[])')
            # Servers may pad the response with non-tuple items — only a
            # (envelope, bytes) tuple carries the message.
            if status != 'OK' or not fetched or not isinstance(fetched[0], tuple):
                continue
            message = email.message_from_bytes(fetched[0][1])
            subject = _subject(message)
            if not subject_allowed(account.platform, subject):
                continue  # never parse account-security emails
            if not _sender_domain_ok(message, spec['sender_domains']):
                continue  # IMAP FROM matches substrings; verify for real
            sent = _sent_at(message)
            if sent is not None and sent < cutoff:
                continue  # stale code from an earlier login attempt
            if account.platform == 'steam':
                code = extract_code(_body_text(message), account.login)
            else:
                if not _addressed_to(message, account.guard_email):
                    continue
                code = extract_generic_code(subject, _body_text(message))
            if code:
                return code
        return None
    except (imaplib.IMAP4.error, OSError) as exc:
        raise GuardMailError(str(exc)) from exc
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001 — cleanup must never raise
                pass
