"""Story routes: create, view, list grouped by user, track views."""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from typing import List
from datetime import datetime
import os
import uuid

from app.database import get_db
from app.config import settings
from app.models.user import User, Follow
from app.models.story import Story, StoryView
from app.schemas.story import (
    StoryCreate, StoryResponse, StoryGroupResponse,
    StoryListResponse, StoryViewResponse
)
from app.schemas.user import UserMinimal
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/stories", tags=["Stories"])


@router.post("", response_model=StoryResponse, status_code=status.HTTP_201_CREATED)
async def create_story(
    story_data: StoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new story.
    
    Story expires automatically after 24 hours.
    Must have either content (text) or image_url.
    """
    if not story_data.content and not story_data.image_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Story must have content or image"
        )
    
    story = Story(
        user_id=current_user.id,
        content=story_data.content,
        image_url=story_data.image_url
    )
    db.add(story)
    await db.flush()
    await db.refresh(story)
    
    return StoryResponse(
        id=story.id,
        content=story.content,
        image_url=story.image_url,
        created_at=story.created_at,
        expires_at=story.expires_at,
        author=UserMinimal.model_validate(current_user),
        views_count=0,
        is_viewed=False
    )


@router.post("/upload-image")
async def upload_story_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """Upload an image for a story to Cloudinary."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large")
    
    try:
        from app.utils.cloudinary import upload_story_image as cloudinary_upload
        image_url = await cloudinary_upload(content, current_user.id)
        return {"image_url": image_url}
    except ValueError:
        # Fallback to local storage if Cloudinary not configured
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
        filename = f"story_{current_user.id}_{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(settings.UPLOAD_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(content)
        return {"image_url": f"/uploads/{filename}"}


@router.get("", response_model=StoryListResponse)
async def get_stories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all active stories grouped by user.
    
    Returns story groups ordered by:
    1. Current user's stories first
    2. Then followed users with unseen stories
    3. Then followed users with seen stories
    """
    now = datetime.utcnow()
    
    # Get IDs of users we follow (only ACTIVE follows)
    following_result = await db.execute(
        select(Follow.following_id).where(
            Follow.follower_id == current_user.id,
            Follow.status == "active"
        )
    )
    following_ids = [r[0] for r in following_result.fetchall()]
    following_ids.append(current_user.id)  # Include own stories
    
    # Get active stories from: followed users, self, or public (non-private) accounts
    result = await db.execute(
        select(Story)
        .options(selectinload(Story.author))
        .where(
            Story.expires_at > now,
            or_(
                Story.user_id.in_(following_ids),
                Story.author.has(User.is_private == False)
            )
        )
        .order_by(Story.created_at.desc())
    )
    stories = result.scalars().all()
    
    # Group by user
    user_stories = {}
    story_ids = []
    for story in stories:
        story_ids.append(story.id)
        if story.user_id not in user_stories:
            user_stories[story.user_id] = {
                "user": story.author,
                "stories": [],
                "latest_at": story.created_at
            }
        user_stories[story.user_id]["stories"].append(story)
    
    # Batch fetch: current user's views (which stories they've seen)
    viewed_result = await db.execute(
        select(StoryView.story_id).where(
            StoryView.story_id.in_(story_ids),
            StoryView.viewer_id == current_user.id
        )
    )
    viewed_story_ids = {r[0] for r in viewed_result.fetchall()}
    
    # Batch fetch: view counts per story
    view_counts_result = await db.execute(
        select(
            StoryView.story_id,
            func.count(StoryView.id).label("count")
        ).where(StoryView.story_id.in_(story_ids))
        .group_by(StoryView.story_id)
    )
    view_counts = {r[0]: r[1] for r in view_counts_result.fetchall()}
    
    # Build response with pre-fetched data
    story_groups = []
    for user_id, data in user_stories.items():
        user = data["user"]
        stories_list = data["stories"]
        
        story_responses = []
        all_seen = True
        
        for story in stories_list:
            is_viewed = story.id in viewed_story_ids
            
            if not is_viewed and story.user_id != current_user.id:
                all_seen = False
            
            story_responses.append(StoryResponse(
                id=story.id,
                content=story.content,
                image_url=story.image_url,
                created_at=story.created_at,
                expires_at=story.expires_at,
                author=UserMinimal.model_validate(user),
                views_count=view_counts.get(story.id, 0),
                is_viewed=is_viewed
            ))
        
        story_groups.append(StoryGroupResponse(
            user=UserMinimal.model_validate(user),
            stories=story_responses,
            all_seen=all_seen if user_id != current_user.id else True,
            latest_story_at=data["latest_at"]
        ))
    
    # Sort: current user first, then unseen, then seen
    def sort_key(group):
        if group.user.id == current_user.id:
            return (0, group.latest_story_at)
        elif not group.all_seen:
            return (1, group.latest_story_at)
        else:
            return (2, group.latest_story_at)
    
    story_groups.sort(key=sort_key, reverse=True)
    
    return StoryListResponse(story_groups=story_groups)


@router.get("/{story_id}", response_model=StoryResponse)
async def get_story(
    story_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a single story and mark it as viewed.
    
    Creates StoryView record if not already viewed.
    """
    result = await db.execute(
        select(Story).options(selectinload(Story.author)).where(Story.id == story_id)
    )
    story = result.scalar_one_or_none()
    
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    
    if story.is_expired:
        raise HTTPException(status_code=404, detail="Story has expired")
    
    # Check privacy: if author is private, check if we follow them
    if story.author.is_private and story.user_id != current_user.id:
        is_following = await db.scalar(
            select(func.count(Follow.id)).where(
                Follow.follower_id == current_user.id,
                Follow.following_id == story.user_id,
                Follow.status == "active"
            )
        ) > 0
        if not is_following:
            raise HTTPException(status_code=403, detail="This account is private")
    
    # Mark as viewed (if not own story and not already viewed)
    if story.user_id != current_user.id:
        view_result = await db.execute(
            select(StoryView).where(
                StoryView.story_id == story_id,
                StoryView.viewer_id == current_user.id
            )
        )
        if not view_result.scalar_one_or_none():
            view = StoryView(story_id=story_id, viewer_id=current_user.id)
            db.add(view)
            await db.flush()
    
    views_count = await db.scalar(
        select(func.count(StoryView.id)).where(StoryView.story_id == story_id)
    )
    
    return StoryResponse(
        id=story.id,
        content=story.content,
        image_url=story.image_url,
        created_at=story.created_at,
        expires_at=story.expires_at,
        author=UserMinimal.model_validate(story.author),
        views_count=views_count or 0,
        is_viewed=True
    )


@router.get("/{story_id}/views", response_model=List[StoryViewResponse])
async def get_story_views(
    story_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of users who viewed a story (owner only)."""
    result = await db.execute(
        select(Story).where(Story.id == story_id)
    )
    story = result.scalar_one_or_none()
    
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    
    if story.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    views_result = await db.execute(
        select(StoryView)
        .options(selectinload(StoryView.viewer))
        .where(StoryView.story_id == story_id)
        .order_by(StoryView.viewed_at.desc())
    )
    views = views_result.scalars().all()
    
    return [
        StoryViewResponse(
            viewer=UserMinimal.model_validate(v.viewer),
            viewed_at=v.viewed_at
        )
        for v in views
    ]


@router.delete("/{story_id}", status_code=status.HTTP_200_OK)
async def delete_story(
    story_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a story (owner only)."""
    result = await db.execute(select(Story).where(Story.id == story_id))
    story = result.scalar_one_or_none()
    
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    
    if story.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.delete(story)
    
    return {"message": "Story deleted"}
