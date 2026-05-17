"""
GamesBazaar URL configuration.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.http import Http404
from django.views.static import serve as static_serve
from core.storage_backends import AVATAR_CACHE_SECONDS, GAME_ICON_CACHE_SECONDS

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('core.urls')),
]

def cached_media_serve(request, path, document_root=None):
    """Serve media files with Cache-Control headers for dev performance."""
    try:
        response = static_serve(request, path, document_root=document_root)
    except SuspiciousFileOperation as exc:
        raise Http404 from exc

    normalized_path = str(path).replace('\\', '/').lstrip('/')
    if normalized_path.startswith('game_icons/'):
        response['Cache-Control'] = f'public, max-age={GAME_ICON_CACHE_SECONDS}'
    elif normalized_path.startswith('avatars/'):
        response['Cache-Control'] = f'private, max-age={AVATAR_CACHE_SECONDS}'
    else:
        response['Cache-Control'] = 'private, no-store'
    return response


# Serve media files in development with browser-friendly cache headers
if settings.DEBUG:
    from django.urls import re_path
    urlpatterns += [
        re_path(
            r'^media/(?P<path>.*)$',
            cached_media_serve,
            {'document_root': settings.MEDIA_ROOT},
        ),
    ]
