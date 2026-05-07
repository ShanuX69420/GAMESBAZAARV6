"""
ASGI config for gamesbazaar project.
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gamesbazaar.settings')
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator
from django.conf import settings
from django.core.asgi import get_asgi_application
from core.routing import websocket_urlpatterns
from core.middleware import ChatTicketAuthMiddleware

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': OriginValidator(
        ChatTicketAuthMiddleware(
            URLRouter(websocket_urlpatterns)
        ),
        settings.WEBSOCKET_ALLOWED_ORIGINS,
    ),
})
