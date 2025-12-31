"""Post routes: CRUD, feed, likes, comments."""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import selectinload
from typing import Optional
from datetime import datetime
import os
import uuid

from app.database import get_db
from app.config import settings
from app.models.user import User, Follow
from app.models.post import Post, Like, Comment, Share
from app.models.notification import Notification, NotificationType
from app.schemas.post import (
    PostCreate, PostResponse, PostListResponse, PostUpdate,
    LikeResponse, CommentCreate, CommentResponse, CommentListResponse
)
from app.schemas.user import UserMinimal
from app.utils.auth import get_current_user
from app.routers.users import get_relationship_status

router = APIRouter(prefix="/api/posts", tags=["Posts"])

def build_post_response(post: Post, current_user_id: int, likes_count: int, comments_count: int, shares_count: int, is_liked: bool, relationship_status: str = "none") -> PostResponse:
    """Build PostResponse from Post model."""
    return PostResponse(
        id=post.id,
        content=post.content,
        image_url=post.image_url,
        visibility=post.visibility,
        created_at=post.created_at,
        updated_at=post.updated_at,
        author=UserMinimal.model_validate(post.author),
        likes_count=likes_count,
        comments_count=comments_count,
        shares_count=shares_count,
        is_liked=is_liked,
        relationship_status=relationship_status
    )


@router.post("", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
async def create_post(
    post_data: PostCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new post.
    
    Flow:
    1. Validate content
    2. Create post record
    3. Return post with author info
    """
    post = Post(
        user_id=current_user.id,
        content=post_data.content,
        image_url=post_data.image_url,
        visibility=post_data.visibility
    )
    db.add(post)
    await db.flush()
    await db.refresh(post, ["author"])
    
    return build_post_response(post, current_user.id, 0, 0, 0, False, "self")


@router.post("/upload-image")
async def upload_post_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """Upload an image for a post to Cloudinary."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large")
    
    try:
        from app.utils.cloudinary import upload_post_image as cloudinary_upload
        image_url = await cloudinary_upload(content, current_user.id)
        return {"image_url": image_url}
    except ValueError:
        # Fallback to local storage
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
        filename = f"post_{current_user.id}_{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(settings.UPLOAD_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(content)
        return {"image_url": f"/uploads/{filename}"}



@router.get("/feed", response_model=PostListResponse)
async def get_feed(
    cursor: Optional[str] = None,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get personalized feed with infinite scroll.
    
    Feed includes:
    - Own posts
    - Posts from followed users (public + followers visibility)
    - Public posts from non-followed users
    
    Cursor-based pagination using created_at timestamp.
    """
    # Get IDs of users we follow (only ACTIVE follows)
    following_result = await db.execute(
        select(Follow.following_id).where(
            Follow.follower_id == current_user.id,
            Follow.status == "active"
        )
    )
    following_ids = [r[0] for r in following_result.fetchall()]
    following_ids.append(current_user.id)  # Include own posts
    
    # Get IDs of private accounts we don't follow
    private_users_result = await db.execute(
        select(User.id).where(
            User.is_private == True,
            User.id.not_in(following_ids)
        )
    )
    private_not_following = [r[0] for r in private_users_result.fetchall()]
    
    # Base query
    query = select(Post).options(selectinload(Post.author))
    
    # Filter: own posts OR followed users' posts OR public posts from non-private accounts
    query = query.where(
        or_(
            Post.user_id.in_(following_ids),
            and_(
                Post.visibility == "public",
                Post.user_id.not_in(private_not_following) if private_not_following else True
            )
        )
    )
    
    # Cursor pagination
    if cursor:
        try:
            cursor_time = datetime.fromisoformat(cursor)
            query = query.where(Post.created_at < cursor_time)
        except ValueError:
            pass
    
    # Order and limit
    query = query.order_by(Post.created_at.desc()).limit(limit + 1)
    
    result = await db.execute(query)
    posts = result.scalars().all()
    
    # Check if there are more posts
    has_more = len(posts) > limit
    if has_more:
        posts = posts[:limit]
    
    # Build response with counts
    post_responses = []
    for post in posts:
        likes_count = await db.scalar(
            select(func.count(Like.id)).where(Like.post_id == post.id)
        )
        comments_count = await db.scalar(
            select(func.count(Comment.id)).where(Comment.post_id == post.id)
        )
        shares_count = await db.scalar(
            select(func.count(Share.id)).where(Share.post_id == post.id)
        )
        is_liked = await db.scalar(
            select(func.count(Like.id)).where(
                Like.post_id == post.id,
                Like.user_id == current_user.id
            )
        ) > 0
        
        rel_status = await get_relationship_status(current_user.id, post.author.id, db)
        
        post_responses.append(build_post_response(
            post, current_user.id, likes_count or 0, comments_count or 0, shares_count or 0, is_liked, rel_status
        ))
    
    next_cursor = None
    if has_more and posts:
        next_cursor = posts[-1].created_at.isoformat()
    
    return PostListResponse(
        posts=post_responses,
        next_cursor=next_cursor,
        has_more=has_more
    )


@router.get("/user/{user_id}", response_model=PostListResponse)
async def get_user_posts(
    user_id: int,
    cursor: Optional[str] = None,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get posts by a specific user."""
    # Check if we follow this user
    is_following = current_user.id == user_id or await db.scalar(
        select(func.count(Follow.id)).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id
        )
    ) > 0
    
    query = select(Post).options(selectinload(Post.author)).where(Post.user_id == user_id)
    
    # If not following, only show public posts
    if not is_following:
        query = query.where(Post.visibility == "public")
    
    if cursor:
        try:
            cursor_time = datetime.fromisoformat(cursor)
            query = query.where(Post.created_at < cursor_time)
        except ValueError:
            pass
    
    query = query.order_by(Post.created_at.desc()).limit(limit + 1)
    
    result = await db.execute(query)
    posts = result.scalars().all()
    
    has_more = len(posts) > limit
    if has_more:
        posts = posts[:limit]
    
    post_responses = []
    for post in posts:
        likes_count = await db.scalar(
            select(func.count(Like.id)).where(Like.post_id == post.id)
        )
        comments_count = await db.scalar(
            select(func.count(Comment.id)).where(Comment.post_id == post.id)
        )
        shares_count = await db.scalar(
            select(func.count(Share.id)).where(Share.post_id == post.id)
        )
        is_liked = await db.scalar(
            select(func.count(Like.id)).where(
                Like.post_id == post.id,
                Like.user_id == current_user.id
            )
        ) > 0
        
        rel_status = await get_relationship_status(current_user.id, post.author.id, db)
        
        post_responses.append(build_post_response(
            post, current_user.id, likes_count or 0, comments_count or 0, shares_count or 0, is_liked, rel_status
        ))
    
    next_cursor = posts[-1].created_at.isoformat() if has_more and posts else None
    
    return PostListResponse(posts=post_responses, next_cursor=next_cursor, has_more=has_more)


@router.get("/{post_id}", response_model=PostResponse)
async def get_post(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a single post by ID."""
    result = await db.execute(
        select(Post).options(selectinload(Post.author)).where(Post.id == post_id)
    )
    post = result.scalar_one_or_none()
    
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    likes_count = await db.scalar(
        select(func.count(Like.id)).where(Like.post_id == post.id)
    )
    comments_count = await db.scalar(
        select(func.count(Comment.id)).where(Comment.post_id == post.id)
    )
    shares_count = await db.scalar(
        select(func.count(Share.id)).where(Share.post_id == post.id)
    )
    is_liked = await db.scalar(
        select(func.count(Like.id)).where(
            Like.post_id == post.id,
            Like.user_id == current_user.id
        )
    ) > 0
    
    rel_status = await get_relationship_status(current_user.id, post.author.id, db)
    
    return build_post_response(post, current_user.id, likes_count or 0, comments_count or 0, shares_count or 0, is_liked, rel_status)


@router.delete("/{post_id}", status_code=status.HTTP_200_OK)
async def delete_post(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a post (owner only)."""
    result = await db.execute(select(Post).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    if post.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.delete(post)
    
    return {"message": "Post deleted"}


# Like endpoints
@router.post("/{post_id}/like", response_model=LikeResponse)
async def like_post(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Like a post."""
    result = await db.execute(select(Post).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    # Check if already liked
    existing = await db.execute(
        select(Like).where(Like.post_id == post_id, Like.user_id == current_user.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Already liked")
    
    # Create like
    like = Like(user_id=current_user.id, post_id=post_id)
    db.add(like)
    
    # Create notification (if not own post)
    if post.user_id != current_user.id:
        notification = Notification(
            user_id=post.user_id,
            actor_id=current_user.id,
            type=NotificationType.LIKE.value,
            post_id=post_id
        )
        db.add(notification)
    
    await db.flush()
    
    likes_count = await db.scalar(
        select(func.count(Like.id)).where(Like.post_id == post_id)
    )
    
    return LikeResponse(post_id=post_id, likes_count=likes_count, is_liked=True)


@router.delete("/{post_id}/like", response_model=LikeResponse)
async def unlike_post(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Unlike a post."""
    result = await db.execute(
        select(Like).where(Like.post_id == post_id, Like.user_id == current_user.id)
    )
    like = result.scalar_one_or_none()
    
    if not like:
        raise HTTPException(status_code=400, detail="Not liked")
    
    await db.delete(like)
    await db.flush()
    
    likes_count = await db.scalar(
        select(func.count(Like.id)).where(Like.post_id == post_id)
    )
    
    return LikeResponse(post_id=post_id, likes_count=likes_count or 0, is_liked=False)


# Share endpoints
@router.post("/{post_id}/share")
async def share_post(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Share a post."""
    # Check if post exists
    post = await db.scalar(select(Post).where(Post.id == post_id))
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    # Check if already shared
    existing = await db.scalar(
        select(Share).where(Share.post_id == post_id, Share.user_id == current_user.id)
    )
    if existing:
        raise HTTPException(status_code=400, detail="Already shared")
    
    share = Share(user_id=current_user.id, post_id=post_id)
    db.add(share)
    await db.flush()
    
    shares_count = await db.scalar(
        select(func.count(Share.id)).where(Share.post_id == post_id)
    )
    
    return {"post_id": post_id, "shares_count": shares_count, "is_shared": True}


@router.delete("/{post_id}/share")
async def unshare_post(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove a share from a post."""
    result = await db.execute(
        select(Share).where(Share.post_id == post_id, Share.user_id == current_user.id)
    )
    share = result.scalar_one_or_none()
    
    if not share:
        raise HTTPException(status_code=400, detail="Not shared")
    
    await db.delete(share)
    await db.flush()
    
    shares_count = await db.scalar(
        select(func.count(Share.id)).where(Share.post_id == post_id)
    )
    
    return {"post_id": post_id, "shares_count": shares_count or 0, "is_shared": False}


# Comment endpoints
@router.post("/{post_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
async def create_comment(
    post_id: int,
    comment_data: CommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add a comment to a post."""
    result = await db.execute(select(Post).where(Post.id == post_id))
    post = result.scalar_one_or_none()
    
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    comment = Comment(
        post_id=post_id,
        user_id=current_user.id,
        content=comment_data.content,
        parent_id=comment_data.parent_id
    )
    db.add(comment)
    
    # Create notification
    if post.user_id != current_user.id:
        notification = Notification(
            user_id=post.user_id,
            actor_id=current_user.id,
            type=NotificationType.COMMENT.value,
            post_id=post_id
        )
        db.add(notification)
    
    await db.flush()
    await db.refresh(comment)
    
    return CommentResponse(
        id=comment.id,
        post_id=comment.post_id,
        content=comment.content,
        created_at=comment.created_at,
        author=UserMinimal.model_validate(current_user),
        parent_id=comment.parent_id,
        replies_count=0
    )


@router.get("/{post_id}/comments", response_model=CommentListResponse)
async def get_comments(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get comments for a post."""
    result = await db.execute(
        select(Comment)
        .options(selectinload(Comment.author))
        .where(Comment.post_id == post_id, Comment.parent_id.is_(None))
        .order_by(Comment.created_at.desc())
    )
    comments = result.scalars().all()
    
    comment_responses = []
    for comment in comments:
        replies_count = await db.scalar(
            select(func.count(Comment.id)).where(Comment.parent_id == comment.id)
        )
        comment_responses.append(CommentResponse(
            id=comment.id,
            post_id=comment.post_id,
            content=comment.content,
            created_at=comment.created_at,
            author=UserMinimal.model_validate(comment.author),
            parent_id=comment.parent_id,
            replies_count=replies_count or 0
        ))
    
    return CommentListResponse(comments=comment_responses, total=len(comment_responses))
