"""
Security headers middleware for Django API responses.

Adds Content-Security-Policy, Permissions-Policy, and other hardening
headers that Django's built-in SecurityMiddleware does not cover.

These headers protect the API layer; the Next.js frontend has its own
proxy that sets equivalent static headers for browser-rendered pages.
"""

from django.conf import settings


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
