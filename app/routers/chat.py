"""Chat routes: conversations and messages."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import selectinload
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.models.user import User
from app.models.chat import Conversation, ConversationMember, Message
from app.schemas.chat import (
    ConversationCreate, ConversationResponse, ConversationListResponse,
    MessageCreate, MessageResponse, MessageListResponse
)
from app.schemas.user import UserMinimal
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/conversations", tags=["Chat"])


@router.get("", response_model=ConversationListResponse)
async def get_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all conversations for current user.
    
    Returns conversations with:
    - Other participant info
    - Last message
    - Unread count
    
    Ordered by most recent activity.
    """
    # Get conversation IDs for current user
    result = await db.execute(
        select(ConversationMember.conversation_id)
        .where(ConversationMember.user_id == current_user.id)
    )
    conversation_ids = [r[0] for r in result.fetchall()]
    
    if not conversation_ids:
        return ConversationListResponse(conversations=[])
    
    # Get conversations with members
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.members).selectinload(ConversationMember.user))
        .where(Conversation.id.in_(conversation_ids))
        .order_by(Conversation.updated_at.desc())
    )
    conversations = result.scalars().all()
    
    conversation_responses = []
    for conv in conversations:
        # Find the other user
        other_user = None
        for member in conv.members:
            if member.user_id != current_user.id:
                other_user = member.user
                break
        
        if not other_user:
            continue
        
        # Get last message
        last_msg_result = await db.execute(
            select(Message)
            .options(selectinload(Message.sender))
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        last_message = last_msg_result.scalar_one_or_none()
        
        # Get unread count
        unread_count = await db.scalar(
            select(func.count(Message.id)).where(
                Message.conversation_id == conv.id,
                Message.sender_id != current_user.id,
                Message.read == False
            )
        )
        
        last_msg_response = None
        if last_message:
            last_msg_response = MessageResponse(
                id=last_message.id,
                conversation_id=last_message.conversation_id,
                content=last_message.content,
                read=last_message.read,
                created_at=last_message.created_at,
                sender=UserMinimal.model_validate(last_message.sender)
            )
        
        conversation_responses.append(ConversationResponse(
            id=conv.id,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            other_user=UserMinimal.model_validate(other_user),
            last_message=last_msg_response,
            unread_count=unread_count or 0
        ))
    
    return ConversationListResponse(conversations=conversation_responses)


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_or_get_conversation(
    data: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Start a new conversation or get existing one.
    
    If conversation between these users exists, returns it.
    Otherwise creates a new one.
    """
    if data.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot start conversation with yourself")
    
    # Check other user exists
    result = await db.execute(select(User).where(User.id == data.user_id))
    other_user = result.scalar_one_or_none()
    
    if not other_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if conversation exists
    # Find conversations where both users are members
    subq1 = select(ConversationMember.conversation_id).where(
        ConversationMember.user_id == current_user.id
    )
    subq2 = select(ConversationMember.conversation_id).where(
        ConversationMember.user_id == data.user_id
    )
    
    result = await db.execute(
        select(Conversation).where(
            Conversation.id.in_(subq1),
            Conversation.id.in_(subq2)
        )
    )
    existing_conv = result.scalar_one_or_none()
    
    if existing_conv:
        return ConversationResponse(
            id=existing_conv.id,
            created_at=existing_conv.created_at,
            updated_at=existing_conv.updated_at,
            other_user=UserMinimal.model_validate(other_user),
            last_message=None,
            unread_count=0
        )
    
    # Create new conversation
    conversation = Conversation()
    db.add(conversation)
    await db.flush()
    
    # Add members
    member1 = ConversationMember(conversation_id=conversation.id, user_id=current_user.id)
    member2 = ConversationMember(conversation_id=conversation.id, user_id=data.user_id)
    db.add(member1)
    db.add(member2)
    await db.flush()
    await db.refresh(conversation)
    
    return ConversationResponse(
        id=conversation.id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        other_user=UserMinimal.model_validate(other_user),
        last_message=None,
        unread_count=0
    )


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
async def get_messages(
    conversation_id: int,
    cursor: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get messages in a conversation with pagination."""
    # Verify user is member
    result = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == current_user.id
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this conversation")
    
    # Build query
    query = select(Message).options(selectinload(Message.sender)).where(
        Message.conversation_id == conversation_id
    )
    
    if cursor:
        try:
            cursor_time = datetime.fromisoformat(cursor)
            query = query.where(Message.created_at < cursor_time)
        except ValueError:
            pass
    
    query = query.order_by(Message.created_at.desc()).limit(limit + 1)
    
    result = await db.execute(query)
    messages = result.scalars().all()
    
    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]
    
    # Mark messages as read
    for msg in messages:
        if msg.sender_id != current_user.id and not msg.read:
            msg.read = True
    await db.flush()
    
    message_responses = [
        MessageResponse(
            id=msg.id,
            conversation_id=msg.conversation_id,
            content=msg.content,
            read=msg.read,
            created_at=msg.created_at,
            sender=UserMinimal.model_validate(msg.sender)
        )
        for msg in reversed(messages)  # Return in chronological order
    ]
    
    return MessageListResponse(messages=message_responses, has_more=has_more)


@router.post("/{conversation_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    conversation_id: int,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Send a message in a conversation."""
    # Verify user is member
    result = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == current_user.id
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this conversation")
    
    # Create message
    message = Message(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=data.content
    )
    db.add(message)
    
    # Update conversation timestamp
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conversation = result.scalar_one()
    conversation.updated_at = datetime.utcnow()
    
    await db.flush()
    await db.refresh(message)
    
    # Build message response
    message_response = MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        content=message.content,
        read=message.read,
        created_at=message.created_at,
        sender=UserMinimal.model_validate(current_user)
    )
    
    # Broadcast via WebSocket to other conversation members
    try:
        from app.websocket.manager import manager
        
        # Get other members
        result = await db.execute(
            select(ConversationMember.user_id).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id != current_user.id
            )
        )
        other_user_ids = [r[0] for r in result.fetchall()]
        
        # Broadcast to recipients
        ws_message = {
            "type": "new_message",
            "message": {
                "id": message.id,
                "conversation_id": message.conversation_id,
                "content": message.content,
                "read": message.read,
                "created_at": message.created_at.isoformat(),
                "sender": {
                    "id": current_user.id,
                    "username": current_user.username,
                    "display_name": current_user.display_name,
                    "avatar_url": current_user.avatar_url
                }
            }
        }
        
        for recipient_id in other_user_ids:
            await manager.send_personal_message(recipient_id, ws_message)
    except Exception as e:
        # Don't fail the request if WebSocket broadcast fails
        print(f"WebSocket broadcast error: {e}")
    
    return message_response


@router.patch("/{conversation_id}/read")
async def mark_conversation_read(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark all messages in conversation as read."""
    # Verify membership
    result = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == current_user.id
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member")
    
    # Mark unread messages as read
    result = await db.execute(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.sender_id != current_user.id,
            Message.read == False
        )
    )
    messages = result.scalars().all()
    
    for msg in messages:
        msg.read = True
    
    await db.flush()
    
    return {"message": "Marked as read", "count": len(messages)}
