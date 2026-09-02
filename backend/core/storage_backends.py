import hashlib
import mimetypes

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage
from django.urls import reverse
from django.utils.deconstruct import deconstructible

try:
    from storages.backends.s3 import S3Storage
except ImportError:  # pragma: no cover - raised only when R2 is enabled without deps.
    S3Storage = None


CLOUDFLARE_R2_NAME_PREFIX = 'r2/'
AVATAR_CACHE_SECONDS = 60 * 60
# Public media served through /api/media/<kind>/<name> (see views.PublicMediaView).
# Avatars are shown on every listing page but live in the private R2 bucket, so
# they need a signed URL to load. Handing that signed URL straight to the page
# meant it got baked into cached HTML and expired underneath crawlers (Ahrefs
# 2026-09-02: "broken image" on ~2,000 pages). The stable address below never
# carries a signature; the endpoint behind it redirects to a fresh one.
AVATAR_MEDIA_KIND = 'avatars'
# How long browsers/proxies may reuse the redirect itself.
PUBLIC_MEDIA_REDIRECT_CACHE_SECONDS = 5 * 60
# How long the signed URL the redirect points at stays valid. Must comfortably
# exceed the redirect cache + memo windows so a cached redirect never lands on
# an expired link.
PUBLIC_MEDIA_SIGNED_URL_SECONDS = 60 * 60
# Reuse one signed URL for this long so repeat visitors hit their browser cache
# for the image bytes instead of re-downloading behind every fresh signature.
PUBLIC_MEDIA_SIGNED_URL_MEMO_SECONDS = 10 * 60
assert (
    PUBLIC_MEDIA_REDIRECT_CACHE_SECONDS + PUBLIC_MEDIA_SIGNED_URL_MEMO_SECONDS
    < PUBLIC_MEDIA_SIGNED_URL_SECONDS
), 'a cached public-media redirect must never outlive the signed URL it points at'
GAME_ICON_CACHE_SECONDS = 30 * 24 * 60 * 60
REVIEW_IMAGE_CACHE_SECONDS = 24 * 60 * 60
R2_SIGNED_URL_MAX_SECONDS = 7 * 24 * 60 * 60
R2_SIGNED_URL_CACHE_SAFETY_SECONDS = 60
IMAGE_CONTENT_TYPES_BY_EXTENSION = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
}


def is_cloudflare_r2_name(name):
    return str(name or '').startswith(CLOUDFLARE_R2_NAME_PREFIX)


def media_content_type(name):
    guessed = mimetypes.guess_type(name)[0]
    if guessed:
        return guessed

    normalized = str(name or '').lower()
    for extension, content_type in IMAGE_CONTENT_TYPES_BY_EXTENSION.items():
        if normalized.endswith(extension):
            return content_type
    return None


def r2_signed_url_expiration(cache_seconds):
    return min(
        max(cache_seconds, settings.CLOUDFLARE_R2_PUBLIC_URL_EXPIRATION_SECONDS),
        R2_SIGNED_URL_MAX_SECONDS,
    )


def r2_signed_url_cache_key(name, *, cache_seconds, cache_scope, content_type, expire):
    raw_key = ':'.join([
        settings.CLOUDFLARE_R2_BUCKET_NAME,
        settings.CLOUDFLARE_R2_ENDPOINT_URL,
        str(name),
        str(cache_seconds),
        cache_scope,
        content_type or '',
        str(expire),
    ])
    digest = hashlib.sha256(raw_key.encode('utf-8')).hexdigest()
    return f'r2-signed-media-url:v1:{digest}'


def cached_media_url(file_field, *, request=None, cache_seconds=3600, cache_scope='public'):
    """Build a media URL with cache headers for signed R2 object responses."""
    if not file_field:
        return None

    name = getattr(file_field, 'name', '')
    if is_cloudflare_r2_name(name):
        parameters = {
            'ResponseCacheControl': f'{cache_scope}, max-age={cache_seconds}',
        }
        content_type = media_content_type(name)
        if content_type:
            parameters['ResponseContentType'] = content_type
        expire = r2_signed_url_expiration(cache_seconds)
        url_cache_timeout = max(0, expire - R2_SIGNED_URL_CACHE_SAFETY_SECONDS)
        url_cache_key = r2_signed_url_cache_key(
            name,
            cache_seconds=cache_seconds,
            cache_scope=cache_scope,
            content_type=content_type,
            expire=expire,
        )
        url = cache.get(url_cache_key) if url_cache_timeout else None
        if url is None:
            url = file_field.storage.url(
                name,
                parameters=parameters,
                expire=expire,
            )
            if url_cache_timeout:
                cache.set(url_cache_key, url, url_cache_timeout)
    else:
        url = file_field.url

    if request and str(url).startswith('/'):
        return request.build_absolute_uri(url)
    return url


def public_media_name(file_field, kind):
    """The <name> segment of a stable /api/media/<kind>/<name> URL, or None
    when the file is not an R2 object under that kind's folder."""
    name = str(getattr(file_field, 'name', '') or '')
    prefix = f'{CLOUDFLARE_R2_NAME_PREFIX}{kind}/'
    if not name.startswith(prefix):
        return None
    rest = name[len(prefix):]
    if not rest or '/' in rest:
        return None
    return rest


def public_avatar_url(file_field, request=None):
    """Stable, unsigned URL for a profile avatar.

    R2 avatars resolve through the public-media redirect endpoint, so the
    address embedded in API payloads (and therefore in server-rendered page
    HTML) never expires. Legacy avatars on local disk keep their plain
    /media/avatars/ address, which nginx serves directly.
    """
    if not file_field:
        return None
    media_name = public_media_name(file_field, AVATAR_MEDIA_KIND)
    if media_name is None:
        return cached_media_url(
            file_field,
            request=request,
            cache_seconds=AVATAR_CACHE_SECONDS,
            cache_scope='private',
        )
    url = reverse('public-media', kwargs={'kind': AVATAR_MEDIA_KIND, 'name': media_name})
    if request:
        return request.build_absolute_uri(url)
    return url


@deconstructible
class CloudflareR2Storage(S3Storage if S3Storage is not None else object):
    """Store new uploads in Cloudflare R2 while keeping old local media readable."""

    def __init__(self, *args, **kwargs):
        if S3Storage is None:
            raise ImproperlyConfigured(
                'Cloudflare R2 storage requires django-storages with boto3 support.'
            )

        self.local_storage = FileSystemStorage(
            location=settings.MEDIA_ROOT,
            base_url=settings.MEDIA_URL,
        )

        options = {
            'bucket_name': settings.CLOUDFLARE_R2_BUCKET_NAME,
            'access_key': settings.CLOUDFLARE_R2_ACCESS_KEY_ID,
            'secret_key': settings.CLOUDFLARE_R2_SECRET_ACCESS_KEY,
            'endpoint_url': settings.CLOUDFLARE_R2_ENDPOINT_URL,
            'region_name': 'auto',
            'addressing_style': 'path',
            'default_acl': None,
            'file_overwrite': False,
            'querystring_auth': True,
            'querystring_expire': settings.CLOUDFLARE_R2_PUBLIC_URL_EXPIRATION_SECONDS,
        }
        options.update(kwargs)
        super().__init__(*args, **options)

    def _r2_name(self, name):
        normalized = str(name or '').replace('\\', '/').lstrip('/')
        if is_cloudflare_r2_name(normalized):
            return normalized
        return f'{CLOUDFLARE_R2_NAME_PREFIX}{normalized}'

    def save(self, name, content, max_length=None):
        return super().save(self._r2_name(name), content, max_length=max_length)

    def exists(self, name):
        if is_cloudflare_r2_name(name):
            return super().exists(name)
        return self.local_storage.exists(name)

    def open(self, name, mode='rb'):
        if is_cloudflare_r2_name(name):
            return super().open(name, mode)
        return self.local_storage.open(name, mode)

    def delete(self, name):
        if not name:
            return
        if is_cloudflare_r2_name(name):
            super().delete(name)
            return
        self.local_storage.delete(name)

    def url(self, name, parameters=None, expire=None, http_method=None):
        if is_cloudflare_r2_name(name):
            return super().url(
                name,
                parameters=parameters,
                expire=expire,
                http_method=http_method,
            )
        return self.local_storage.url(name)

    def size(self, name):
        if is_cloudflare_r2_name(name):
            return super().size(name)
        return self.local_storage.size(name)

    def get_modified_time(self, name):
        if is_cloudflare_r2_name(name):
            return super().get_modified_time(name)
        return self.local_storage.get_modified_time(name)

    def get_accessed_time(self, name):
        if is_cloudflare_r2_name(name):
            return super().get_accessed_time(name)
        return self.local_storage.get_accessed_time(name)

    def get_created_time(self, name):
        if is_cloudflare_r2_name(name):
            return super().get_created_time(name)
        return self.local_storage.get_created_time(name)
