"""User-related Pydantic schemas."""

from datetime import datetime, date
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from enum import Enum


class RelationshipStatus(str, Enum):
    """Relationship status between users."""

    NONE = "none"
    FOLLOWING = "following"
    PENDING_SENT = "pending_sent"
    PENDING_RECEIVED = "pending_received"


# Base schemas
class UserBase(BaseModel):
    """Base user fields."""

    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")


class UserCreate(UserBase):
    """Schema for user registration."""

    password: str = Field(..., min_length=6, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=100)
    birthday: date  # Mandatory. Must be at least 13 years old.


class UserLogin(BaseModel):
    """Schema for user login."""

    email: EmailStr
    password: str


class PasswordChange(BaseModel):
    """Schema for changing user password."""

    current_password: str
    new_password: str = Field(..., min_length=6, max_length=100)


class UserUpdate(BaseModel):
    """Schema for updating user profile."""

    display_name: Optional[str] = Field(None, max_length=100)
    bio: Optional[str] = Field(None, max_length=500)
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    is_private: Optional[bool] = None
    # About section
    workplace: Optional[str] = Field(None, max_length=200)
    education: Optional[str] = Field(None, max_length=200)
    location: Optional[str] = Field(None, max_length=100)
    hometown: Optional[str] = Field(None, max_length=100)
    relationship_status: Optional[str] = Field(None, max_length=50)
    website: Optional[str] = Field(None, max_length=200)


# Response schemas
class UserResponse(BaseModel):
    """User data returned in responses."""

    id: int
    email: EmailStr
    username: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    birthday: Optional[date] = None
    is_private: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class UserProfileResponse(UserResponse):
    """Extended user profile with stats."""

    posts_count: Optional[int] = 0
    followers_count: Optional[int] = 0
    following_count: Optional[int] = 0
    is_following: bool = False
    relationship_status: str = "none"
    is_accessible: bool = True
    # About section
    workplace: Optional[str] = None
    education: Optional[str] = None
    location: Optional[str] = None
    hometown: Optional[str] = None
    user_relationship_status: Optional[str] = None  # renamed to avoid conflict
    website: Optional[str] = None


class UserMinimal(BaseModel):
    """Minimal user info for embedding in other responses."""

    id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True


class UserSearchResult(UserMinimal):
    """User search result with relationship status."""

    is_private: bool = False
    relationship_status: str = "none"


class UserSearchResponse(BaseModel):
    """Search results response."""

    users: List[UserSearchResult]
    total: int
    has_more: bool = False


# Follow request schemas
class FollowRequestResponse(BaseModel):
    """Follow request data."""

    id: int
    requester: UserMinimal
    created_at: datetime

    class Config:
        from_attributes = True


class FollowRequestListResponse(BaseModel):
    """List of follow requests."""

    requests: List[FollowRequestResponse]
    total: int


class SentRequestResponse(BaseModel):
    """Sent request data (outgoing)."""

    id: int
    target: UserMinimal
    created_at: datetime

    class Config:
        from_attributes = True


class SentRequestListResponse(BaseModel):
    """List of sent requests."""

    requests: List[SentRequestResponse]
    total: int


class FollowActionResponse(BaseModel):
    """Response after follow action."""

    success: bool
    relationship_status: str
    message: str


# Token schemas
class Token(BaseModel):
    """JWT token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: int  # user_id
    exp: datetime
    type: str  # "access" or "refresh"


class RefreshTokenRequest(BaseModel):
    """Request to refresh access token."""

    refresh_token: str


class AuthResponse(BaseModel):
    """Authentication response with user and tokens."""

    user: UserResponse
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
