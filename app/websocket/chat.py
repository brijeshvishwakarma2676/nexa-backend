"""WebSocket endpoint for real-time chat."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from datetime import datetime
import json

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.chat import (
    Conversation,
    ConversationMember,
    Message,
    MessageReaction,
    MessageStatus,
)
from app.utils.auth import decode_token
from app.websocket.manager import manager

router = APIRouter()


async def get_user_from_token(token: str) -> User | None:
    """Validate token and get user."""
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == int(user_id)))
        return result.scalar_one_or_none()


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket endpoint for real-time chat.

    Message Types:

    Client -> Server:
    - send_message: { type: "send_message", conversation_id: int, content: str, client_msg_id: str, reply_to_id?: int, media_*?: ... }
    - typing: { type: "typing", conversation_id: int }
    - mark_read: { type: "mark_read", message_ids: [int] }
    - react: { type: "react", message_id: int, emoji: str|null }
    - delete_message: { type: "delete_message", message_id: int, delete_for_everyone: bool }
    - forward_message: { type: "forward_message", message_id: int, to_conversation_ids: [int] }

    Server -> Client:
    - new_message: { type: "new_message", message: {...} }
    - message_sent: { type: "message_sent", message: {...} }
    - message_delivered: { type: "message_delivered", message_id: int, delivered_at: str }
    - message_read: { type: "message_read", message_id: int, read_at: str, read_by: int }
    - user_typing: { type: "user_typing", conversation_id: int, user_id: int }
    - message_reaction_update: { type: "message_reaction_update", message_id: int, reactions: [...] }
    - message_deleted: { type: "message_deleted", message_id: int, delete_for_everyone: bool }
    - user_online: { type: "user_online", user_id: int }
    - user_offline: { type: "user_offline", user_id: int }
    """
    # Get token from query params
    token = websocket.query_params.get("token")

    # Accept the connection first
    await websocket.accept()

    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    # Validate user
    user = await get_user_from_token(token)
    if not user:
        await websocket.close(code=4001, reason="Invalid token")
        return

    # Connect
    await manager.connect(websocket, user.id)

    # Initialize contact_ids
    contact_ids = []

    try:
        # Notify contacts that user is online
        async with AsyncSessionLocal() as db:
            # Get user's conversation IDs first
            user_convs = await db.execute(
                select(ConversationMember.conversation_id).where(
                    ConversationMember.user_id == user.id
                )
            )
            conv_ids = [r[0] for r in user_convs.fetchall()]

            if conv_ids:
                # Get other members in those conversations
                result = await db.execute(
                    select(ConversationMember.user_id).where(
                        ConversationMember.conversation_id.in_(conv_ids),
                        ConversationMember.user_id != user.id,
                    )
                )
                contact_ids = list(set(r[0] for r in result.fetchall()))

        if contact_ids:
            await manager.broadcast_to_users(
                contact_ids, {"type": "user_online", "user_id": user.id}
            )

        # Handle incoming messages
        while True:
            data = await websocket.receive_text()
            try:
                message_data = json.loads(data)
                await handle_websocket_message(user.id, message_data)
            except json.JSONDecodeError:
                pass
            except Exception as e:
                print(f"WebSocket error: {e}")

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, user.id)

        # Notify contacts that user is offline
        if contact_ids and not manager.is_online(user.id):
            await manager.broadcast_to_users(
                contact_ids, {"type": "user_offline", "user_id": user.id}
            )


async def handle_websocket_message(user_id: int, data: dict):
    """Handle incoming WebSocket message."""
    msg_type = data.get("type")

    if msg_type == "send_message":
        await handle_send_message(user_id, data)
    elif msg_type == "typing":
        await handle_typing(user_id, data)
    elif msg_type == "mark_read":
        await handle_mark_read(user_id, data)
    elif msg_type == "react":
        await handle_react_message(user_id, data)
    elif msg_type == "delete_message":
        await handle_delete_message(user_id, data)
    elif msg_type == "forward_message":
        await handle_forward_message(user_id, data)
    # Backward compatibility
    elif msg_type == "read_receipt":
        await handle_read_receipt(user_id, data)


async def handle_send_message(user_id: int, data: dict):
    """Handle send_message WebSocket event with delivery tracking."""
    conversation_id = data.get("conversation_id")
    content = data.get("content", "").strip()
    client_msg_id = data.get("client_msg_id")
    reply_to_id = data.get("reply_to_id")
    media_type = data.get("media_type")
    media_url = data.get("media_url")
    media_thumbnail_url = data.get("media_thumbnail_url")
    media_duration = data.get("media_duration")
    media_file_name = data.get("media_file_name")
    media_file_size = data.get("media_file_size")

    # Allow empty content if media is present
    if not conversation_id or (not content and not media_url):
        return

    async with AsyncSessionLocal() as db:
        # Verify user is member
        result = await db.execute(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == user_id,
            )
        )
        if not result.scalar_one_or_none():
            return

        # Get sender info
        result = await db.execute(select(User).where(User.id == user_id))
        sender = result.scalar_one()

        # Create message with status SENT
        message = Message(
            conversation_id=conversation_id,
            sender_id=user_id,
            content=content or "",
            status=MessageStatus.SENT,
            reply_to_id=reply_to_id,
            media_type=media_type,
            media_url=media_url,
            media_thumbnail_url=media_thumbnail_url,
            media_duration=media_duration,
            media_file_name=media_file_name,
            media_file_size=media_file_size,
        )
        db.add(message)

        # Update conversation timestamp
        result = await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conversation = result.scalar_one()
        conversation.updated_at = datetime.utcnow()

        await db.commit()
        await db.refresh(message)

        # Build reply preview if replying
        reply_to_data = None
        if reply_to_id:
            result = await db.execute(
                select(Message, User)
                .join(User, Message.sender_id == User.id)
                .where(Message.id == reply_to_id)
            )
            row = result.first()
            if row:
                reply_msg, reply_sender = row
                reply_to_data = {
                    "id": reply_msg.id,
                    "content": (
                        reply_msg.content[:100] + "..."
                        if len(reply_msg.content) > 100
                        else reply_msg.content
                    ),
                    "sender": {
                        "id": reply_sender.id,
                        "display_name": reply_sender.display_name,
                    },
                }

        # Build message response
        message_response = {
            "id": message.id,
            "conversation_id": message.conversation_id,
            "content": message.content,
            "status": message.status.value,
            "delivered_at": None,
            "read_at": None,
            "read": message.read,
            "created_at": message.created_at.isoformat(),
            "updated_at": (
                message.updated_at.isoformat() if message.updated_at else None
            ),
            "sender": {
                "id": sender.id,
                "username": sender.username,
                "display_name": sender.display_name,
                "avatar_url": sender.avatar_url,
            },
            "reply_to_id": reply_to_id,
            "reply_to": reply_to_data,
            "media_type": message.media_type,
            "media_url": message.media_url,
            "media_thumbnail_url": message.media_thumbnail_url,
            "media_duration": message.media_duration,
            "media_file_name": message.media_file_name,
            "media_file_size": message.media_file_size,
            "is_deleted": False,
            "reactions": [],
            "client_msg_id": client_msg_id,
        }

        # Get other members and update their unread counts
        result = await db.execute(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id != user_id,
            )
        )
        other_members = result.scalars().all()
        other_user_ids = [m.user_id for m in other_members]

        # Update unread counts for recipients
        for member in other_members:
            member.unread_count = (member.unread_count or 0) + 1
        await db.commit()

        # Track if any recipient is online for delivery status
        delivered = False

        # Send to recipients
        for recipient_id in other_user_ids:
            if manager.is_online(recipient_id):
                delivered = True
                await manager.send_personal_message(
                    recipient_id, {"type": "new_message", "message": message_response}
                )

        # Update status to DELIVERED if at least one recipient is online
        if delivered:
            message.status = MessageStatus.DELIVERED
            message.delivered_at = datetime.utcnow()
            await db.commit()

            # Notify sender about delivery
            await manager.send_personal_message(
                user_id,
                {
                    "type": "message_delivered",
                    "message_id": message.id,
                    "delivered_at": message.delivered_at.isoformat(),
                },
            )

        # Confirm to sender
        message_response["status"] = message.status.value
        message_response["delivered_at"] = (
            message.delivered_at.isoformat() if message.delivered_at else None
        )
        await manager.send_personal_message(
            user_id, {"type": "message_sent", "message": message_response}
        )


async def handle_typing(user_id: int, data: dict):
    """Handle typing indicator."""
    conversation_id = data.get("conversation_id")
    if not conversation_id:
        return

    async with AsyncSessionLocal() as db:
        # Get other members
        result = await db.execute(
            select(ConversationMember.user_id).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id != user_id,
            )
        )
        other_user_ids = [r[0] for r in result.fetchall()]

    # Notify others
    for recipient_id in other_user_ids:
        await manager.send_personal_message(
            recipient_id,
            {
                "type": "user_typing",
                "conversation_id": conversation_id,
                "user_id": user_id,
            },
        )


async def handle_mark_read(user_id: int, data: dict):
    """Handle mark messages as read with status update."""
    message_ids = data.get("message_ids", [])

    if not message_ids:
        return

    async with AsyncSessionLocal() as db:
        # Get messages that user didn't send
        result = await db.execute(
            select(Message).where(
                Message.id.in_(message_ids),
                Message.sender_id != user_id,
                Message.status != MessageStatus.READ,
            )
        )
        messages = result.scalars().all()

        if not messages:
            return

        now = datetime.utcnow()
        for msg in messages:
            msg.status = MessageStatus.READ
            msg.read_at = now
            msg.read = True

        # Reset unread count for the user in the conversation
        conversation_id = messages[0].conversation_id
        result = await db.execute(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()
        if member:
            member.unread_count = 0
            member.last_read_message_id = max(m.id for m in messages)

        await db.commit()

        # Notify senders about read status
        sender_ids = set(msg.sender_id for msg in messages)
        for sender_id in sender_ids:
            sender_messages = [m for m in messages if m.sender_id == sender_id]
            for msg in sender_messages:
                await manager.send_personal_message(
                    sender_id,
                    {
                        "type": "message_read",
                        "message_id": msg.id,
                        "read_at": now.isoformat(),
                        "read_by": user_id,
                    },
                )


async def handle_read_receipt(user_id: int, data: dict):
    """Handle read receipt (backward compatibility)."""
    conversation_id = data.get("conversation_id")
    if not conversation_id:
        return

    async with AsyncSessionLocal() as db:
        # Get unread messages
        result = await db.execute(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.sender_id != user_id,
                Message.read == False,
            )
        )
        messages = result.scalars().all()

        if messages:
            message_ids = [m.id for m in messages]
            await handle_mark_read(user_id, {"message_ids": message_ids})


async def handle_react_message(user_id: int, data: dict):
    """Add or remove reaction to message."""
    message_id = data.get("message_id")
    emoji = data.get("emoji")  # None to remove

    if not message_id:
        return

    async with AsyncSessionLocal() as db:
        # Get message to verify it exists and get conversation
        result = await db.execute(select(Message).where(Message.id == message_id))
        message = result.scalar_one_or_none()
        if not message:
            return

        if emoji:
            # Add/update reaction
            result = await db.execute(
                select(MessageReaction).where(
                    MessageReaction.message_id == message_id,
                    MessageReaction.user_id == user_id,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.emoji = emoji
            else:
                reaction = MessageReaction(
                    message_id=message_id, user_id=user_id, emoji=emoji
                )
                db.add(reaction)
        else:
            # Remove reaction
            await db.execute(
                delete(MessageReaction).where(
                    MessageReaction.message_id == message_id,
                    MessageReaction.user_id == user_id,
                )
            )

        await db.commit()

        # Get all reactions for this message
        result = await db.execute(
            select(MessageReaction, User)
            .join(User, MessageReaction.user_id == User.id)
            .where(MessageReaction.message_id == message_id)
        )
        reactions = []
        for reaction, user in result.fetchall():
            reactions.append(
                {
                    "id": reaction.id,
                    "emoji": reaction.emoji,
                    "user_id": reaction.user_id,
                    "user": {
                        "id": user.id,
                        "display_name": user.display_name,
                        "avatar_url": user.avatar_url,
                    },
                    "created_at": reaction.created_at.isoformat(),
                }
            )

        # Broadcast to all conversation members
        result = await db.execute(
            select(ConversationMember.user_id).where(
                ConversationMember.conversation_id == message.conversation_id
            )
        )
        member_ids = [r[0] for r in result.fetchall()]

        for member_id in member_ids:
            await manager.send_personal_message(
                member_id,
                {
                    "type": "message_reaction_update",
                    "message_id": message_id,
                    "reactions": reactions,
                },
            )


async def handle_delete_message(user_id: int, data: dict):
    """Soft delete message."""
    message_id = data.get("message_id")
    delete_for_everyone = data.get("delete_for_everyone", False)

    if not message_id:
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Message).where(Message.id == message_id))
        message = result.scalar_one_or_none()

        if not message:
            return

        # Only sender can delete for everyone
        if delete_for_everyone and message.sender_id != user_id:
            return

        # User must be sender or recipient to delete
        result = await db.execute(
            select(ConversationMember).where(
                ConversationMember.conversation_id == message.conversation_id,
                ConversationMember.user_id == user_id,
            )
        )
        if not result.scalar_one_or_none():
            return

        message.is_deleted = True
        message.deleted_at = datetime.utcnow()
        message.deleted_for_everyone = delete_for_everyone

        if delete_for_everyone:
            message.content = "This message was deleted"

        await db.commit()

        # Notify conversation members
        result = await db.execute(
            select(ConversationMember.user_id).where(
                ConversationMember.conversation_id == message.conversation_id
            )
        )
        member_ids = [r[0] for r in result.fetchall()]

        for member_id in member_ids:
            await manager.send_personal_message(
                member_id,
                {
                    "type": "message_deleted",
                    "message_id": message_id,
                    "delete_for_everyone": delete_for_everyone,
                    "deleted_by": user_id,
                },
            )


async def handle_forward_message(user_id: int, data: dict):
    """Forward message to other conversations."""
    message_id = data.get("message_id")
    to_conversation_ids = data.get("to_conversation_ids", [])

    if not message_id or not to_conversation_ids:
        return

    async with AsyncSessionLocal() as db:
        # Get original message
        result = await db.execute(select(Message).where(Message.id == message_id))
        original = result.scalar_one_or_none()

        if not original or original.is_deleted:
            return

        # Get sender info
        result = await db.execute(select(User).where(User.id == user_id))
        sender = result.scalar_one()

        for conv_id in to_conversation_ids:
            # Verify user is member of target conversation
            result = await db.execute(
                select(ConversationMember).where(
                    ConversationMember.conversation_id == conv_id,
                    ConversationMember.user_id == user_id,
                )
            )
            if not result.scalar_one_or_none():
                continue

            # Create forwarded message
            forwarded = Message(
                conversation_id=conv_id,
                sender_id=user_id,
                content=original.content,
                status=MessageStatus.SENT,
                forwarded_from_id=original.id,
                media_type=original.media_type,
                media_url=original.media_url,
                media_thumbnail_url=original.media_thumbnail_url,
                media_duration=original.media_duration,
                media_file_name=original.media_file_name,
                media_file_size=original.media_file_size,
            )
            db.add(forwarded)
            await db.flush()

            # Update conversation timestamp
            result = await db.execute(
                select(Conversation).where(Conversation.id == conv_id)
            )
            conversation = result.scalar_one()
            conversation.updated_at = datetime.utcnow()

            # Build response
            message_response = {
                "id": forwarded.id,
                "conversation_id": conv_id,
                "content": forwarded.content,
                "status": forwarded.status.value,
                "created_at": forwarded.created_at.isoformat(),
                "sender": {
                    "id": sender.id,
                    "username": sender.username,
                    "display_name": sender.display_name,
                    "avatar_url": sender.avatar_url,
                },
                "forwarded_from_id": original.id,
                "media_type": forwarded.media_type,
                "media_url": forwarded.media_url,
                "is_deleted": False,
                "reactions": [],
            }

            # Send to all members
            result = await db.execute(
                select(ConversationMember.user_id).where(
                    ConversationMember.conversation_id == conv_id
                )
            )
            member_ids = [r[0] for r in result.fetchall()]

            for member_id in member_ids:
                msg_type = "message_sent" if member_id == user_id else "new_message"
                await manager.send_personal_message(
                    member_id, {"type": msg_type, "message": message_response}
                )

        await db.commit()
