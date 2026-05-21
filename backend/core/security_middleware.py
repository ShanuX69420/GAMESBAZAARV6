"""
Security middleware for Django API responses and admin access.

Adds Content-Security-Policy, Permissions-Policy, and other hardening
headers that Django's built-in SecurityMiddleware does not cover.

These headers protect the API layer; the Next.js frontend has its own
proxy that sets equivalent static headers for browser-rendered pages.
"""

from ipaddress import ip_address, ip_network

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponseForbidden


def parse_ip_networks(values, setting_name):
    networks = []
    for value in values:
        try:
            networks.append(ip_network(value, strict=False))
        except ValueError as exc:
            raise ImproperlyConfigured(
                f'{setting_name} contains an invalid IP address or CIDR: {value}'
            ) from exc
    return tuple(networks)


class AdminIpAllowlistMiddleware:
    """
    Optionally restrict Django admin to configured client IPs/CIDR ranges.

    Disabled unless ADMIN_ALLOWED_IPS is set. When Django is behind a trusted
    reverse proxy, ADMIN_TRUSTED_PROXY_IPS enables using that proxy's
    X-Forwarded-For client address.
    """

    ADMIN_PATH_PREFIX = '/admin/'

    def __init__(self, get_response):
        self.get_response = get_response
        self.allowed_networks = parse_ip_networks(
            getattr(settings, 'ADMIN_ALLOWED_IPS', []),
            'ADMIN_ALLOWED_IPS',
        )
        self.trusted_proxy_networks = parse_ip_networks(
            getattr(settings, 'ADMIN_TRUSTED_PROXY_IPS', []),
            'ADMIN_TRUSTED_PROXY_IPS',
        )

    def should_apply_to_request(self, request):
        path = getattr(request, 'path_info', getattr(request, 'path', ''))
        return path == self.ADMIN_PATH_PREFIX.rstrip('/') or path.startswith(self.ADMIN_PATH_PREFIX)

    def request_ip(self, request):
        remote_addr = request.META.get('REMOTE_ADDR', '')
        try:
            remote_ip = ip_address(remote_addr)
        except ValueError:
            return None

        if any(remote_ip in network for network in self.trusted_proxy_networks):
            forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
            forwarded_ip = forwarded_for.split(',', 1)[0].strip()
            if forwarded_ip:
                try:
                    return ip_address(forwarded_ip)
                except ValueError:
                    return None

        return remote_ip

    def is_allowed(self, request):
        client_ip = self.request_ip(request)
        if client_ip is None:
            return False
        return any(client_ip in network for network in self.allowed_networks)

    def __call__(self, request):
        if (
            self.allowed_networks and
            self.should_apply_to_request(request) and
            not self.is_allowed(request)
        ):
            return HttpResponseForbidden('Forbidden')

        return self.get_response(request)


class SecurityHeadersMiddleware:
    """
    Append production-grade security headers to API HTTP responses.

    Placed immediately after Django's SecurityMiddleware so it runs on
    API responses, including API error pages.

    Skipped entirely when DEBUG=True to avoid interfering with the
    browsable API, Django Debug Toolbar, etc.
    """

    API_PATH_PREFIX = '/api/'

    # Headers that never change between requests - built once at startup.
    STATIC_HEADERS = {
        # Strict CSP for an API that serves JSON - no scripts, styles, or
        # frames should ever be needed.
        'Content-Security-Policy': (
            "default-src 'none'; "
            "frame-ancestors 'none'; "
            "base-uri 'none'; "
            "form-action 'none'"
        ),
        # Restrict access to powerful browser features.
        'Permissions-Policy': (
            'camera=(), '
            'microphone=(), '
            'geolocation=(), '
            'payment=(), '
            'usb=(), '
            'magnetometer=(), '
            'gyroscope=(), '
            'accelerometer=()'
        ),
        # Prevent Adobe Flash / Acrobat cross-domain policy loading.
        'X-Permitted-Cross-Domain-Policies': 'none',
        # nosniff is already set by SecurityMiddleware via SECURE_CONTENT_TYPE_NOSNIFF,
        # but we set it explicitly as defence-in-depth.
        'X-Content-Type-Options': 'nosniff',
    }

    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = not settings.DEBUG

    def should_apply_to_request(self, request):
        path = getattr(request, 'path_info', getattr(request, 'path', ''))
        return (
            path == self.API_PATH_PREFIX.rstrip('/') or
            path.startswith(self.API_PATH_PREFIX)
        )

    def __call__(self, request):
        response = self.get_response(request)

        if self.enabled and self.should_apply_to_request(request):
            for header, value in self.STATIC_HEADERS.items():
                # Don't overwrite if a view has already set the header
                # (e.g. an API view sets its own CSP).
                if header not in response:
                    response[header] = value

        return response
