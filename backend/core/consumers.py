"""
WebSocket consumer for real-time chat.
"""

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from .models import Conversation, Message
from .services import (
    CHAT_MESSAGE_EMPTY_ERROR,
    CHAT_MESSAGE_NOT_TEXT_ERROR,
    CHAT_MESSAGE_TOO_LONG_ERROR,
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

            # Save to database after resolving any server-trusted listing reference.
            msg_data, listing_error = await self.save_message(text, content.get('listing_id'))
            if listing_error:
                await self.send_chat_error('invalid_listing_reference', listing_error)
                return

            # Broadcast to all participants in the room
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat.message',
                    'message': msg_data,
                }
            )

        elif message_type == 'mark_read':
            await self.mark_messages_read()

    async def chat_message(self, event):
        """Send message to WebSocket client."""
        msg = event['message']
        is_mine = (msg['sender_id'] == self.user.id)
        msg['is_mine'] = is_mine

        # Auto-mark as read — user is actively in this chat
        if not is_mine:
            await self.mark_message_read(msg['id'])

        await self.send_json({
            'type': 'new_message',
            'message': msg,
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
    def save_message(self, content, listing_id=None):
        conversation = Conversation.objects.get(id=self.conversation_id)
        referenced_listing, listing_error = validate_chat_listing_reference(
            listing_id,
            conversation_id=conversation.id,
        )
        if listing_error:
            return None, listing_error
        msg = Message.objects.create(
            conversation=conversation,
            sender=self.user,
            content=content,
            referenced_listing=referenced_listing,
            referenced_listing_title=referenced_listing.title if referenced_listing else '',
            referenced_listing_price=referenced_listing.price if referenced_listing else None,
        )
        conversation.save()  # Update updated_at
        return {
            'id': msg.id,
            'sender_id': msg.sender.id,
            'sender_name': msg.sender.username,
            'content': msg.content,
            'image_url': msg.image.url if msg.image else None,
            'listing_reference': (
                {
                    'id': referenced_listing.id,
                    'title': msg.referenced_listing_title,
                    'price': str(msg.referenced_listing_price),
                }
                if referenced_listing else None
            ),
            'is_read': msg.is_read,
            'created_at': msg.created_at.isoformat(),
        }, None

    @database_sync_to_async
    def mark_messages_read(self):
        Message.objects.filter(
            conversation_id=self.conversation_id,
            is_read=False,
        ).exclude(sender=self.user).update(is_read=True)

    @database_sync_to_async
    def mark_message_read(self, message_id):
        Message.objects.filter(
            id=message_id,
            conversation_id=self.conversation_id,
            is_read=False,
        ).exclude(sender=self.user).update(is_read=True)
