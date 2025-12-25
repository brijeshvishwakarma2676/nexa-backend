"""Cloudinary utility for image uploads."""
import cloudinary
import cloudinary.uploader
from app.config import settings

# Configure Cloudinary
if settings.CLOUDINARY_CLOUD_NAME:
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True
    )


async def upload_image(file_bytes: bytes, folder: str = "socialconnect", public_id: str = None) -> dict:
    """
    Upload an image to Cloudinary.
    
    Args:
        file_bytes: Image file bytes
        folder: Cloudinary folder to upload to
        public_id: Optional custom public ID for the image
    
    Returns:
        dict with 'url' and 'public_id' keys
    """
    if not settings.CLOUDINARY_CLOUD_NAME:
        raise ValueError("Cloudinary is not configured")
    
    upload_options = {
        "folder": folder,
        "resource_type": "image",
        "transformation": [
            {"quality": "auto:good"},
            {"fetch_format": "auto"}
        ]
    }
    
    if public_id:
        upload_options["public_id"] = public_id
    
    result = cloudinary.uploader.upload(file_bytes, **upload_options)
    
    return {
        "url": result["secure_url"],
        "public_id": result["public_id"]
    }


async def upload_avatar(file_bytes: bytes, user_id: int) -> str:
    """Upload user avatar and return URL."""
    result = await upload_image(
        file_bytes,
        folder="socialconnect/avatars",
        public_id=f"avatar_{user_id}"
    )
    return result["url"]


async def upload_cover(file_bytes: bytes, user_id: int) -> str:
    """Upload user cover photo and return URL."""
    result = await upload_image(
        file_bytes,
        folder="socialconnect/covers",
        public_id=f"cover_{user_id}"
    )
    return result["url"]


async def upload_post_image(file_bytes: bytes, user_id: int, post_id: int = None) -> str:
    """Upload post image and return URL."""
    import uuid
    public_id = f"post_{user_id}_{post_id or uuid.uuid4().hex}"
    result = await upload_image(
        file_bytes,
        folder="socialconnect/posts",
        public_id=public_id
    )
    return result["url"]


async def upload_story_image(file_bytes: bytes, user_id: int) -> str:
    """Upload story image and return URL."""
    import uuid
    public_id = f"story_{user_id}_{uuid.uuid4().hex}"
    result = await upload_image(
        file_bytes,
        folder="socialconnect/stories",
        public_id=public_id
    )
    return result["url"]


def delete_image(public_id: str) -> bool:
    """Delete an image from Cloudinary."""
    if not settings.CLOUDINARY_CLOUD_NAME:
        return False
    
    try:
        result = cloudinary.uploader.destroy(public_id)
        return result.get("result") == "ok"
    except Exception:
        return False
