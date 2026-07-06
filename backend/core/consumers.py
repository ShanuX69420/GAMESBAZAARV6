"""
WebSocket consumer for real-time chat.
"""

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from .models import Conversation, Message
from .services import (
    CHAT_MESSAGE_EMPTY_ERROR,
    CHAT_MESSAGE_NOT_TEXT_ERROR,
    CHAT_MESSAGE_TOO_LONG_ERROR,
    broadcast_chat_message_after_commit,
    chat_unread_cache_key,
    consume_chat_ws_message_quota,
    validate_chat_listing_reference,
    validate_chat_message_content,
)


class ChatConsumer(AsyncJsonWebsocketConsumer):
    """Handles real-time messaging for a conversation."""

    async def connect(self):
        self.user = self.scope['user']
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.ticket_conversation_id = self.scope.get('chat_ticket_conversation_id')

        # Reject unauthenticated users
        if isinstance(self.user, AnonymousUser):
            await self.close()
            return
        if int(self.conversation_id) != self.ticket_conversation_id:
            await self.close()
            return

        # Verify user is a participant
        is_participant = await self.check_participant()
        if not is_participant:
            await self.close()
            return

        # Join the conversation's channel group
        self.room_group_name = f'chat_{self.conversation_id}'
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)

        # Watch the other participant's presence so the client doesn't poll
        self.presence_group_names = [
            f'presence_{user_id}'
            for user_id in await self.get_other_participant_ids()
        ]
        for group_name in self.presence_group_names:
            await self.channel_layer.group_add(group_name, self.channel_name)

        accept_subprotocol = self.scope.get('chat_accept_subprotocol')
        if accept_subprotocol:
            await self.accept(subprotocol=accept_subprotocol)
        else:
            await self.accept()

        # Mark unread messages as read
        await self.mark_messages_read()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        for group_name in getattr(self, 'presence_group_names', []):
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def receive_json(self, content):
        """Handle incoming message from WebSocket client."""
        if not isinstance(content, dict):
            await self.send_chat_error('invalid_message', 'Message must be a JSON object.')
            return

        message_type = content.get('type')

        if message_type == 'chat_message':
            text, validation_error = validate_chat_message_content(content.get('content', ''))
            if validation_error == CHAT_MESSAGE_EMPTY_ERROR:
                return

            if await self.is_message_rate_limited():
                await self.send_chat_error(
                    'rate_limited',
                    'You are sending messages too quickly. Please wait a moment.',
                )
                return

            if validation_error:
                await self.send_chat_error(self.error_code_for(validation_error), validation_error)
                return

            # Save to database after resolving any server-trusted listing
            # reference. Broadcasting (this room + participants' inbox
            # sockets) happens centrally inside save_message.
            listing_error = await self.save_message(text, content.get('listing_id'))
            if listing_error:
                await self.send_chat_error('invalid_listing_reference', listing_error)
                return

        elif message_type == 'mark_read':
            await self.mark_messages_read()

    async def chat_message(self, event):
        """Send message to WebSocket client."""
        # Copy before mutating: with the Redis channel layer, consumers in the
        # same process receive the *same* dict object, so writing is_mine in
        # place races with the other participant's handler across the await
        # below (receiver would echo the sender's is_mine=True as "You").
        msg = dict(event['message'])
        is_mine = (msg['sender_id'] == self.user.id)
        msg['is_mine'] = is_mine

        # Auto-mark as read — user is actively in this chat
        if not is_mine:
            await self.mark_message_read(msg['id'])

        await self.send_json({
            'type': 'new_message',
            'message': msg,
        })

    async def presence_update(self, event):
        """Relay a watched participant's fresh last_active to the client."""
        await self.send_json({
            'type': 'presence',
            'user_id': event['user_id'],
            'last_active': event['last_active'],
        })

    # ── Database helpers ─────────────────────────────────────────────────────

    @database_sync_to_async
    def is_message_rate_limited(self):
        return not consume_chat_ws_message_quota(self.user.id, self.conversation_id)

    def error_code_for(self, validation_error):
        if validation_error == CHAT_MESSAGE_TOO_LONG_ERROR:
            return 'message_too_long'
        if validation_error == CHAT_MESSAGE_NOT_TEXT_ERROR:
            return 'invalid_message'
        return 'message_rejected'

    async def send_chat_error(self, code, message):
        await self.send_json({
            'type': 'error',
            'code': code,
            'error': message,
        })

    @database_sync_to_async
    def check_participant(self):
        return Conversation.objects.filter(
            id=self.conversation_id, participants=self.user
        ).exists()

    @database_sync_to_async
    def get_other_participant_ids(self):
        return list(
            Conversation.objects.get(id=self.conversation_id)
            .participants.exclude(id=self.user.id)
            .values_list('id', flat=True)
        )

    @database_sync_to_async
    def save_message(self, content, listing_id=None):
        conversation = Conversation.objects.get(id=self.conversation_id)
        referenced_listing, listing_error = validate_chat_listing_reference(
            listing_id,
            conversation_id=conversation.id,
        )
        if listing_error:
            return listing_error
        msg = Message.objects.create(
            conversation=conversation,
            sender=self.user,
            content=content,
            referenced_listing=referenced_listing,
            referenced_listing_title=referenced_listing.title if referenced_listing else '',
            referenced_listing_price=referenced_listing.price if referenced_listing else None,
        )
        conversation.save()  # Update updated_at
        broadcast_chat_message_after_commit(msg)
        return None

    @database_sync_to_async
    def mark_messages_read(self):
        updated = Message.objects.filter(
            conversation_id=self.conversation_id,
            is_read=False,
        ).exclude(sender=self.user).update(is_read=True)
        if updated:
            cache.delete(chat_unread_cache_key(self.user.id))

    @database_sync_to_async
    def mark_message_read(self, message_id):
        updated = Message.objects.filter(
            id=message_id,
            conversation_id=self.conversation_id,
            is_read=False,
        ).exclude(sender=self.user).update(is_read=True)
        if updated:
            cache.delete(chat_unread_cache_key(self.user.id))


class InboxConsumer(AsyncJsonWebsocketConsumer):
    """Per-user socket feeding the inbox sidebar: activity in any of the
    user's conversations plus presence of recent chat partners."""

    # Presence groups are joined per partner, so bound them to the partners
    # the sidebar realistically shows; older dots age out client-side.
    PRESENCE_WATCH_LIMIT = 100

    async def connect(self):
        self.user = self.scope['user']

        # Reject unauthenticated users (only inbox-scoped tickets pass)
        if isinstance(self.user, AnonymousUser):
            await self.close()
            return

        self.group_name = f'user_inbox_{self.user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)

        # Watch recent chat partners' presence so the sidebar dots stay live
        self.presence_group_names = [
            f'presence_{user_id}'
            for user_id in await self.get_recent_partner_ids()
        ]
        for group_name in self.presence_group_names:
            await self.channel_layer.group_add(group_name, self.channel_name)

        accept_subprotocol = self.scope.get('chat_accept_subprotocol')
        if accept_subprotocol:
            await self.accept(subprotocol=accept_subprotocol)
        else:
            await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        for group_name in getattr(self, 'presence_group_names', []):
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def inbox_conversation_updated(self, event):
        """Relay a compact "this conversation changed" notice to the client."""
        await self.send_json({
            'type': 'conversation_updated',
            'conversation_id': event['conversation_id'],
            'other_user_id': event['other_user_id'],
        })

    async def notification_created(self, event):
        """Relay a fresh in-app notification so the navbar bell is instant."""
        await self.send_json({
            'type': 'notification',
            'notification': event['notification'],
        })

    async def presence_update(self, event):
        """Relay a watched partner's fresh last_active to the client."""
        await self.send_json({
            'type': 'presence',
            'user_id': event['user_id'],
            'last_active': event['last_active'],
        })

    @database_sync_to_async
    def get_recent_partner_ids(self):
        recent_conversation_ids = list(
            Conversation.objects.filter(participants=self.user)
            .order_by('-updated_at')
            .values_list('id', flat=True)[:self.PRESENCE_WATCH_LIMIT]
        )
        return list(
            User.objects.filter(conversations__id__in=recent_conversation_ids)
            .exclude(id=self.user.id)
            .distinct()
            .values_list('id', flat=True)
        )
