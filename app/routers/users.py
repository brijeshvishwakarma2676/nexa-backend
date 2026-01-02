"""User routes: profiles, follow/unfollow, followers/following lists, search, requests."""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from typing import List
import os
import uuid

from app.database import get_db
from app.config import settings
from app.models.user import User, Follow, FollowStatus
from app.models.post import Post
from app.models.notification import Notification, NotificationType
from app.schemas.user import (
    UserResponse, UserProfileResponse, UserUpdate, UserMinimal,
    UserSearchResult, UserSearchResponse, FollowRequestResponse,
    FollowRequestListResponse, FollowActionResponse,
    SentRequestResponse, SentRequestListResponse
)
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/users", tags=["Users"])


# ===============================
# HELPER: Get relationship status
# ===============================
async def get_relationship_status(current_user_id: int, target_user_id: int, db: AsyncSession) -> str:
    """
    Determine relationship status between two users.
    
    Returns:
    - "none": No relationship
    - "following": Actively following
    - "pending_sent": I sent a follow request (waiting)
    - "pending_received": They sent me a request (needs action)
    """
    if current_user_id == target_user_id:
        return "self"
    
    # Check if I follow them (outgoing)
    outgoing = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user_id,
            Follow.following_id == target_user_id
        )
    )
    outgoing_follow = outgoing.scalar_one_or_none()
    
    if outgoing_follow:
        if outgoing_follow.status == FollowStatus.ACTIVE.value:
            return "following"
        elif outgoing_follow.status == FollowStatus.PENDING.value:
            return "pending_sent"
    
    # Check if they requested to follow me (incoming)
    incoming = await db.execute(
        select(Follow).where(
            Follow.follower_id == target_user_id,
            Follow.following_id == current_user_id,
            Follow.status == FollowStatus.PENDING.value
        )
    )
    if incoming.scalar_one_or_none():
        return "pending_received"
    
    return "none"


# ===============================
# USER SEARCH
# ===============================
@router.get("/search/{query}", response_model=UserSearchResponse)
async def search_users(
    query: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Search users by username or display name.
    Returns relationship status for each result.
    """
    result = await db.execute(
        select(User).where(
            User.id != current_user.id,
            or_(
                User.username.ilike(f"%{query}%"),
                User.display_name.ilike(f"%{query}%")
            )
        ).limit(20)
    )
    users = result.scalars().all()
    
    search_results = []
    for user in users:
        rel_status = await get_relationship_status(current_user.id, user.id, db)
        search_results.append(UserSearchResult(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            is_private=user.is_private or False,
            relationship_status=rel_status
        ))
    
    return UserSearchResponse(users=search_results, total=len(search_results))


# ===============================
# FOLLOW / UNFOLLOW
# ===============================
@router.post("/{user_id}/follow", response_model=FollowActionResponse)
async def follow_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Follow a user.
    - Public accounts: Instant follow (status=active)
    - Private accounts: Request (status=pending)
    """
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")
    
    # Check target exists
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check existing relationship
    existing = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id
        )
    )
    existing_follow = existing.scalar_one_or_none()
    
    if existing_follow:
        if existing_follow.status == FollowStatus.ACTIVE.value:
            raise HTTPException(status_code=400, detail="Already following")
        elif existing_follow.status == FollowStatus.PENDING.value:
            raise HTTPException(status_code=400, detail="Request already sent")
        elif existing_follow.status == FollowStatus.REJECTED.value:
            # Allow re-request after rejection
            existing_follow.status = FollowStatus.PENDING.value
            await db.flush()
            return FollowActionResponse(
                success=True,
                relationship_status="pending_sent",
                message="Follow request sent"
            )
    
    # Determine status based on privacy
    follow_status = FollowStatus.PENDING.value if target_user.is_private else FollowStatus.ACTIVE.value
    
    follow = Follow(
        follower_id=current_user.id,
        following_id=user_id,
        status=follow_status
    )
    db.add(follow)
    
    # Create notification
    notification = Notification(
        user_id=user_id,
        actor_id=current_user.id,
        type=NotificationType.FOLLOW.value
    )
    db.add(notification)
    
    await db.flush()
    
    if follow_status == FollowStatus.ACTIVE.value:
        return FollowActionResponse(
            success=True,
            relationship_status="following",
            message="Now following"
        )
    else:
        return FollowActionResponse(
            success=True,
            relationship_status="pending_sent",
            message="Follow request sent"
        )


@router.delete("/{user_id}/follow", response_model=FollowActionResponse)
async def unfollow_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Unfollow a user or cancel pending request."""
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id
        )
    )
    follow = result.scalar_one_or_none()
    
    if not follow:
        raise HTTPException(status_code=400, detail="Not following this user")
    
    await db.delete(follow)
    
    return FollowActionResponse(
        success=True,
        relationship_status="none",
        message="Unfollowed successfully"
    )


# ===============================
# INCOMING REQUESTS
# ===============================
@router.get("/requests/incoming", response_model=FollowRequestListResponse)
async def get_incoming_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get pending follow requests where I am the target.
    Only shows requests I need to accept/reject.
    """
    result = await db.execute(
        select(Follow, User)
        .join(User, User.id == Follow.follower_id)
        .where(
            Follow.following_id == current_user.id,
            Follow.status == FollowStatus.PENDING.value
        )
        .order_by(Follow.created_at.desc())
    )
    rows = result.fetchall()
    
    requests = []
    for follow, requester in rows:
        requests.append(FollowRequestResponse(
            id=follow.id,
            requester=UserMinimal.model_validate(requester),
            created_at=follow.created_at
        ))
    
    return FollowRequestListResponse(requests=requests, total=len(requests))


@router.post("/requests/{request_id}/accept", response_model=FollowActionResponse)
async def accept_follow_request(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Accept a pending friend request.
    Creates mutual friendship: both users follow each other.
    """
    result = await db.execute(
        select(Follow).where(Follow.id == request_id)
    )
    follow = result.scalar_one_or_none()
    
    if not follow:
        raise HTTPException(status_code=404, detail="Request not found")
    
    # Verify I am the target
    if follow.following_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if follow.status != FollowStatus.PENDING.value:
        raise HTTPException(status_code=400, detail="Request already processed")
    
    # Accept the incoming request
    follow.status = FollowStatus.ACTIVE.value
    
    # Create reverse follow (I follow them back) for mutual friendship
    existing_reverse = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == follow.follower_id
        )
    )
    if not existing_reverse.scalar_one_or_none():
        reverse_follow = Follow(
            follower_id=current_user.id,
            following_id=follow.follower_id,
            status=FollowStatus.ACTIVE.value
        )
        db.add(reverse_follow)
    
    await db.flush()
    
    return FollowActionResponse(
        success=True,
        relationship_status="following",
        message="Friend request accepted"
    )


@router.delete("/requests/{request_id}", response_model=FollowActionResponse)
async def reject_follow_request(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Reject/delete a pending follow request.
    Removes the record entirely from DB.
    """
    result = await db.execute(
        select(Follow).where(Follow.id == request_id)
    )
    follow = result.scalar_one_or_none()
    
    if not follow:
        raise HTTPException(status_code=404, detail="Request not found")
    
    # Verify I am the target
    if follow.following_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.delete(follow)
    
    return FollowActionResponse(
        success=True,
        relationship_status="none",
        message="Request rejected"
    )


@router.get("/requests/sent", response_model=SentRequestListResponse)
async def get_sent_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get pending friend requests I have sent.
    """
    result = await db.execute(
        select(Follow, User)
        .join(User, User.id == Follow.following_id)
        .where(
            Follow.follower_id == current_user.id,
            Follow.status == FollowStatus.PENDING.value
        )
        .order_by(Follow.created_at.desc())
    )
    rows = result.fetchall()
    
    requests = []
    for follow, target in rows:
        requests.append(SentRequestResponse(
            id=follow.id,
            target=UserMinimal.model_validate(target),
            created_at=follow.created_at
        ))
    
    return SentRequestListResponse(requests=requests, total=len(requests))


@router.delete("/requests/{request_id}/cancel", response_model=FollowActionResponse)
async def cancel_sent_request(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Cancel a friend request I sent.
    """
    result = await db.execute(
        select(Follow).where(Follow.id == request_id)
    )
    follow = result.scalar_one_or_none()
    
    if not follow:
        raise HTTPException(status_code=404, detail="Request not found")
    
    # Verify I am the sender
    if follow.follower_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.delete(follow)
    
    return FollowActionResponse(
        success=True,
        relationship_status="none",
        message="Request cancelled"
    )


# ===============================
# EXISTING ENDPOINTS (Updated)
# ===============================
@router.get("/{username}", response_model=UserProfileResponse)
async def get_user_profile(
    username: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get user profile with stats and relationship status."""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Relationship status
    rel_status = await get_relationship_status(current_user.id, user.id, db)
    is_following = rel_status == "following"
    is_owner = current_user.id == user.id
    
    # Determine if viewer can access private content
    is_accessible = is_owner or is_following or not (user.is_private or False)
    
    # Counts (only active followers)
    if is_accessible:
        posts_count = await db.scalar(
            select(func.count(Post.id)).where(Post.user_id == user.id)
        )
        followers_count = await db.scalar(
            select(func.count(Follow.id)).where(
                Follow.following_id == user.id,
                Follow.status == FollowStatus.ACTIVE.value
            )
        )
        following_count = await db.scalar(
            select(func.count(Follow.id)).where(
                Follow.follower_id == user.id,
                Follow.status == FollowStatus.ACTIVE.value
            )
        )
    else:
        # Private profile, hide counts
        posts_count = None
        followers_count = None
        following_count = None
    
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        display_name=user.display_name,
        bio=user.bio,
        avatar_url=user.avatar_url,
        cover_url=user.cover_url,
        is_private=user.is_private or False,
        created_at=user.created_at,
        posts_count=posts_count,
        followers_count=followers_count,
        following_count=following_count,
        is_following=is_following,
        relationship_status=rel_status,
        is_accessible=is_accessible,
        # About section
        workplace=user.workplace,
        education=user.education,
        location=user.location,
        hometown=user.hometown,
        user_relationship_status=user.relationship_status,
        website=user.website
    )


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    update_data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update current user's profile."""
    update_dict = update_data.model_dump(exclude_unset=True)
    
    for field, value in update_dict.items():
        setattr(current_user, field, value)
    
    await db.flush()
    await db.refresh(current_user)
    
    return UserResponse.model_validate(current_user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete current user's account and all associated data."""
    await db.delete(current_user)
    return None


@router.post("/me/avatar", response_model=UserResponse)
async def upload_avatar_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Upload user avatar image to Cloudinary."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large")
    
    try:
        from app.utils.cloudinary import upload_avatar
        avatar_url = await upload_avatar(content, current_user.id)
        current_user.avatar_url = avatar_url
    except ValueError:
        # Fallback to local storage if Cloudinary not configured
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
        filename = f"avatar_{current_user.id}_{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(settings.UPLOAD_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(content)
        current_user.avatar_url = f"/uploads/{filename}"
    
    await db.flush()
    await db.refresh(current_user)
    
    return UserResponse.model_validate(current_user)


@router.post("/me/cover", response_model=UserResponse)
async def upload_cover_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Upload user cover image to Cloudinary."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large")
    
    # Process image to Facebook ideal dimensions (851x315)
    try:
        from app.utils.image_processing import process_cover_photo
        content = process_cover_photo(content)
    except Exception as e:
        # If processing fails (e.g. invalid image format), raise error
        raise HTTPException(status_code=400, detail=f"Invalid image format: {str(e)}")
    
    try:
        from app.utils.cloudinary import upload_cover
        cover_url = await upload_cover(content, current_user.id)
        current_user.cover_url = cover_url
    except ValueError:
        # Fallback to local storage if Cloudinary not configured
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        filename = f"cover_{current_user.id}_{uuid.uuid4().hex}.jpg"
        filepath = os.path.join(settings.UPLOAD_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(content)
        current_user.cover_url = f"/uploads/{filename}"
    
    await db.flush()
    await db.refresh(current_user)
    
    return UserResponse.model_validate(current_user)


@router.get("/{user_id}/followers", response_model=List[UserSearchResult])
async def get_followers(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of users who follow this user (active only)."""
    # Check if user exists and if we can view their followers
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check privacy permissions
    is_owner = current_user.id == user_id
    rel_status = await get_relationship_status(current_user.id, user_id, db)
    is_following = rel_status == "following"
    
    if target_user.is_private and not is_owner and not is_following:
        raise HTTPException(status_code=403, detail="This account is private")
    
    result = await db.execute(
        select(User)
        .join(Follow, Follow.follower_id == User.id)
        .where(
            Follow.following_id == user_id,
            Follow.status == FollowStatus.ACTIVE.value
        )
    )
    followers = result.scalars().all()
    
    results = []
    for f in followers:
        rel_status = await get_relationship_status(current_user.id, f.id, db)
        results.append(UserSearchResult(
            id=f.id,
            username=f.username,
            display_name=f.display_name,
            avatar_url=f.avatar_url,
            is_private=f.is_private or False,
            relationship_status=rel_status
        ))
    
    return results


@router.get("/{user_id}/following", response_model=List[UserSearchResult])
async def get_following(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of users this user follows (active only)."""
    # Check if user exists and if we can view who they follow
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check privacy permissions
    is_owner = current_user.id == user_id
    rel_status = await get_relationship_status(current_user.id, user_id, db)
    is_following = rel_status == "following"
    
    if target_user.is_private and not is_owner and not is_following:
        raise HTTPException(status_code=403, detail="This account is private")
    
    result = await db.execute(
        select(User)
        .join(Follow, Follow.following_id == User.id)
        .where(
            Follow.follower_id == user_id,
            Follow.status == FollowStatus.ACTIVE.value
        )
    )
    following = result.scalars().all()
    
    results = []
    for f in following:
        rel_status = await get_relationship_status(current_user.id, f.id, db)
        results.append(UserSearchResult(
            id=f.id,
            username=f.username,
            display_name=f.display_name,
            avatar_url=f.avatar_url,
            is_private=f.is_private or False,
            relationship_status=rel_status
        ))
    
    return results


# ===============================
# PHOTOS & FRIENDS
# ===============================

@router.get("/{user_id}/photos")
async def get_user_photos(
    user_id: int,
    limit: int = 9,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get photos from user's posts."""
    # Get posts with media
    result = await db.execute(
        select(Post)
        .where(Post.user_id == user_id, Post.image_url.isnot(None))
        .order_by(Post.created_at.desc())
        .limit(limit)
    )
    posts = result.scalars().all()
    
    photos = [{"id": p.id, "url": p.image_url} for p in posts if p.image_url]
    return {"photos": photos, "total": len(photos)}


@router.get("/{user_id}/friends")
async def get_user_friends(
    user_id: int,
    limit: int = 9,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get mutual friends (users who follow each other)."""
    # Users that user follows AND are followed by user
    result = await db.execute(
        select(User)
        .join(Follow, Follow.following_id == User.id)
        .where(
            Follow.follower_id == user_id,
            Follow.status == FollowStatus.ACTIVE.value,
            # Check if they also follow back
            User.id.in_(
                select(Follow.follower_id).where(
                    Follow.following_id == user_id,
                    Follow.status == FollowStatus.ACTIVE.value
                )
            )
        )
        .limit(limit)
    )
    friends = result.scalars().all()
    
    # Count total mutual friends
    count_result = await db.scalar(
        select(func.count(User.id))
        .join(Follow, Follow.following_id == User.id)
        .where(
            Follow.follower_id == user_id,
            Follow.status == FollowStatus.ACTIVE.value,
            User.id.in_(
                select(Follow.follower_id).where(
                    Follow.following_id == user_id,
                    Follow.status == FollowStatus.ACTIVE.value
                )
            )
        )
    )
    
    return {
        "friends": [
            {"id": f.id, "username": f.username, "display_name": f.display_name, "avatar_url": f.avatar_url}
            for f in friends
        ],
        "total": count_result or 0
    }
