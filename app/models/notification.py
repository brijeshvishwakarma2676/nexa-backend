"""Notification model."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.database import Base
import enum


class NotificationType(str, enum.Enum):
    """Types of notifications."""
    LIKE = "like"
    COMMENT = "comment"
    FOLLOW = "follow"
    MENTION = "mention"


class Notification(Base):
    """User notification."""
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)  # Recipient
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)  # Who triggered
    type = Column(String(50), nullable=False)  # NotificationType value
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=True)  # Related post (optional)
    read = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="notifications")
    actor = relationship("User", foreign_keys=[actor_id])
    post = relationship("Post")
