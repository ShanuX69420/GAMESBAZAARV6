from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from .security_middleware import AdminIpAllowlistMiddleware, SecurityHeadersMiddleware


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


class AdminIpAllowlistMiddlewareTests(SimpleTestCase):
    def response_through_middleware(self, path='/admin/', remote_addr='198.51.100.10', headers=None):
        self.view_called = False

        def view(_request):
            self.view_called = True
            return HttpResponse('ok')

        request = RequestFactory().get(path, **(headers or {}))
        request.META['REMOTE_ADDR'] = remote_addr
        middleware = AdminIpAllowlistMiddleware(view)
        return middleware(request)

    @override_settings(ADMIN_ALLOWED_IPS=[], ADMIN_TRUSTED_PROXY_IPS=[])
    def test_allows_admin_when_allowlist_is_not_configured(self):
        response = self.response_through_middleware()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.view_called)

    @override_settings(ADMIN_ALLOWED_IPS=['203.0.113.10'], ADMIN_TRUSTED_PROXY_IPS=[])
    def test_blocks_admin_when_client_ip_is_not_allowed(self):
        response = self.response_through_middleware(remote_addr='198.51.100.10')

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.view_called)

    @override_settings(ADMIN_ALLOWED_IPS=['203.0.113.0/24'], ADMIN_TRUSTED_PROXY_IPS=[])
    def test_allows_admin_when_client_ip_is_in_allowed_cidr(self):
        response = self.response_through_middleware(remote_addr='203.0.113.42')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.view_called)

    @override_settings(ADMIN_ALLOWED_IPS=['203.0.113.10'], ADMIN_TRUSTED_PROXY_IPS=[])
    def test_does_not_apply_to_non_admin_paths(self):
        response = self.response_through_middleware('/api/admin/orders/1/resolve-dispute/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.view_called)

    @override_settings(
        ADMIN_ALLOWED_IPS=['203.0.113.10'],
        ADMIN_TRUSTED_PROXY_IPS=['10.0.0.0/8'],
    )
    def test_uses_forwarded_for_from_trusted_proxy(self):
        response = self.response_through_middleware(
            remote_addr='10.1.2.3',
            headers={'HTTP_X_FORWARDED_FOR': '203.0.113.10, 10.1.2.3'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.view_called)

    @override_settings(
        ADMIN_ALLOWED_IPS=['203.0.113.10'],
        ADMIN_TRUSTED_PROXY_IPS=['10.0.0.0/8'],
    )
    def test_ignores_forwarded_for_from_untrusted_proxy(self):
        response = self.response_through_middleware(
            remote_addr='198.51.100.10',
            headers={'HTTP_X_FORWARDED_FOR': '203.0.113.10'},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.view_called)

    @override_settings(ADMIN_ALLOWED_IPS=['not-an-ip'], ADMIN_TRUSTED_PROXY_IPS=[])
    def test_rejects_invalid_allowlist_entries(self):
        with self.assertRaises(ImproperlyConfigured):
            AdminIpAllowlistMiddleware(lambda _request: HttpResponse('ok'))
