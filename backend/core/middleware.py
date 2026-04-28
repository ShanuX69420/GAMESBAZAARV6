"""
Chat ticket authentication middleware for Django Channels WebSocket connections.
Authenticates using ?ticket=<short_lived_chat_ticket> query parameter.
"""

from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.models import User
from .services import consume_chat_ws_ticket


@database_sync_to_async
def get_user_from_ticket(ticket_str):
    """Validate a short-lived chat ticket and return the user plus scoped conversation."""
    try:
        payload = consume_chat_ws_ticket(ticket_str)
        return User.objects.get(id=payload['user_id']), payload['conversation_id']
    except Exception:
        return AnonymousUser(), None


class ChatTicketAuthMiddleware(BaseMiddleware):
    """Middleware that authenticates WebSocket connections via scoped chat tickets."""

    async def __call__(self, scope, receive, send):
        query_string = scope.get('query_string', b'').decode()
        params = parse_qs(query_string)
        ticket_list = params.get('ticket', [])

        if ticket_list:
            user, conversation_id = await get_user_from_ticket(ticket_list[0])
            scope['user'] = user
            scope['chat_ticket_conversation_id'] = conversation_id
        else:
            scope['user'] = AnonymousUser()
            scope['chat_ticket_conversation_id'] = None

        return await super().__call__(scope, receive, send)
