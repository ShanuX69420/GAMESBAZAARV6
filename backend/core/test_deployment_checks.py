from django.test import SimpleTestCase, override_settings

from .checks import production_error_monitoring_check, production_throttle_cache_check


REDIS_CACHE = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': 'redis://localhost:6379/1',
    },
}


class ProductionThrottleCacheCheckTests(SimpleTestCase):
    @override_settings(
        DEBUG=False,
        CACHES=REDIS_CACHE,
        REST_FRAMEWORK={'DEFAULT_THROTTLE_RATES': {'auth_login': '10/min'}},
    )
    def test_accepts_redis_cache_with_throttle_rates(self):
        self.assertEqual(production_throttle_cache_check(None), [])

    @override_settings(
        DEBUG=False,
        CACHES={
            'default': {
                'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'local',
            },
        },
        REST_FRAMEWORK={'DEFAULT_THROTTLE_RATES': {'auth_login': '10/min'}},
    )
    def test_rejects_non_redis_cache_in_production(self):
        errors = production_throttle_cache_check(None)

        self.assertIn('core.E001', [error.id for error in errors])

    @override_settings(
        DEBUG=False,
        CACHES={
            'default': {
                'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            },
        },
        REST_FRAMEWORK={'DEFAULT_THROTTLE_RATES': {'auth_login': '10/min'}},
    )
    def test_rejects_missing_redis_location_in_production(self):
        errors = production_throttle_cache_check(None)

        self.assertIn('core.E002', [error.id for error in errors])

    @override_settings(
        DEBUG=False,
        CACHES=REDIS_CACHE,
        REST_FRAMEWORK={'DEFAULT_THROTTLE_RATES': {}},
    )
    def test_rejects_missing_throttle_rates_in_production(self):
        errors = production_throttle_cache_check(None)

        self.assertIn('core.E003', [error.id for error in errors])

    @override_settings(
        DEBUG=True,
        CACHES={
            'default': {
                'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': 'local',
            },
        },
        REST_FRAMEWORK={'DEFAULT_THROTTLE_RATES': {}},
    )
    def test_skips_local_development(self):
        self.assertEqual(production_throttle_cache_check(None), [])


class ProductionErrorMonitoringCheckTests(SimpleTestCase):
    @override_settings(DEBUG=False, SENTRY_DSN='https://key@sentry.example.com/1')
    def test_accepts_configured_sentry_dsn(self):
        self.assertEqual(production_error_monitoring_check(None), [])

    @override_settings(DEBUG=False, SENTRY_DSN='')
    def test_warns_when_sentry_dsn_missing_in_production(self):
        warnings = production_error_monitoring_check(None)

        self.assertIn('core.W001', [warning.id for warning in warnings])

    @override_settings(DEBUG=True, SENTRY_DSN='')
    def test_skips_local_development(self):
        self.assertEqual(production_error_monitoring_check(None), [])
