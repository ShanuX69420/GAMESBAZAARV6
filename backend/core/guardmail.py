"""Fetch Steam Guard codes from the shared guard mailbox.

Email-guard offline-activation accounts can't use the TOTP generator (no
mobile authenticator — Steam requires a phone number those accounts can't
add). Instead, every such account's contact email points at ONE dedicated
mailbox (Steam allows the same email on many accounts) and this module pulls
codes out of it over IMAP.

Steam only emails a code when a login is attempted, so the flow is: buyer
starts the Steam login → Steam emails the code → buyer presses the button /
types !code → the newest fresh guard email naming that account login is
parsed and the code handed over. The email body contains the account name,
which is how one mailbox serves every account.
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

# Only Steam's LOGIN-code template ("Your Steam account: Access from new
# computer/browser/device", some variants say "Steam Guard") may ever be
# parsed. With email guard the mailbox IS the account's second factor —
# email-change / password-reset / recovery mails must never reach a buyer,
# regardless of what their bodies contain. Fail closed on anything else.
_LOGIN_SUBJECT_RE = re.compile(r'access from|steam guard', re.IGNORECASE)


class GuardMailError(Exception):
    """The guard mailbox could not be read (config/network/auth)."""


def is_configured():
    return bool(
        settings.GUARD_EMAIL_IMAP_HOST
        and settings.GUARD_EMAIL_IMAP_USER
        and settings.GUARD_EMAIL_IMAP_PASSWORD
    )


def is_login_code_subject(subject):
    """True only for Steam's login-code email template. Account-security
    emails (email change, password reset, recovery) always return False."""
    return bool(_LOGIN_SUBJECT_RE.search(str(subject or '')))


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


def fetch_latest_code(login):
    """The newest fresh Steam Guard code for ``login``, or None when no
    fresh guard email exists yet (buyer must attempt the Steam login first).
    Raises GuardMailError when the mailbox cannot be read."""
    if not is_configured():
        raise GuardMailError('guard mailbox is not configured')

    cutoff = timezone.now() - timedelta(
        minutes=settings.GUARD_EMAIL_MAX_AGE_MINUTES)
    since = cutoff.strftime('%d-%b-%Y')  # IMAP SINCE is day-granular

    conn = None
    try:
        conn = imaplib.IMAP4_SSL(settings.GUARD_EMAIL_IMAP_HOST,
                                 settings.GUARD_EMAIL_IMAP_PORT,
                                 timeout=IMAP_TIMEOUT_SECONDS)
        conn.login(settings.GUARD_EMAIL_IMAP_USER,
                   settings.GUARD_EMAIL_IMAP_PASSWORD)
        conn.select('INBOX', readonly=True)
        status, data = conn.search(
            None, f'(FROM "steampowered.com" SINCE {since})')
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
            if not is_login_code_subject(_subject(message)):
                continue  # never parse account-security emails
            sent = _sent_at(message)
            if sent is not None and sent < cutoff:
                continue  # stale code from an earlier login attempt
            code = extract_code(_body_text(message), login)
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
