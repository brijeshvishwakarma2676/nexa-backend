"""Post-related Pydantic schemas."""
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List
from app.schemas.user import UserMinimal


class PostCreate(BaseModel):
    """Schema for creating a post."""
    content: Optional[str] = Field(default="", max_length=5000)
    image_url: Optional[str] = None
    visibility: str = "public"  # public or followers


class PostUpdate(BaseModel):
    """Schema for updating a post."""
    content: Optional[str] = Field(None, min_length=1, max_length=5000)
    visibility: Optional[str] = None


class PostResponse(BaseModel):
    """Post data returned in responses."""
    id: int
    content: str
    image_url: Optional[str] = None
    visibility: str
    created_at: datetime
    updated_at: datetime
    author: UserMinimal
    likes_count: int = 0
    comments_count: int = 0
    is_liked: bool = False
    
    class Config:
        from_attributes = True


class PostListResponse(BaseModel):
    """Paginated list of posts."""
    posts: List[PostResponse]
    next_cursor: Optional[str] = None
    has_more: bool = False


# Like schemas
class LikeResponse(BaseModel):
    """Like response."""
    post_id: int
    likes_count: int
    is_liked: bool


# Comment schemas
class CommentCreate(BaseModel):
    """Schema for creating a comment."""
    content: str = Field(..., min_length=1, max_length=2000)
    parent_id: Optional[int] = None


class CommentResponse(BaseModel):
    """Comment data returned in responses."""
    id: int
    post_id: int
    content: str
    created_at: datetime
    author: UserMinimal
    parent_id: Optional[int] = None
    replies_count: int = 0
    
    class Config:
        from_attributes = True


class CommentListResponse(BaseModel):
    """List of comments."""
    comments: List[CommentResponse]
    total: int
