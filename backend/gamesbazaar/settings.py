"""
Django settings for gamesbazaar project.
"""

from pathlib import Path
from datetime import timedelta
import os
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


DEV_SECRET_KEY = 'django-insecure-gamesbazaar-dev-key-change-in-production'

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', DEV_SECRET_KEY)

DEBUG = env_bool('DJANGO_DEBUG', True)

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

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
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

# Database — PostgreSQL
DATABASES = {
    'default': {
        'ENGINE': os.environ.get('DB_ENGINE', 'django.db.backends.postgresql'),
        'NAME': os.environ.get('DB_NAME', 'gamesbazaar'),
        'USER': os.environ.get('DB_USER', 'postgres'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'postgres'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
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

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'core.authentication.CookieJWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': None,
    'DEFAULT_THROTTLE_RATES': {
        'auth_login': '10/min',
        'auth_refresh': '30/min',
        'auth_register': '5/hour',
        'chat_start': '20/min',
        'chat_message': '60/min',
        'chat_upload': '20/min',
        'topup_request': '10/hour',
        'heartbeat': '120/hour',
    },
}

# JWT Settings
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=12),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

JWT_AUTH_COOKIE_ACCESS = 'gb_access_token'
JWT_AUTH_COOKIE_REFRESH = 'gb_refresh_token'
JWT_AUTH_COOKIE_HTTP_ONLY = True
JWT_AUTH_COOKIE_SECURE = env_bool('JWT_AUTH_COOKIE_SECURE', not DEBUG)
JWT_AUTH_COOKIE_SAMESITE = 'Lax'
JWT_AUTH_COOKIE_PATH = '/'

# Browser / proxy security. Defaults stay relaxed in local development and
# become strict automatically when DJANGO_DEBUG=False.
SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', not DEBUG)
SECURE_HSTS_SECONDS = env_int('SECURE_HSTS_SECONDS', 31536000 if not DEBUG else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', not DEBUG)
SECURE_HSTS_PRELOAD = env_bool('SECURE_HSTS_PRELOAD', False)
SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', not DEBUG)

# CORS — allow Next.js frontend
DEV_FRONTEND_ORIGINS = ['http://localhost:3000', 'http://127.0.0.1:3000']
CORS_ALLOWED_ORIGINS = env_list(
    'CORS_ALLOWED_ORIGINS',
    DEV_FRONTEND_ORIGINS if DEBUG else [],
)
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS', CORS_ALLOWED_ORIGINS)

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
