from django.conf import settings
from django.core.checks import Error, Tags, register


REDIS_CACHE_BACKEND = 'django.core.cache.backends.redis.RedisCache'


@register(Tags.security, deploy=True)
def production_throttle_cache_check(app_configs, **kwargs):
    if settings.DEBUG:
        return []

    errors = []
    default_cache = settings.CACHES.get('default') or {}
    backend = default_cache.get('BACKEND', '')
    location = default_cache.get('LOCATION')

    if backend != REDIS_CACHE_BACKEND:
        errors.append(Error(
            'Production DRF throttling must use the shared Redis cache backend.',
            hint='Set CACHE_REDIS_URL or CHANNEL_REDIS_URL so CACHES["default"] uses django.core.cache.backends.redis.RedisCache.',
            id='core.E001',
        ))

    if not location:
        errors.append(Error(
            'Production Redis cache LOCATION is missing.',
            hint='Set CACHE_REDIS_URL to the shared Redis instance used for DRF throttling.',
            id='core.E002',
        ))

    throttle_rates = (
        getattr(settings, 'REST_FRAMEWORK', {})
        .get('DEFAULT_THROTTLE_RATES')
    )
    if not throttle_rates:
        errors.append(Error(
            'Production DRF throttle rates are not configured.',
            hint='Keep REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] populated for sensitive API throttles.',
            id='core.E003',
        ))

    return errors
