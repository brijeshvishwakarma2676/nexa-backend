"""Notification routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import List

from app.database import get_db
from app.models.user import User
from app.models.notification import Notification, NotificationType
from app.schemas.notification import (
    NotificationResponse, NotificationListResponse, NotificationCountResponse
)
from app.schemas.user import UserMinimal
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


def build_notification_message(notification: Notification, actor_name: str) -> str:
    """Build human-readable notification message."""
    if notification.type == NotificationType.LIKE.value:
        return f"{actor_name} liked your post"
    elif notification.type == NotificationType.COMMENT.value:
        return f"{actor_name} commented on your post"
    elif notification.type == NotificationType.FOLLOW.value:
        return f"{actor_name} started following you"
    elif notification.type == NotificationType.MENTION.value:
        return f"{actor_name} mentioned you"
    return f"{actor_name} interacted with you"


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get notifications for current user."""
    result = await db.execute(
        select(Notification)
        .options(selectinload(Notification.actor))
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    notifications = result.scalars().all()
    
    unread_count = await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == current_user.id,
            Notification.read == False
        )
    )
    
    notification_responses = []
    for notif in notifications:
        actor_name = notif.actor.display_name or notif.actor.username
        notification_responses.append(NotificationResponse(
            id=notif.id,
            type=notif.type,
            read=notif.read,
            created_at=notif.created_at,
            actor=UserMinimal.model_validate(notif.actor),
            post_id=notif.post_id,
            message=build_notification_message(notif, actor_name)
        ))
    
    return NotificationListResponse(
        notifications=notification_responses,
        unread_count=unread_count or 0
    )


@router.get("/count", response_model=NotificationCountResponse)
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get unread notification count."""
    count = await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == current_user.id,
            Notification.read == False
        )
    )
    return NotificationCountResponse(unread_count=count or 0)


@router.patch("/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark a notification as read."""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id
        )
    )
    notification = result.scalar_one_or_none()
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    notification.read = True
    await db.flush()
    
    return {"message": "Marked as read"}


@router.patch("/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark all notifications as read."""
    result = await db.execute(
        select(Notification).where(
            Notification.user_id == current_user.id,
            Notification.read == False
        )
    )
    notifications = result.scalars().all()
    
    for notif in notifications:
        notif.read = True
    
    await db.flush()
    
    return {"message": "All marked as read", "count": len(notifications)}
