"""Notification-related Pydantic schemas."""
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List
from app.schemas.user import UserMinimal


class NotificationResponse(BaseModel):
    """Notification data returned in responses."""
    id: int
    type: str  # like, comment, follow, mention
    read: bool
    created_at: datetime
    actor: UserMinimal
    post_id: Optional[int] = None
    message: str = ""  # Human-readable message
    
    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    """List of notifications."""
    notifications: List[NotificationResponse]
    unread_count: int = 0


class NotificationCountResponse(BaseModel):
    """Unread notification count."""
    unread_count: int
