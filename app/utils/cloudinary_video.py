"""Cloudinary video upload utilities for Reels."""
import cloudinary
import cloudinary.uploader
from app.config import settings


def configure_video_cloudinary():
    """Configure Cloudinary with video account credentials."""
    if not all([
        settings.CLOUDINARY_VIDEO_CLOUD_NAME,
        settings.CLOUDINARY_VIDEO_API_KEY,
        settings.CLOUDINARY_VIDEO_API_SECRET
    ]):
        raise ValueError("Cloudinary video credentials not configured")
    
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_VIDEO_CLOUD_NAME,
        api_key=settings.CLOUDINARY_VIDEO_API_KEY,
        api_secret=settings.CLOUDINARY_VIDEO_API_SECRET
    )


async def upload_reel_video(file_content: bytes, user_id: int) -> dict:
    """
    Upload a video to Cloudinary (video account) with optimization for mobile streaming.
    
    Returns:
        dict with video_url, thumbnail_url, and duration
    """
    configure_video_cloudinary()
    
    import io
    file_stream = io.BytesIO(file_content)
    
    result = cloudinary.uploader.upload(
        file_stream,
        resource_type="video",
        folder=f"reels/{user_id}",
        # Video optimization for mobile
        transformation=[
            {"quality": "auto:good", "fetch_format": "mp4"},
            {"width": 720, "crop": "limit"},  # Max width for mobile
        ],
        eager=[
            # Generate thumbnail
            {"format": "jpg", "transformation": [
                {"width": 720, "height": 1280, "crop": "fill", "gravity": "center"}
            ]}
        ],
        eager_async=True
    )
    
    video_url = result.get("secure_url")
    duration = result.get("duration", 0)
    
    # Generate thumbnail URL
    thumbnail_url = video_url.replace(".mp4", ".jpg") if video_url else None
    
    return {
        "video_url": video_url,
        "thumbnail_url": thumbnail_url,
        "duration": duration
    }


async def delete_reel_video(public_id: str):
    """Delete a video from Cloudinary."""
    configure_video_cloudinary()
    cloudinary.uploader.destroy(public_id, resource_type="video")
