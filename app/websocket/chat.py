"""WebSocket endpoint for real-time chat."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import json

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.chat import Conversation, ConversationMember, Message
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
    - send_message: { type: "send_message", conversation_id: int, content: str }
    - typing: { type: "typing", conversation_id: int }
    - read_receipt: { type: "read_receipt", conversation_id: int, message_id: int }
    
    Server -> Client:
    - new_message: { type: "new_message", message: {...} }
    - message_sent: { type: "message_sent", message: {...} }
    - user_typing: { type: "user_typing", conversation_id: int, user_id: int }
    - messages_read: { type: "messages_read", conversation_id: int, reader_id: int }
    - notification: { type: "notification", notification: {...} }
    - user_online: { type: "user_online", user_id: int }
    - user_offline: { type: "user_offline }
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
                select(ConversationMember.conversation_id)
                .where(ConversationMember.user_id == user.id)
            )
            conv_ids = [r[0] for r in user_convs.fetchall()]
            
            if conv_ids:
                # Get other members in those conversations
                result = await db.execute(
                    select(ConversationMember.user_id)
                    .where(
                        ConversationMember.conversation_id.in_(conv_ids),
                        ConversationMember.user_id != user.id
                    )
                )
                contact_ids = list(set(r[0] for r in result.fetchall()))
        
        if contact_ids:
            await manager.broadcast_to_users(contact_ids, {
                "type": "user_online",
                "user_id": user.id
            })
        
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
            await manager.broadcast_to_users(contact_ids, {
                "type": "user_offline",
                "user_id": user.id
            })


async def handle_websocket_message(user_id: int, data: dict):
    """Handle incoming WebSocket message."""
    msg_type = data.get("type")
    
    if msg_type == "send_message":
        await handle_send_message(user_id, data)
    elif msg_type == "typing":
        await handle_typing(user_id, data)
    elif msg_type == "read_receipt":
        await handle_read_receipt(user_id, data)


async def handle_send_message(user_id: int, data: dict):
    """Handle send_message WebSocket event."""
    conversation_id = data.get("conversation_id")
    content = data.get("content", "").strip()
    
    if not conversation_id or not content:
        return
    
    async with AsyncSessionLocal() as db:
        # Verify user is member
        result = await db.execute(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == user_id
            )
        )
        if not result.scalar_one_or_none():
            return
        
        # Get sender info
        result = await db.execute(select(User).where(User.id == user_id))
        sender = result.scalar_one()
        
        # Create message
        message = Message(
            conversation_id=conversation_id,
            sender_id=user_id,
            content=content
        )
        db.add(message)
        
        # Update conversation timestamp
        result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.scalar_one()
        conversation.updated_at = datetime.utcnow()
        
        await db.commit()
        await db.refresh(message)
        
        # Build message response
        message_response = {
            "id": message.id,
            "conversation_id": message.conversation_id,
            "content": message.content,
            "read": message.read,
            "created_at": message.created_at.isoformat(),
            "sender": {
                "id": sender.id,
                "username": sender.username,
                "display_name": sender.display_name,
                "avatar_url": sender.avatar_url
            }
        }
        
        # Get other members
        result = await db.execute(
            select(ConversationMember.user_id).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id != user_id
            )
        )
        other_user_ids = [r[0] for r in result.fetchall()]
        
        # Send to recipients
        for recipient_id in other_user_ids:
            await manager.send_personal_message(recipient_id, {
                "type": "new_message",
                "message": message_response
            })
        
        # Confirm to sender
        await manager.send_personal_message(user_id, {
            "type": "message_sent",
            "message": message_response
        })


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
                ConversationMember.user_id != user_id
            )
        )
        other_user_ids = [r[0] for r in result.fetchall()]
    
    # Notify others
    for recipient_id in other_user_ids:
        await manager.send_personal_message(recipient_id, {
            "type": "user_typing",
            "conversation_id": conversation_id,
            "user_id": user_id
        })


async def handle_read_receipt(user_id: int, data: dict):
    """Handle read receipt."""
    conversation_id = data.get("conversation_id")
    if not conversation_id:
        return
    
    async with AsyncSessionLocal() as db:
        # Mark messages as read
        result = await db.execute(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.sender_id != user_id,
                Message.read == False
            )
        )
        messages = result.scalars().all()
        
        for msg in messages:
            msg.read = True
        
        await db.commit()
        
        # Notify sender
        if messages:
            sender_id = messages[0].sender_id
            await manager.send_personal_message(sender_id, {
                "type": "messages_read",
                "conversation_id": conversation_id,
                "reader_id": user_id
            })
