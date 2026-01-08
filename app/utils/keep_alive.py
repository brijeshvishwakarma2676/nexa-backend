import os
import logging
from redis import Redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime

logger = logging.getLogger(__name__)


class KeepAliveService:
    """
    Service to keep the Render server awake by pinging Upstash Redis periodically.
    This prevents the free tier from sleeping after 15 minutes of inactivity.
    """

    def __init__(self):
        self.redis_client = None
        self.scheduler = None
        self.enabled = False

    def connect(self):
        """Initialize Redis connection"""
        # Import here to avoid circular dependency and get settings at runtime
        from app.config import settings

        redis_url = settings.UPSTASH_REDIS_URL

        if not redis_url:
            logger.info("Keep-alive service disabled (no UPSTASH_REDIS_URL)")
            return

        self.enabled = True

        try:
            # Connect to Upstash Redis (TLS is handled automatically via the rediss:// protocol)
            self.redis_client = Redis.from_url(redis_url, decode_responses=True)

            # Test connection
            self.redis_client.ping()
            logger.info("✅ Connected to Upstash Redis for keep-alive")

        except Exception as e:
            logger.error(f"❌ Failed to connect to Upstash Redis: {e}")
            self.enabled = False

    def ping_redis(self):
        """Ping Redis to maintain server activity"""
        if not self.enabled or not self.redis_client:
            return

        try:
            # Set a heartbeat key with current timestamp
            timestamp = datetime.now().isoformat()
            self.redis_client.setex("server:heartbeat", 300, timestamp)  # 5 minutes TTL
            logger.info(f"💓 Keep-alive ping sent at {timestamp}")

        except Exception as e:
            logger.error(f"❌ Keep-alive ping failed: {e}")

    def start(self):
        """Start the keep-alive scheduler"""
        if not self.enabled:
            return

        try:
            self.scheduler = AsyncIOScheduler()

            # Ping every 30 minutes (1800 seconds)
            # This is well before Render's 15-minute sleep timeout
            self.scheduler.add_job(
                self.ping_redis, "interval", minutes=30, id="keep_alive_ping"
            )

            self.scheduler.start()
            logger.info("🚀 Keep-alive scheduler started (pinging every 30 minutes)")

            # Send initial ping
            self.ping_redis()

        except Exception as e:
            logger.error(f"❌ Failed to start keep-alive scheduler: {e}")

    def stop(self):
        """Stop the keep-alive scheduler"""
        if self.scheduler:
            self.scheduler.shutdown()
            logger.info("⏹️ Keep-alive scheduler stopped")

        if self.redis_client:
            self.redis_client.close()
            logger.info("Upstash Redis connection closed")


# Global instance
keep_alive_service = KeepAliveService()
