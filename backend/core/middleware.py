"""
Chat ticket authentication middleware for Django Channels WebSocket connections.
Authenticates using a short-lived chat ticket.
"""

import base64
import binascii
from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.models import User
from .services import consume_chat_ws_ticket, consume_inbox_ws_ticket


CHAT_SUBPROTOCOL = 'gb.chat'
TICKET_SUBPROTOCOL_PREFIX = 'gb.ticket.'
INBOX_WS_PATH = '/ws/inbox/'


def ticket_from_subprotocols(subprotocols):
    for protocol in subprotocols or []:
        if not protocol.startswith(TICKET_SUBPROTOCOL_PREFIX):
            continue
        encoded = protocol[len(TICKET_SUBPROTOCOL_PREFIX):]
        padding = '=' * (-len(encoded) % 4)
        try:
            return base64.urlsafe_b64decode(
                f'{encoded}{padding}'.encode('ascii')
            ).decode('ascii')
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return None
    return None


@database_sync_to_async
def get_user_from_ticket(ticket_str):
    """Validate a short-lived chat ticket and return the user plus scoped conversation."""
    try:
        payload = consume_chat_ws_ticket(ticket_str)
        return User.objects.get(id=payload['user_id']), payload['conversation_id']
    except Exception:
        return AnonymousUser(), None


@database_sync_to_async
def get_user_from_inbox_ticket(ticket_str):
    """Validate a short-lived inbox ticket and return the user."""
    try:
        payload = consume_inbox_ws_ticket(ticket_str)
        return User.objects.get(id=payload['user_id'])
    except Exception:
        return AnonymousUser()


class ChatTicketAuthMiddleware(BaseMiddleware):
    """Middleware that authenticates WebSocket connections via scoped tickets.

    Chat sockets use conversation-scoped tickets; the inbox socket uses
    user-scoped tickets. The salts differ, so neither ticket kind can open
    the other socket.
    """

    async def __call__(self, scope, receive, send):
        subprotocols = scope.get('subprotocols') or []
        ticket = ticket_from_subprotocols(subprotocols)
        if ticket is None:
            query_string = scope.get('query_string', b'').decode()
            params = parse_qs(query_string)
            ticket_list = params.get('ticket', [])
            ticket = ticket_list[0] if ticket_list else None

        scope['user'] = AnonymousUser()
        scope['chat_ticket_conversation_id'] = None
        if ticket:
            if scope.get('path') == INBOX_WS_PATH:
                scope['user'] = await get_user_from_inbox_ticket(ticket)
            else:
                user, conversation_id = await get_user_from_ticket(ticket)
                scope['user'] = user
                scope['chat_ticket_conversation_id'] = conversation_id
        scope['chat_accept_subprotocol'] = (
            CHAT_SUBPROTOCOL if CHAT_SUBPROTOCOL in subprotocols else None
        )

        return await super().__call__(scope, receive, send)
