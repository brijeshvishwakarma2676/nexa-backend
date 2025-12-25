"""Story-related Pydantic schemas."""
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List
from app.schemas.user import UserMinimal


class StoryCreate(BaseModel):
    """Schema for creating a story."""
    content: Optional[str] = Field(None, max_length=500)
    image_url: Optional[str] = None


class StoryResponse(BaseModel):
    """Story data returned in responses."""
    id: int
    content: Optional[str] = None
    image_url: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    author: UserMinimal
    views_count: int = 0
    is_viewed: bool = False
    
    class Config:
        from_attributes = True


class StoryGroupResponse(BaseModel):
    """Stories grouped by user."""
    user: UserMinimal
    stories: List[StoryResponse]
    all_seen: bool = False
    latest_story_at: datetime


class StoryListResponse(BaseModel):
    """List of story groups."""
    story_groups: List[StoryGroupResponse]


class StoryViewResponse(BaseModel):
    """Story view data."""
    viewer: UserMinimal
    viewed_at: datetime
    
    class Config:
        from_attributes = True
