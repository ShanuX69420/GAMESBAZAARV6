from urllib.parse import urlparse

from django.conf import settings
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication


SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}


def enforce_trusted_origin(request):
    if request.method in SAFE_METHODS:
        return

    origin = request.META.get('HTTP_ORIGIN')
    if not origin:
        return

    trusted_origins = set(getattr(settings, 'CORS_ALLOWED_ORIGINS', []))
    trusted_origins.update(getattr(settings, 'CSRF_TRUSTED_ORIGINS', []))
    if origin in trusted_origins:
        return

    parsed_origin = urlparse(origin)
    request_scheme = 'https' if request.is_secure() else 'http'
    if parsed_origin.scheme == request_scheme and parsed_origin.netloc == request.get_host():
        return

    raise exceptions.PermissionDenied('CSRF origin check failed.')


class CookieJWTAuthentication(JWTAuthentication):
    """
    SimpleJWT authentication that preserves Authorization: Bearer support and
    falls back to an HttpOnly access-token cookie when no Authorization header
    is present.
    """

    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            raw_token = self.get_raw_token(header)
            if raw_token is None:
                return None
        else:
            raw_token = request.COOKIES.get(settings.JWT_AUTH_COOKIE_ACCESS)
            if raw_token is None:
                return None
            enforce_trusted_origin(request)

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token
