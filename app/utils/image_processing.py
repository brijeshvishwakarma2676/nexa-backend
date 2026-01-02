from io import BytesIO
from PIL import Image

def process_cover_photo(file_bytes: bytes, target_width: int = 851, target_height: int = 315) -> bytes:
    """
    Process image bytes to be exactly target_width x target_height.
    Uses center-cropping to maintain aspect ratio and then resizes.
    """
    img = Image.open(BytesIO(file_bytes))
    
    # Convert to RGB if necessary (e.g. for PNG with alpha or CMYK)
    if img.mode != 'RGB':
        img = img.convert('RGB')
        
    width, height = img.size
    target_ratio = target_width / target_height
    img_ratio = width / height
    
    if img_ratio > target_ratio:
        # Image is wider than target: crop left and right
        new_width = int(target_ratio * height)
        offset = (width - new_width) // 2
        img = img.crop((offset, 0, offset + new_width, height))
    else:
        # Image is taller than target: crop top and bottom
        new_height = int(width / target_ratio)
        offset = (height - new_height) // 2
        img = img.crop((0, offset, width, offset + new_height))
        
    # Final resize to exact dimensions
    img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    
    # Save back to bytes
    output = BytesIO()
    img.save(output, format='JPEG', quality=95)
    return output.getvalue()
