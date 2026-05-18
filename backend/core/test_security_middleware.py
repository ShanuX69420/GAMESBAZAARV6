from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from .security_middleware import SecurityHeadersMiddleware


class SecurityHeadersMiddlewareTests(SimpleTestCase):
    def response_through_middleware(self, path='/api/health/', response=None):
        middleware = SecurityHeadersMiddleware(
            lambda _request: (
                response if response is not None else HttpResponse('ok')
            )
        )
        return middleware(RequestFactory().get(path))

    @override_settings(DEBUG=False)
    def test_adds_api_security_headers_when_debug_is_disabled(self):
        response = self.response_through_middleware()

        self.assertEqual(
            response['Content-Security-Policy'],
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'none'",
        )
        self.assertIn('camera=()', response['Permissions-Policy'])
        self.assertIn('accelerometer=()', response['Permissions-Policy'])
        self.assertEqual(response['X-Permitted-Cross-Domain-Policies'], 'none')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    @override_settings(DEBUG=True)
    def test_skips_api_security_headers_in_debug(self):
        response = self.response_through_middleware()

        self.assertNotIn('Content-Security-Policy', response)
        self.assertNotIn('Permissions-Policy', response)
        self.assertNotIn('X-Permitted-Cross-Domain-Policies', response)
        self.assertNotIn('X-Content-Type-Options', response)

    @override_settings(DEBUG=False)
    def test_skips_non_api_paths_so_django_admin_html_is_not_given_api_csp(self):
        response = self.response_through_middleware('/admin/')

        self.assertNotIn('Content-Security-Policy', response)
        self.assertNotIn('Permissions-Policy', response)
        self.assertNotIn('X-Permitted-Cross-Domain-Policies', response)
        self.assertNotIn('X-Content-Type-Options', response)

    @override_settings(DEBUG=False)
    def test_does_not_overwrite_view_defined_security_headers(self):
        view_response = HttpResponse('ok')
        view_response['Content-Security-Policy'] = "default-src 'self'"
        view_response['Permissions-Policy'] = 'geolocation=(self)'

        response = self.response_through_middleware(response=view_response)

        self.assertEqual(response['Content-Security-Policy'], "default-src 'self'")
        self.assertEqual(response['Permissions-Policy'], 'geolocation=(self)')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')


class SecurityHeadersSettingsTests(SimpleTestCase):
    def test_security_headers_middleware_runs_after_django_security_middleware(self):
        django_security_index = settings.MIDDLEWARE.index(
            'django.middleware.security.SecurityMiddleware'
        )
        custom_security_index = settings.MIDDLEWARE.index(
            'core.security_middleware.SecurityHeadersMiddleware'
        )

        self.assertEqual(custom_security_index, django_security_index + 1)
