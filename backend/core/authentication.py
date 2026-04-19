from urllib.parse import urlparse

from django.conf import settings
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication


SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}


def _is_trusted_origin_url(url, request, trusted_origins):
    parsed_url = urlparse(url)
    if not parsed_url.scheme or not parsed_url.netloc:
        return False

    origin = f'{parsed_url.scheme}://{parsed_url.netloc}'
    if origin in trusted_origins:
        return True

    request_scheme = 'https' if request.is_secure() else 'http'
    return parsed_url.scheme == request_scheme and parsed_url.netloc == request.get_host()


def enforce_trusted_origin(request):
    if request.method in SAFE_METHODS:
        return

    trusted_origins = set(getattr(settings, 'CORS_ALLOWED_ORIGINS', []))
    trusted_origins.update(getattr(settings, 'CSRF_TRUSTED_ORIGINS', []))

    origin = request.META.get('HTTP_ORIGIN')
    if origin:
        if _is_trusted_origin_url(origin, request, trusted_origins):
            return
        raise exceptions.PermissionDenied('CSRF origin check failed.')

    referer = request.META.get('HTTP_REFERER')
    if referer and _is_trusted_origin_url(referer, request, trusted_origins):
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
