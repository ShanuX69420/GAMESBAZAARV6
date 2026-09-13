"""Turn what a person types as their name into a username Django accepts.

The sign-up form asks for a "display name", but ``User.username`` only allows
letters, digits and ``@ . + - _``, so "Ali Khan" came back as a validator
message about permitted characters. In the fortnight to 2026-09-13 that was
25 of the 82 rejected sign-ups, and a third of the people who hit any error
never registered. The name is now normalised instead of refused: spaces and
other stray characters become single underscores, and a clash with an
existing account gets a numeric suffix (silently when the name was changed
anyway, as a suggestion when they typed the exact name).
"""
import re
import secrets

from django.contrib.auth.models import User

# Runs of characters Django's UnicodeUsernameValidator (^[\w.@+-]+\Z) refuses.
_INVALID_RUN = re.compile(r'[^\w.@+-]+')
_UNDERSCORE_RUN = re.compile(r'_{2,}')
# Leaves room for a "_NN" suffix well under User.username's max_length (150).
MAX_BASE_LENGTH = 40


class UsernameError(ValueError):
    """A name with nothing usable in it, or an exact clash — message is user-facing."""


def normalize_display_name(value):
    """'Ali Khan' -> 'Ali_Khan'; ' ali   khan! ' -> 'ali_khan'; '!!!' -> ''."""
    value = _INVALID_RUN.sub('_', (value or '').strip())
    value = _UNDERSCORE_RUN.sub('_', value).strip('_')
    return value[:MAX_BASE_LENGTH].rstrip('_')


def username_is_taken(username, exclude_pk=None):
    qs = User.objects.filter(username__iexact=username)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def next_free_username(base, exclude_pk=None):
    """``base`` if free, else base_2, base_3, ... (numbers read better than the
    random hex the Google and guest flows append to names nobody chose)."""
    if not username_is_taken(base, exclude_pk):
        return base
    for n in range(2, 1000):
        candidate = f'{base}_{n}'
        if not username_is_taken(candidate, exclude_pk):
            return candidate
    return f'{base}_{secrets.token_hex(3)}'


def resolve_signup_username(typed, exclude_pk=None):
    """The username a sign-up gets for the name they typed.

    Raises UsernameError with a user-facing message when nothing usable was
    typed, or when the exact name is taken (the message names a free one so
    a single retry fixes it). A normalised name that clashes is suffixed
    silently — they never asked for that exact string.
    """
    typed = (typed or '').strip()
    base = normalize_display_name(typed)
    if not base:
        raise UsernameError('Please use at least one letter or number in your name.')
    if not username_is_taken(base, exclude_pk):
        return base
    suggestion = next_free_username(base, exclude_pk)
    if base.lower() != typed.lower():
        return suggestion
    raise UsernameError(f'That name is already taken. Try {suggestion}.')
