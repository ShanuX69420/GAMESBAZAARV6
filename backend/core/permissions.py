from rest_framework.permissions import IsAuthenticated

from .models import SocialAccount


PROFILE_SETUP_TOKEN_CLAIM = 'needs_setup'


def user_needs_profile_setup(user):
    """Return whether a Google-linked account still must finish onboarding."""
    profile = getattr(user, 'profile', None)
    if profile and profile.has_accepted_terms:
        return False
    return user.social_accounts.filter(provider=SocialAccount.PROVIDER_GOOGLE).exists()


def add_profile_setup_token_claim(token, user, *, needs_setup=None):
    """Store stable onboarding state in a signed token for fast authorization."""
    if needs_setup is None:
        needs_setup = user_needs_profile_setup(user)
    token[PROFILE_SETUP_TOKEN_CLAIM] = needs_setup
    return token


def request_user_needs_profile_setup(request):
    """Use JWT state for completed sessions, with safe checks for pending/old tokens."""
    token = getattr(request, 'auth', None)
    claim = token.get(PROFILE_SETUP_TOKEN_CLAIM) if hasattr(token, 'get') else None
    if claim is False:
        return False
    if claim is True:
        profile = getattr(request.user, 'profile', None)
        return not (profile and profile.has_accepted_terms)
    return user_needs_profile_setup(request.user)


class HasCompletedProfile(IsAuthenticated):
    """Require authentication and completed onboarding for account actions."""

    message = 'Complete your profile setup before continuing.'
    code = 'profile_setup_required'

    def has_permission(self, request, view):
        return (
            super().has_permission(request, view) and
            not request_user_needs_profile_setup(request)
        )
