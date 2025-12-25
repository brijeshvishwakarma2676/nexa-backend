"""Background tasks for story expiration and cleanup."""
from datetime import datetime
from sqlalchemy import select, delete
from app.database import AsyncSessionLocal
from app.models.story import Story, StoryView
import asyncio


async def cleanup_expired_stories():
    """Delete stories that have expired (older than 24 hours)."""
    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()
        
        # Find expired stories
        result = await db.execute(
            select(Story).where(Story.expires_at < now)
        )
        expired_stories = result.scalars().all()
        
        if expired_stories:
            expired_ids = [s.id for s in expired_stories]
            
            # Delete views first (cascade should handle this, but being explicit)
            await db.execute(
                delete(StoryView).where(StoryView.story_id.in_(expired_ids))
            )
            
            # Delete stories
            await db.execute(
                delete(Story).where(Story.id.in_(expired_ids))
            )
            
            await db.commit()
            print(f"Cleaned up {len(expired_stories)} expired stories")


async def run_periodic_cleanup(interval_minutes: int = 5):
    """Run cleanup tasks periodically."""
    while True:
        try:
            await cleanup_expired_stories()
        except Exception as e:
            print(f"Cleanup error: {e}")
        
        await asyncio.sleep(interval_minutes * 60)
