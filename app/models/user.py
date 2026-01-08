"""User model and Follow relationship."""

from datetime import datetime
from enum import Enum
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Date,
    ForeignKey,
    UniqueConstraint,
    Boolean,
)
from sqlalchemy.orm import relationship
from app.database import Base


class FollowStatus(str, Enum):
    """Follow request status."""

    PENDING = "pending"
    ACTIVE = "active"
    REJECTED = "rejected"


class AuthProvider(str, Enum):
    """How the user authenticates."""

    LOCAL = "local"  # Email + password
    GOOGLE = "google"  # Google OAuth


class User(Base):
    """User account model."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(50), unique=True, index=True, nullable=False)

    # Only set for LOCAL users. Google users have this as NULL.
    password_hash = Column(String(255), nullable=True)

    # Only set for GOOGLE users. Local users have this as NULL.
    google_id = Column(String(255), unique=True, nullable=True)

    # Determines authentication method. See AuthProvider enum.
    auth_provider = Column(String(20), default=AuthProvider.LOCAL.value, nullable=False)

    # Profile info
    display_name = Column(String(100), nullable=True)
    bio = Column(String(500), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    cover_url = Column(String(500), nullable=True)

    # Mandatory for all users. Stored as Date (not DateTime).
    # Must be at least 13 years old at signup.
    birthday = Column(Date, nullable=True)  # Will be made mandatory after migration

    # About section
    workplace = Column(String(200), nullable=True)
    education = Column(String(200), nullable=True)
    location = Column(String(100), nullable=True)
    hometown = Column(String(100), nullable=True)
    relationship_status = Column(String(50), nullable=True)
    website = Column(String(200), nullable=True)

    # Privacy setting
    is_private = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    posts = relationship("Post", back_populates="author", cascade="all, delete-orphan")
    stories = relationship(
        "Story", back_populates="author", cascade="all, delete-orphan"
    )
    reels = relationship("Reel", back_populates="author", cascade="all, delete-orphan")
    comments = relationship(
        "Comment", back_populates="author", cascade="all, delete-orphan"
    )
    notifications = relationship(
        "Notification",
        foreign_keys="Notification.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # Following relationships
    followers = relationship(
        "Follow",
        foreign_keys="Follow.following_id",
        back_populates="following",
        cascade="all, delete-orphan",
    )
    following = relationship(
        "Follow",
        foreign_keys="Follow.follower_id",
        back_populates="follower",
        cascade="all, delete-orphan",
    )


class Follow(Base):
    """Follow relationship between users."""

    __tablename__ = "follows"

    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    following_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Status: pending (for private accounts), active (following), rejected
    status = Column(String(20), default=FollowStatus.ACTIVE.value, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    follower = relationship(
        "User", foreign_keys=[follower_id], back_populates="following"
    )
    following = relationship(
        "User", foreign_keys=[following_id], back_populates="followers"
    )

    __table_args__ = (
        UniqueConstraint("follower_id", "following_id", name="unique_follow"),
    )
