"""
ASGI config for gamesbazaar project.
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gamesbazaar.settings')

from django.core.asgi import get_asgi_application

application = get_asgi_application()
