"""Chat-related Pydantic schemas."""

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
from app.schemas.user import UserMinimal


class MessageStatus(str, Enum):
    """Message delivery status."""

    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"


class MessageCreate(BaseModel):
    """Schema for sending a message."""

    content: str = Field(..., min_length=1, max_length=5000)
    reply_to_id: Optional[int] = None
    media_type: Optional[str] = None
    media_url: Optional[str] = None
    media_thumbnail_url: Optional[str] = None
    media_duration: Optional[int] = None
    media_file_name: Optional[str] = None
    media_file_size: Optional[int] = None


class MessageReactionResponse(BaseModel):
    """Reaction data for a message."""

    id: int
    emoji: str
    user_id: int
    user: Optional[UserMinimal] = None
    created_at: datetime

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    """Message data returned in responses."""

    id: int
    conversation_id: int
    content: str
    status: MessageStatus = MessageStatus.SENT
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    read: bool = False  # Keep for backward compatibility
    created_at: datetime
    updated_at: Optional[datetime] = None
    sender: UserMinimal

    # Reply support
    reply_to_id: Optional[int] = None
    reply_to: Optional["MessageResponse"] = None

    # Media support
    media_type: Optional[str] = None
    media_url: Optional[str] = None
    media_thumbnail_url: Optional[str] = None
    media_duration: Optional[int] = None
    media_file_name: Optional[str] = None
    media_file_size: Optional[int] = None

    # Forward support
    forwarded_from_id: Optional[int] = None

    # Delete support
    is_deleted: bool = False
    deleted_at: Optional[datetime] = None
    deleted_for_everyone: bool = False

    # Reactions
    reactions: List[MessageReactionResponse] = []

    class Config:
        from_attributes = True


class ConversationCreate(BaseModel):
    """Schema for starting a conversation."""

    user_id: int  # The other user


class ConversationResponse(BaseModel):
    """Conversation data returned in responses."""

    id: int
    created_at: datetime
    updated_at: datetime
    other_user: UserMinimal
    last_message: Optional[MessageResponse] = None
    unread_count: int = 0

    class Config:
        from_attributes = True


class ConversationListResponse(BaseModel):
    """List of conversations."""

    conversations: List[ConversationResponse]


class MessageListResponse(BaseModel):
    """Paginated list of messages."""

    messages: List[MessageResponse]
    has_more: bool = False


# WebSocket message types
class WSMessage(BaseModel):
    """WebSocket message format."""

    type: str  # send_message, typing, read_receipt, etc.
    data: dict


class WSSendMessage(BaseModel):
    """WebSocket send message payload."""

    conversation_id: int
    content: str
    client_msg_id: Optional[str] = None  # Temp ID from client for optimistic updates
    reply_to_id: Optional[int] = None
    media_type: Optional[str] = None
    media_url: Optional[str] = None
    media_thumbnail_url: Optional[str] = None
    media_duration: Optional[int] = None
    media_file_name: Optional[str] = None
    media_file_size: Optional[int] = None


class WSTyping(BaseModel):
    """WebSocket typing indicator payload."""

    conversation_id: int


class WSReadReceipt(BaseModel):
    """WebSocket read receipt payload."""

    conversation_id: int
    message_ids: List[int]  # Changed from single ID to list


class WSReaction(BaseModel):
    """WebSocket reaction payload."""

    message_id: int
    emoji: Optional[str] = None  # None to remove reaction


class WSDeleteMessage(BaseModel):
    """WebSocket delete message payload."""

    message_id: int
    delete_for_everyone: bool = False


class WSForwardMessage(BaseModel):
    """WebSocket forward message payload."""

    message_id: int
    to_conversation_ids: List[int]
