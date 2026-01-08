"""Reel routes: CRUD, feed, likes, comments."""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.config import settings
from app.models.user import User
from app.models.reel import Reel, ReelLike, ReelComment
from app.models.notification import Notification, NotificationType
from app.schemas.reel import (
    ReelCreate, ReelResponse, ReelListResponse,
    ReelLikeResponse, ReelCommentCreate, ReelCommentResponse, ReelCommentListResponse
)
from app.schemas.user import UserMinimal
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/reels", tags=["Reels"])


def build_reel_response(reel: Reel, likes_count: int, comments_count: int, is_liked: bool) -> ReelResponse:
    """Build ReelResponse from Reel model."""
    return ReelResponse(
        id=reel.id,
        video_url=reel.video_url,
        thumbnail_url=reel.thumbnail_url,
        caption=reel.caption,
        duration=reel.duration,
        views_count=reel.views_count,
        created_at=reel.created_at,
        author=UserMinimal.model_validate(reel.author),
        likes_count=likes_count,
        comments_count=comments_count,
        is_liked=is_liked
    )


@router.post("/upload-video")
async def upload_reel_video(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """Upload a video for a reel to Cloudinary (video account)."""
    if not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="File must be a video")
    
    content = await file.read()
    
    # Max 50MB for videos
    max_video_size = 50 * 1024 * 1024
    if len(content) > max_video_size:
        raise HTTPException(status_code=400, detail="Video file too large (max 50MB)")
    
    try:
        from app.utils.cloudinary_video import upload_reel_video as cloudinary_upload
        result = await cloudinary_upload(content, current_user.id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.post("", response_model=ReelResponse, status_code=status.HTTP_201_CREATED)
async def create_reel(
    reel_data: ReelCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new reel."""
    reel = Reel(
        user_id=current_user.id,
        video_url=reel_data.video_url,
        thumbnail_url=reel_data.thumbnail_url,
        caption=reel_data.caption,
        duration=reel_data.duration
    )
    db.add(reel)
    await db.flush()
    await db.refresh(reel, ["author"])
    
    return build_reel_response(reel, 0, 0, False)


@router.get("/feed", response_model=ReelListResponse)
async def get_reels_feed(
    cursor: Optional[str] = None,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get reels feed with infinite scroll."""
    query = select(Reel).options(selectinload(Reel.author))
    
    # Cursor pagination
    if cursor:
        try:
            cursor_time = datetime.fromisoformat(cursor)
            query = query.where(Reel.created_at < cursor_time)
        except ValueError:
            pass
    
    query = query.order_by(Reel.created_at.desc()).limit(limit + 1)
    
    result = await db.execute(query)
    reels = result.scalars().all()
    
    has_more = len(reels) > limit
    if has_more:
        reels = reels[:limit]
    
    reel_responses = []
    for reel in reels:
        likes_count = await db.scalar(
            select(func.count(ReelLike.id)).where(ReelLike.reel_id == reel.id)
        )
        comments_count = await db.scalar(
            select(func.count(ReelComment.id)).where(ReelComment.reel_id == reel.id)
        )
        is_liked = await db.scalar(
            select(func.count(ReelLike.id)).where(
                ReelLike.reel_id == reel.id,
                ReelLike.user_id == current_user.id
            )
        ) > 0
        
        reel_responses.append(build_reel_response(reel, likes_count or 0, comments_count or 0, is_liked))
    
    next_cursor = reels[-1].created_at.isoformat() if has_more and reels else None
    
    return ReelListResponse(reels=reel_responses, next_cursor=next_cursor, has_more=has_more)


@router.get("/user/{user_id}", response_model=ReelListResponse)
async def get_user_reels(
    user_id: int,
    cursor: Optional[str] = None,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get reels by a specific user."""
    query = select(Reel).options(selectinload(Reel.author)).where(Reel.user_id == user_id)
    
    if cursor:
        try:
            cursor_time = datetime.fromisoformat(cursor)
            query = query.where(Reel.created_at < cursor_time)
        except ValueError:
            pass
    
    query = query.order_by(Reel.created_at.desc()).limit(limit + 1)
    
    result = await db.execute(query)
    reels = result.scalars().all()
    
    has_more = len(reels) > limit
    if has_more:
        reels = reels[:limit]
    
    reel_responses = []
    for reel in reels:
        likes_count = await db.scalar(
            select(func.count(ReelLike.id)).where(ReelLike.reel_id == reel.id)
        )
        comments_count = await db.scalar(
            select(func.count(ReelComment.id)).where(ReelComment.reel_id == reel.id)
        )
        is_liked = await db.scalar(
            select(func.count(ReelLike.id)).where(
                ReelLike.reel_id == reel.id,
                ReelLike.user_id == current_user.id
            )
        ) > 0
        
        reel_responses.append(build_reel_response(reel, likes_count or 0, comments_count or 0, is_liked))
    
    next_cursor = reels[-1].created_at.isoformat() if has_more and reels else None
    
    return ReelListResponse(reels=reel_responses, next_cursor=next_cursor, has_more=has_more)


@router.get("/{reel_id}", response_model=ReelResponse)
async def get_reel(
    reel_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a single reel by ID."""
    result = await db.execute(
        select(Reel).options(selectinload(Reel.author)).where(Reel.id == reel_id)
    )
    reel = result.scalar_one_or_none()
    
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")
    
    likes_count = await db.scalar(
        select(func.count(ReelLike.id)).where(ReelLike.reel_id == reel.id)
    )
    comments_count = await db.scalar(
        select(func.count(ReelComment.id)).where(ReelComment.reel_id == reel.id)
    )
    is_liked = await db.scalar(
        select(func.count(ReelLike.id)).where(
            ReelLike.reel_id == reel.id,
            ReelLike.user_id == current_user.id
        )
    ) > 0
    
    return build_reel_response(reel, likes_count or 0, comments_count or 0, is_liked)


@router.delete("/{reel_id}", status_code=status.HTTP_200_OK)
async def delete_reel(
    reel_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a reel (owner only)."""
    result = await db.execute(select(Reel).where(Reel.id == reel_id))
    reel = result.scalar_one_or_none()
    
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")
    
    if reel.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.delete(reel)
    
    return {"message": "Reel deleted"}


@router.post("/{reel_id}/view")
async def increment_view(
    reel_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Increment view count for a reel."""
    result = await db.execute(select(Reel).where(Reel.id == reel_id))
    reel = result.scalar_one_or_none()
    
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")
    
    reel.views_count = (reel.views_count or 0) + 1
    await db.flush()
    
    return {"views_count": reel.views_count}


# Like endpoints
@router.post("/{reel_id}/like", response_model=ReelLikeResponse)
async def like_reel(
    reel_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Like a reel."""
    result = await db.execute(select(Reel).where(Reel.id == reel_id))
    reel = result.scalar_one_or_none()
    
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")
    
    existing = await db.execute(
        select(ReelLike).where(ReelLike.reel_id == reel_id, ReelLike.user_id == current_user.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Already liked")
    
    like = ReelLike(user_id=current_user.id, reel_id=reel_id)
    db.add(like)
    
    # Create notification (if not own reel)
    if reel.user_id != current_user.id:
        notification = Notification(
            user_id=reel.user_id,
            actor_id=current_user.id,
            type=NotificationType.LIKE.value,
            post_id=None  # We could add reel_id to notification model later
        )
        db.add(notification)
    
    await db.flush()
    
    likes_count = await db.scalar(
        select(func.count(ReelLike.id)).where(ReelLike.reel_id == reel_id)
    )
    
    return ReelLikeResponse(reel_id=reel_id, likes_count=likes_count, is_liked=True)


@router.delete("/{reel_id}/like", response_model=ReelLikeResponse)
async def unlike_reel(
    reel_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Unlike a reel."""
    result = await db.execute(
        select(ReelLike).where(ReelLike.reel_id == reel_id, ReelLike.user_id == current_user.id)
    )
    like = result.scalar_one_or_none()
    
    if not like:
        raise HTTPException(status_code=400, detail="Not liked")
    
    await db.delete(like)
    await db.flush()
    
    likes_count = await db.scalar(
        select(func.count(ReelLike.id)).where(ReelLike.reel_id == reel_id)
    )
    
    return ReelLikeResponse(reel_id=reel_id, likes_count=likes_count or 0, is_liked=False)


# Comment endpoints
@router.post("/{reel_id}/comments", response_model=ReelCommentResponse, status_code=status.HTTP_201_CREATED)
async def create_reel_comment(
    reel_id: int,
    comment_data: ReelCommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add a comment to a reel."""
    result = await db.execute(select(Reel).where(Reel.id == reel_id))
    reel = result.scalar_one_or_none()
    
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")
    
    comment = ReelComment(
        reel_id=reel_id,
        user_id=current_user.id,
        content=comment_data.content,
        parent_id=comment_data.parent_id
    )
    db.add(comment)
    
    # Create notification
    if reel.user_id != current_user.id:
        notification = Notification(
            user_id=reel.user_id,
            actor_id=current_user.id,
            type=NotificationType.COMMENT.value,
            post_id=None
        )
        db.add(notification)
    
    await db.flush()
    await db.refresh(comment)
    
    return ReelCommentResponse(
        id=comment.id,
        reel_id=comment.reel_id,
        content=comment.content,
        created_at=comment.created_at,
        author=UserMinimal.model_validate(current_user),
        parent_id=comment.parent_id,
        replies_count=0
    )


@router.get("/{reel_id}/comments", response_model=ReelCommentListResponse)
async def get_reel_comments(
    reel_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get comments for a reel."""
    result = await db.execute(
        select(ReelComment)
        .options(selectinload(ReelComment.author))
        .where(ReelComment.reel_id == reel_id, ReelComment.parent_id.is_(None))
        .order_by(ReelComment.created_at.desc())
    )
    comments = result.scalars().all()
    
    comment_responses = []
    for comment in comments:
        replies_count = await db.scalar(
            select(func.count(ReelComment.id)).where(ReelComment.parent_id == comment.id)
        )
        comment_responses.append(ReelCommentResponse(
            id=comment.id,
            reel_id=comment.reel_id,
            content=comment.content,
            created_at=comment.created_at,
            author=UserMinimal.model_validate(comment.author),
            parent_id=comment.parent_id,
            replies_count=replies_count or 0
        ))
    
    return ReelCommentListResponse(comments=comment_responses, total=len(comment_responses))
