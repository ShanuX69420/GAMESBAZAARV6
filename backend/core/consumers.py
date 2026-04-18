"""
WebSocket consumer for real-time chat.
"""

import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from .models import Conversation, Message


class ChatConsumer(AsyncJsonWebsocketConsumer):
    """Handles real-time messaging for a conversation."""

    async def connect(self):
        self.user = self.scope['user']
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']

        # Reject unauthenticated users
        if isinstance(self.user, AnonymousUser):
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
        await self.accept()

        # Mark unread messages as read
        await self.mark_messages_read()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive_json(self, content):
        """Handle incoming message from WebSocket client."""
        message_type = content.get('type')

        if message_type == 'chat_message':
            text = content.get('content', '').strip()
            if not text:
                return

            # Save to database
            msg_data = await self.save_message(text)

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
        # Add is_mine flag for the receiving client
        msg['is_mine'] = (msg['sender_id'] == self.user.id)
        await self.send_json({
            'type': 'new_message',
            'message': msg,
        })

    # ── Database helpers ─────────────────────────────────────────────────────

    @database_sync_to_async
    def check_participant(self):
        return Conversation.objects.filter(
            id=self.conversation_id, participants=self.user
        ).exists()

    @database_sync_to_async
    def save_message(self, content):
        conversation = Conversation.objects.get(id=self.conversation_id)
        msg = Message.objects.create(
            conversation=conversation,
            sender=self.user,
            content=content,
        )
        conversation.save()  # Update updated_at
        return {
            'id': msg.id,
            'sender_id': msg.sender.id,
            'sender_name': msg.sender.username,
            'content': msg.content,
            'is_read': msg.is_read,
            'created_at': msg.created_at.isoformat(),
        }

    @database_sync_to_async
    def mark_messages_read(self):
        Message.objects.filter(
            conversation_id=self.conversation_id,
            is_read=False,
        ).exclude(sender=self.user).update(is_read=True)
