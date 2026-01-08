"""Reel-related Pydantic schemas."""
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List
from app.schemas.user import UserMinimal


class ReelCreate(BaseModel):
    """Schema for creating a reel."""
    caption: Optional[str] = Field(default="", max_length=2200)
    video_url: str
    thumbnail_url: Optional[str] = None
    duration: Optional[float] = None


class ReelResponse(BaseModel):
    """Reel data returned in responses."""
    id: int
    video_url: str
    thumbnail_url: Optional[str] = None
    caption: Optional[str] = None
    duration: Optional[float] = None
    views_count: int = 0
    created_at: datetime
    author: UserMinimal
    likes_count: int = 0
    comments_count: int = 0
    is_liked: bool = False
    
    class Config:
        from_attributes = True


class ReelListResponse(BaseModel):
    """Paginated list of reels."""
    reels: List[ReelResponse]
    next_cursor: Optional[str] = None
    has_more: bool = False


class ReelLikeResponse(BaseModel):
    """Like response for reels."""
    reel_id: int
    likes_count: int
    is_liked: bool


class ReelCommentCreate(BaseModel):
    """Schema for creating a reel comment."""
    content: str = Field(..., min_length=1, max_length=2000)
    parent_id: Optional[int] = None


class ReelCommentResponse(BaseModel):
    """Reel comment data returned in responses."""
    id: int
    reel_id: int
    content: str
    created_at: datetime
    author: UserMinimal
    parent_id: Optional[int] = None
    replies_count: int = 0
    
    class Config:
        from_attributes = True


class ReelCommentListResponse(BaseModel):
    """List of reel comments."""
    comments: List[ReelCommentResponse]
    total: int
