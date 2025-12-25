"""Chat-related Pydantic schemas."""
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List
from app.schemas.user import UserMinimal


class MessageCreate(BaseModel):
    """Schema for sending a message."""
    content: str = Field(..., min_length=1, max_length=5000)


class MessageResponse(BaseModel):
    """Message data returned in responses."""
    id: int
    conversation_id: int
    content: str
    read: bool
    created_at: datetime
    sender: UserMinimal
    
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


class WSTyping(BaseModel):
    """WebSocket typing indicator payload."""
    conversation_id: int


class WSReadReceipt(BaseModel):
    """WebSocket read receipt payload."""
    conversation_id: int
    message_id: int
