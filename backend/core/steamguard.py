"""Steam Guard TOTP code generation for offline-activation accounts.

Steam's mobile authenticator is standard TOTP (HMAC-SHA1 over a 30-second
counter) with a custom 26-character alphabet and 5-character codes. Given an
account's ``shared_secret`` (the base64 seed from its maFile / Steam Desktop
Authenticator export), this produces exactly the code the Steam app would
show — no network calls involved.
"""

import base64
import hashlib
import hmac
import re
import struct
import time

CODE_INTERVAL_SECONDS = 30
_ALPHABET = '23456789BCDFGHJKMNPQRTVWXY'

# FunPay-style chat commands buyers use to ask for the current code.
_COMMAND_RE = re.compile(r'^\s*!\s*(code|guard|2fa)\s*[.!]*\s*$', re.IGNORECASE)


def generate_code(shared_secret, timestamp=None):
    """The current 5-character Steam Guard code for a base64 shared_secret.

    Raises ValueError when the secret is empty or not valid base64. The
    empty check matters: decrypt_sensitive_text returns '' for a value it
    cannot decrypt, and b64decode('') succeeds — without the check that
    would silently become a plausible-looking wrong code.
    """
    secret = base64.b64decode(str(shared_secret).strip(), validate=True)
    if not secret:
        raise ValueError('shared_secret is empty')
    ts = int(time.time() if timestamp is None else timestamp)
    counter = struct.pack('>Q', ts // CODE_INTERVAL_SECONDS)
    digest = hmac.new(secret, counter, hashlib.sha1).digest()
    start = digest[19] & 0x0F
    value = struct.unpack('>I', digest[start:start + 4])[0] & 0x7FFFFFFF
    code = ''
    for _ in range(5):
        code += _ALPHABET[value % len(_ALPHABET)]
        value //= len(_ALPHABET)
    return code


def seconds_remaining(timestamp=None):
    """How long the code generated right now stays valid."""
    ts = int(time.time() if timestamp is None else timestamp)
    return CODE_INTERVAL_SECONDS - (ts % CODE_INTERVAL_SECONDS)


def is_guard_command(text):
    """True when a chat message is a request for the Steam Guard code."""
    return bool(_COMMAND_RE.match(str(text or '')))
