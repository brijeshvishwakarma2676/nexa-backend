"""Chat models: Conversation, ConversationMember, Message, MessageReaction."""

from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Boolean,
    UniqueConstraint,
    Enum as SQLEnum,
)
from sqlalchemy.orm import relationship
from app.database import Base


class MessageStatus(str, PyEnum):
    """Message delivery status."""

    SENT = "SENT"  # Saved to DB
    DELIVERED = "DELIVERED"  # Delivered to recipient's device
    READ = "READ"  # Read by recipient


class Conversation(Base):
    """Conversation between users."""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    members = relationship(
        "ConversationMember",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class ConversationMember(Base):
    """Members of a conversation."""

    __tablename__ = "conversation_members"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    joined_at = Column(DateTime, default=datetime.utcnow)

    # Unread tracking
    unread_count = Column(Integer, default=0)
    last_read_message_id = Column(
        Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    conversation = relationship("Conversation", back_populates="members")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "user_id", name="unique_conversation_member"
        ),
    )


class Message(Base):
    """Chat message with delivery tracking and media support."""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    sender_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content = Column(Text, nullable=False)

    # Delivery status tracking
    status = Column(SQLEnum(MessageStatus), default=MessageStatus.SENT, nullable=False)
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    read = Column(Boolean, default=False)  # Keep for backward compatibility

    # Reply support
    reply_to_id = Column(
        Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )

    # Media support
    media_type = Column(String(50), nullable=True)  # 'image', 'video', 'audio', 'file'
    media_url = Column(String(500), nullable=True)
    media_thumbnail_url = Column(String(500), nullable=True)
    media_duration = Column(Integer, nullable=True)  # For audio/video in seconds
    media_file_name = Column(String(255), nullable=True)
    media_file_size = Column(Integer, nullable=True)  # In bytes

    # Forward support
    forwarded_from_id = Column(
        Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )

    # Delete support
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)
    deleted_for_everyone = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    sender = relationship("User", foreign_keys=[sender_id])
    reply_to = relationship(
        "Message", remote_side=[id], foreign_keys=[reply_to_id], backref="replies"
    )
    forwarded_from = relationship(
        "Message", remote_side=[id], foreign_keys=[forwarded_from_id]
    )
    reactions = relationship(
        "MessageReaction", back_populates="message", cascade="all, delete-orphan"
    )


class MessageReaction(Base):
    """Emoji reactions on messages."""

    __tablename__ = "message_reactions"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(
        Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    emoji = Column(String(10), nullable=False)  # 👍, ❤️, 😂, etc.
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    message = relationship("Message", back_populates="reactions")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="unique_message_reaction"),
    )
