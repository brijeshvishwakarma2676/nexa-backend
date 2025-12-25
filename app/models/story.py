"""Story and StoryView models."""
from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base
from app.config import settings


class Story(Base):
    """Story model with 24-hour expiration."""
    __tablename__ = "stories"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=True)  # Text content (optional)
    image_url = Column(String(500), nullable=True)  # Image URL (optional)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(hours=settings.STORY_EXPIRY_HOURS))
    
    # Relationships
    author = relationship("User", back_populates="stories")
    views = relationship("StoryView", back_populates="story", cascade="all, delete-orphan")
    
    @property
    def is_expired(self) -> bool:
        """Check if story has expired."""
        return datetime.utcnow() > self.expires_at


class StoryView(Base):
    """Track who viewed a story."""
    __tablename__ = "story_views"
    
    id = Column(Integer, primary_key=True, index=True)
    story_id = Column(Integer, ForeignKey("stories.id", ondelete="CASCADE"), nullable=False)
    viewer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    viewed_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    story = relationship("Story", back_populates="views")
    viewer = relationship("User")
    
    __table_args__ = (
        UniqueConstraint("story_id", "viewer_id", name="unique_story_view"),
    )
