"""
Django settings for gamesbazaar project.
"""

from pathlib import Path
from datetime import timedelta
from decimal import Decimal
import os
import sys
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_int(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_list(name, default=None):
    value = os.environ.get(name)
    if value is None:
        return list(default or [])
    return [item.strip() for item in value.split(',') if item.strip()]


def env_key_map(name):
    value = os.environ.get(name, '').strip()
    if not value:
        return {}

    key_map = {}
    for item in value.split(','):
        if ':' not in item:
            raise ImproperlyConfigured(
                f'{name} entries must use key_id:fernet_key format.'
            )
        key_id, key_value = item.split(':', 1)
        key_id = key_id.strip()
        key_value = key_value.strip()
        if not key_id or not key_value:
            raise ImproperlyConfigured(
                f'{name} entries must include both key id and key value.'
            )
        key_map[key_id] = key_value
    return key_map


DEV_SECRET_KEY = 'django-insecure-gamesbazaar-dev-key-change-in-production'

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', DEV_SECRET_KEY)

DJANGO_ENV = os.environ.get('DJANGO_ENV', '').strip().lower()
IS_TESTING = any(arg == 'test' or arg.startswith('test_') for arg in sys.argv)
IS_EXPLICIT_DEVELOPMENT = DJANGO_ENV in {'development', 'dev', 'local'}

if 'DJANGO_DEBUG' not in os.environ and not IS_EXPLICIT_DEVELOPMENT and not IS_TESTING:
    raise ImproperlyConfigured(
        'DJANGO_DEBUG must be set explicitly. Use DJANGO_ENV=development for local defaults.'
    )

DEBUG = env_bool('DJANGO_DEBUG', IS_EXPLICIT_DEVELOPMENT or IS_TESTING)

if DEBUG and not IS_EXPLICIT_DEVELOPMENT and not IS_TESTING:
    raise ImproperlyConfigured(
        'DJANGO_DEBUG=True is only allowed when DJANGO_ENV=development.'
    )

FIELD_ENCRYPTION_KEYS = env_key_map('FIELD_ENCRYPTION_KEYS')
FIELD_ENCRYPTION_PRIMARY_KEY_ID = (
    os.environ.get('FIELD_ENCRYPTION_PRIMARY_KEY_ID', '').strip()
    or next(reversed(FIELD_ENCRYPTION_KEYS), '')
)

if FIELD_ENCRYPTION_PRIMARY_KEY_ID and FIELD_ENCRYPTION_PRIMARY_KEY_ID not in FIELD_ENCRYPTION_KEYS:
    raise ImproperlyConfigured(
        'FIELD_ENCRYPTION_PRIMARY_KEY_ID must match a key id in FIELD_ENCRYPTION_KEYS.'
    )

ALLOWED_HOSTS = env_list(
    'DJANGO_ALLOWED_HOSTS',
    ['*'] if DEBUG else [],
)

if not DEBUG:
    if not os.environ.get('DJANGO_SECRET_KEY') or SECRET_KEY == DEV_SECRET_KEY:
        raise ImproperlyConfigured(
            'DJANGO_SECRET_KEY must be set to a unique production value when DJANGO_DEBUG=False.'
        )
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured(
            'DJANGO_ALLOWED_HOSTS must list production hostnames when DJANGO_DEBUG=False.'
        )
    if '*' in ALLOWED_HOSTS:
        raise ImproperlyConfigured(
            'DJANGO_ALLOWED_HOSTS cannot contain "*" when DJANGO_DEBUG=False.'
        )
    if not FIELD_ENCRYPTION_KEYS:
        raise ImproperlyConfigured(
            'FIELD_ENCRYPTION_KEYS must be set when DJANGO_DEBUG=False.'
        )

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Registers OpClass as an index expression wrapper (used by the
    # UPPER(...) trigram indexes in core.models).
    'django.contrib.postgres',
    # Third party
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'channels',
    # Local
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'core.security_middleware.SecurityHeadersMiddleware',
    'core.security_middleware.AdminIpAllowlistMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'gamesbazaar.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'gamesbazaar.wsgi.application'

# Database — PostgreSQL. Connections are kept alive between requests
# (DB_CONN_MAX_AGE seconds) instead of reconnecting per request; health
# checks drop stale connections before reuse.
DATABASES = {
    'default': {
        'ENGINE': os.environ.get('DB_ENGINE', 'django.db.backends.postgresql'),
        'NAME': os.environ.get('DB_NAME', 'gamesbazaar'),
        'USER': os.environ.get('DB_USER', 'postgres'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'postgres'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'CONN_MAX_AGE': env_int('DB_CONN_MAX_AGE', 60),
        'CONN_HEALTH_CHECKS': True,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Karachi'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files (game icons, etc.)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

CLOUDFLARE_R2_ENABLED = env_bool('CLOUDFLARE_R2_ENABLED', False)
CLOUDFLARE_R2_BUCKET_NAME = os.environ.get('CLOUDFLARE_R2_BUCKET_NAME', '').strip()
CLOUDFLARE_R2_ACCESS_KEY_ID = os.environ.get('CLOUDFLARE_R2_ACCESS_KEY_ID', '').strip()
CLOUDFLARE_R2_SECRET_ACCESS_KEY = os.environ.get('CLOUDFLARE_R2_SECRET_ACCESS_KEY', '').strip()
CLOUDFLARE_R2_ENDPOINT_URL = os.environ.get('CLOUDFLARE_R2_ENDPOINT_URL', '').strip()
CLOUDFLARE_R2_PUBLIC_URL_EXPIRATION_SECONDS = env_int(
    'CLOUDFLARE_R2_PUBLIC_URL_EXPIRATION_SECONDS',
    24 * 60 * 60,
)
CLOUDFLARE_R2_PRIVATE_URL_EXPIRATION_SECONDS = env_int(
    'CLOUDFLARE_R2_PRIVATE_URL_EXPIRATION_SECONDS',
    5 * 60,
)

if CLOUDFLARE_R2_ENABLED:
    missing_cloudflare_r2_settings = [
        name for name, value in {
            'CLOUDFLARE_R2_BUCKET_NAME': CLOUDFLARE_R2_BUCKET_NAME,
            'CLOUDFLARE_R2_ACCESS_KEY_ID': CLOUDFLARE_R2_ACCESS_KEY_ID,
            'CLOUDFLARE_R2_SECRET_ACCESS_KEY': CLOUDFLARE_R2_SECRET_ACCESS_KEY,
            'CLOUDFLARE_R2_ENDPOINT_URL': CLOUDFLARE_R2_ENDPOINT_URL,
        }.items()
        if not value
    ]
    if missing_cloudflare_r2_settings:
        raise ImproperlyConfigured(
            'CLOUDFLARE_R2_ENABLED=True requires: '
            + ', '.join(missing_cloudflare_r2_settings)
        )

    STORAGES = {
        'default': {
            'BACKEND': 'core.storage_backends.CloudflareR2Storage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Cache. DRF throttles use Django's default cache, so production must use a
# shared backend instead of per-process local memory.
CACHE_REDIS_URL = os.environ.get('CACHE_REDIS_URL') or os.environ.get('CHANNEL_REDIS_URL')
if CACHE_REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': CACHE_REDIS_URL,
        },
    }
elif DEBUG:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'gamesbazaar-dev',
        },
    }
else:
    raise ImproperlyConfigured(
        'CACHE_REDIS_URL or CHANNEL_REDIS_URL is required when DJANGO_DEBUG=False.'
    )

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'core.authentication.CookieJWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'core.permissions.HasCompletedProfile',
    ],
    'DEFAULT_PAGINATION_CLASS': None,
    'DEFAULT_THROTTLE_RATES': {
        'auth_login': '10/min',
        'auth_refresh': '30/min',
        'auth_register': '5/hour',
        'email_verify': '10/hour',
        'email_resend': '5/hour',
        'complete_profile': '10/hour',
        'password_change': '10/hour',
        'password_reset_request': '5/hour',
        'password_reset_confirm': '10/hour',
        'email_change_request': '5/hour',
        'email_change_confirm': '10/hour',
        'chat_start': '20/min',
        'chat_ws_ticket': '30/min',
        'inbox_ws_ticket': '30/min',
        'chat_message': '60/min',
        'chat_upload': '20/min',
        'topup_request': '10/hour',
        'jazzcash_initiate': '15/hour',
        'withdraw_request': '10/hour',
        'heartbeat': '120/hour',
        'search': '120/min',
        'avatar_upload': '20/hour',
        'seller_apply': '5/hour',
        'listing_create': '30/hour',
        'listing_mutation': '120/hour',
        'listing_restock': '60/hour',
        'create_report': '10/hour',
        'create_support_ticket': '5/hour',
        'create_item_request': '5/hour',
        'validate_topup_id': '20/min',
    },
}

# JWT Settings
JWT_ACCESS_TOKEN_MINUTES = env_int('JWT_ACCESS_TOKEN_MINUTES', 12 * 60 if DEBUG else 30)
JWT_REFRESH_TOKEN_DAYS = env_int('JWT_REFRESH_TOKEN_DAYS', 7)

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=JWT_ACCESS_TOKEN_MINUTES),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=JWT_REFRESH_TOKEN_DAYS),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

JWT_AUTH_COOKIE_ACCESS = 'gb_access_token'
JWT_AUTH_COOKIE_REFRESH = 'gb_refresh_token'
JWT_AUTH_COOKIE_HTTP_ONLY = True
JWT_AUTH_COOKIE_SECURE = env_bool('JWT_AUTH_COOKIE_SECURE', not DEBUG)
JWT_AUTH_COOKIE_SAMESITE = os.environ.get('JWT_AUTH_COOKIE_SAMESITE', 'Lax').strip() or 'Lax'
if JWT_AUTH_COOKIE_SAMESITE not in {'Lax', 'Strict', 'None'}:
    raise ImproperlyConfigured('JWT_AUTH_COOKIE_SAMESITE must be one of Lax, Strict, or None.')
JWT_AUTH_COOKIE_PATH = '/'

# Optional Django admin IP allowlist. Leave ADMIN_ALLOWED_IPS empty to rely on
# Django's staff/superuser authentication; set it to comma-separated IPs/CIDRs
# to block /admin/ before the login page for all other clients.
ADMIN_ALLOWED_IPS = env_list('ADMIN_ALLOWED_IPS', [])
ADMIN_TRUSTED_PROXY_IPS = env_list('ADMIN_TRUSTED_PROXY_IPS', [])

# Browser / proxy security. Defaults stay relaxed in local development and
# become strict automatically when DJANGO_DEBUG=False.
SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', not DEBUG)
SECURE_HSTS_SECONDS = env_int('SECURE_HSTS_SECONDS', 31536000 if not DEBUG else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', not DEBUG)
SECURE_HSTS_PRELOAD = env_bool('SECURE_HSTS_PRELOAD', False)
SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', not DEBUG)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# CORS — allow Next.js frontend
DEV_FRONTEND_ORIGINS = ['http://localhost:3000', 'http://127.0.0.1:3000']
CORS_ALLOWED_ORIGINS = env_list(
    'CORS_ALLOWED_ORIGINS',
    DEV_FRONTEND_ORIGINS if DEBUG else [],
)
CORS_ALLOW_CREDENTIALS = True
CORS_EXPOSE_HEADERS = sorted(set(env_list('CORS_EXPOSE_HEADERS', []) + ['Date']))
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS', CORS_ALLOWED_ORIGINS)
WEBSOCKET_ALLOWED_ORIGINS = env_list(
    'WEBSOCKET_ALLOWED_ORIGINS',
    CORS_ALLOWED_ORIGINS if not DEBUG else DEV_FRONTEND_ORIGINS,
)

if not DEBUG:
    if not CORS_ALLOWED_ORIGINS:
        raise ImproperlyConfigured(
            'CORS_ALLOWED_ORIGINS must list the production frontend origin when DJANGO_DEBUG=False.'
        )
    if not WEBSOCKET_ALLOWED_ORIGINS:
        raise ImproperlyConfigured(
            'WEBSOCKET_ALLOWED_ORIGINS or CORS_ALLOWED_ORIGINS must list the production frontend origin when DJANGO_DEBUG=False.'
        )

# Email — console in dev, configure SMTP for production
EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend' if DEBUG
    else 'django.core.mail.backends.smtp.EmailBackend',
)
DKIM_EMAIL_BACKEND = 'core.email_backends.DKIMSMTPEmailBackend'
SMTP_EMAIL_BACKENDS = {
    'django.core.mail.backends.smtp.EmailBackend',
    DKIM_EMAIL_BACKEND,
}
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@gamesbazaar.pk')
# Public site origin used for links inside transactional emails.
PUBLIC_SITE_URL = os.environ.get('PUBLIC_SITE_URL', 'https://www.gamesbazaar.pk').rstrip('/')
TRANSACTIONAL_EMAILS_ENABLED = env_bool('TRANSACTIONAL_EMAILS_ENABLED', True)
TRANSACTIONAL_EMAIL_FAIL_SILENTLY = env_bool('TRANSACTIONAL_EMAIL_FAIL_SILENTLY', True)
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'localhost' if DEBUG else '').strip()
EMAIL_PORT = env_int('EMAIL_PORT', 587)
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', not DEBUG)
EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL', False)
EMAIL_TIMEOUT = env_int('EMAIL_TIMEOUT', 20)
DKIM_DOMAIN = os.environ.get('DKIM_DOMAIN', '').strip()
DKIM_SELECTOR = os.environ.get('DKIM_SELECTOR', '').strip()
DKIM_PRIVATE_KEY = os.environ.get('DKIM_PRIVATE_KEY', '').strip()
DKIM_PRIVATE_KEY_PATH = os.environ.get('DKIM_PRIVATE_KEY_PATH', '').strip()
if DKIM_PRIVATE_KEY_PATH and not Path(DKIM_PRIVATE_KEY_PATH).is_absolute():
    DKIM_PRIVATE_KEY_PATH = str(BASE_DIR / DKIM_PRIVATE_KEY_PATH)

if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise ImproperlyConfigured('EMAIL_USE_TLS and EMAIL_USE_SSL cannot both be True.')

if (
    not DEBUG and
    EMAIL_BACKEND in SMTP_EMAIL_BACKENDS and
    not EMAIL_HOST
):
    raise ImproperlyConfigured(
        'EMAIL_HOST must be set when using SMTP email in production.'
    )

if EMAIL_BACKEND == DKIM_EMAIL_BACKEND:
    missing_dkim_settings = [
        name for name, value in {
            'DKIM_DOMAIN': DKIM_DOMAIN,
            'DKIM_SELECTOR': DKIM_SELECTOR,
            'DKIM_PRIVATE_KEY or DKIM_PRIVATE_KEY_PATH': (
                DKIM_PRIVATE_KEY or DKIM_PRIVATE_KEY_PATH
            ),
        }.items()
        if not value
    ]
    if missing_dkim_settings:
        raise ImproperlyConfigured(
            f'{DKIM_EMAIL_BACKEND} requires: ' + ', '.join(missing_dkim_settings)
        )
    if (
        not DKIM_PRIVATE_KEY and
        DKIM_PRIVATE_KEY_PATH and
        not Path(DKIM_PRIVATE_KEY_PATH).is_file()
    ):
        raise ImproperlyConfigured(
            f'DKIM_PRIVATE_KEY_PATH does not exist: {DKIM_PRIVATE_KEY_PATH}'
        )

# ASGI / Channels
ASGI_APPLICATION = 'gamesbazaar.asgi.application'
CHANNEL_REDIS_URL = os.environ.get('CHANNEL_REDIS_URL')
if CHANNEL_REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [CHANNEL_REDIS_URL],
            },
        },
    }
elif DEBUG:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }
else:
    raise ImproperlyConfigured('CHANNEL_REDIS_URL is required when DJANGO_DEBUG=False.')

# Google OAuth — Sign-In with Google
GOOGLE_OAUTH_CLIENT_ID = os.environ.get('GOOGLE_OAUTH_CLIENT_ID', '').strip()

# JazzCash MWallet payment gateway (REST API v1.1). Payments stay disabled
# until the merchant credentials are configured.
JAZZCASH_BASE_URL = (
    os.environ.get('JAZZCASH_BASE_URL', 'https://pgw.jazzcash.com.pk')
    .strip().rstrip('/')
)
JAZZCASH_MERCHANT_ID = os.environ.get('JAZZCASH_MERCHANT_ID', '').strip()
JAZZCASH_PASSWORD = os.environ.get('JAZZCASH_PASSWORD', '').strip()
JAZZCASH_INTEGRITY_SALT = os.environ.get('JAZZCASH_INTEGRITY_SALT', '').strip()
# Must be pre-registered with JazzCash; the same URL is sent on every request.
JAZZCASH_RETURN_URL = os.environ.get('JAZZCASH_RETURN_URL', '').strip()
# pp_SubMerchantName: mandatory and signed. JazzCash rejects anything that is
# not pure letters, so strip the value down to letters rather than trusting env.
JAZZCASH_SUB_MERCHANT_NAME = ''.join(
    ch for ch in os.environ.get('JAZZCASH_SUB_MERCHANT_NAME', 'GamesBazaar').strip()
    if ch.isascii() and ch.isalpha()
) or 'GamesBazaar'
# Only needed for the optional Refund API.
JAZZCASH_MERCHANT_MPIN = os.environ.get('JAZZCASH_MERCHANT_MPIN', '').strip()
# First three letters of the merchant domain, used in pp_TxnRefNo.
JAZZCASH_TXN_REF_PREFIX = (os.environ.get('JAZZCASH_TXN_REF_PREFIX', 'Gam').strip() or 'Gam')[:3]
JAZZCASH_REQUEST_TIMEOUT_SECONDS = env_int('JAZZCASH_REQUEST_TIMEOUT_SECONDS', 65)
# Sanity ceiling for a single JazzCash purchase charge (PKR). JazzCash itself
# declines anything beyond the customer's wallet limits; this only blocks
# absurd amounts that would overflow money fields.
JAZZCASH_MAX_PAYMENT_PKR = Decimal(str(env_int('JAZZCASH_MAX_PAYMENT_PKR', 1_000_000)))
JAZZCASH_ENABLED = bool(
    JAZZCASH_MERCHANT_ID and JAZZCASH_PASSWORD
    and JAZZCASH_INTEGRITY_SALT and JAZZCASH_RETURN_URL
)

# FazerCards supplier API — automatic fulfillment of Fazer-sourced listings
# (Steam keys, gift cards, game top-ups). Auto-fulfillment additionally needs
# the runtime PlatformSetting toggle 'fazer_autofulfill_enabled' switched on
# (manage.py fazer_autofulfill on|off|status).
FAZER_API_BASE_URL = (
    os.environ.get('FAZER_API_BASE_URL', 'https://api.fzr.cards/api/v2')
    .strip().rstrip('/')
)
FAZER_API_KEY = os.environ.get('FAZER_API_KEY', '').strip()
FAZER_REQUEST_TIMEOUT_SECONDS = env_int('FAZER_REQUEST_TIMEOUT_SECONDS', 30)
# Hard ceiling on the supplier cost of one order (USD) — bounds worst-case
# spend if prices or quantities go sideways.
FAZER_MAX_ORDER_USD = Decimal(str(env_int('FAZER_MAX_ORDER_USD', 30)))
# Refuse to auto-buy when the live supplier price exceeds the last-synced
# cost by more than this percentage (protects against stale sale prices).
FAZER_PRICE_TOLERANCE_PCT = env_int('FAZER_PRICE_TOLERANCE_PCT', 10)
# Alert (once a day) when the Fazer USD balance drops below this.
FAZER_LOW_BALANCE_USD = env_int('FAZER_LOW_BALANCE_USD', 10)

# Error monitoring — active whenever SENTRY_DSN is set. Captures unhandled
# exceptions and ERROR-level log records (including failed transactional
# emails) with the Django integration enabled automatically. Never active
# during test runs: tests deliberately trigger error paths.
SENTRY_DSN = os.environ.get('SENTRY_DSN', '').strip()
if IS_TESTING:
    SENTRY_DSN = ''
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=DJANGO_ENV or ('development' if DEBUG else 'production'),
        send_default_pii=False,
        traces_sample_rate=float(os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0') or '0'),
    )

# Logging — everything to stderr so systemd/journald (or the console in dev)
# captures it; WARNING+ from third-party code, INFO+ from Django and the app.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '{asctime} {levelname} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {'level': 'INFO'},
        'core': {'level': 'INFO'},
    },
}
