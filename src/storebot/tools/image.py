import base64
import io
from pathlib import Path

from PIL import Image, ImageOps

# Limit decompression to ~50 megapixels to prevent memory exhaustion
# on resource-constrained devices (Raspberry Pi 5).
Image.MAX_IMAGE_PIXELS = 50_000_000


def _output_path(image_path: str, suffix: str) -> Path:
    """Generate output path with a suffix before the extension."""
    p = Path(image_path)
    return p.with_stem(f"{p.stem}_{suffix}")


def _prepare_for_jpeg(img: Image.Image) -> Image.Image:
    """Handle EXIF rotation and convert to RGB for JPEG saving."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    return img


def resize_for_listing(image_path: str, max_size: tuple[int, int] = (1200, 1200)) -> str:
    """Resize image for marketplace listing upload.

    Returns path to the resized image.
    """
    with Image.open(image_path) as img:
        img = _prepare_for_jpeg(img)
        img.thumbnail(max_size, Image.LANCZOS)
        out = _output_path(image_path, "listing").with_suffix(".jpg")
        img.save(out, "JPEG", quality=90)
    return str(out)


def resize_for_analysis(image_path: str, max_size: tuple[int, int] = (800, 800)) -> str:
    """Resize image for Claude vision analysis (lower res to save tokens).

    Returns path to the resized image.
    """
    with Image.open(image_path) as img:
        img = _prepare_for_jpeg(img)
        img.thumbnail(max_size, Image.LANCZOS)
        out = _output_path(image_path, "analysis").with_suffix(".jpg")
        img.save(out, "JPEG", quality=80)
    return str(out)


def optimize_for_upload(image_path: str, quality: int = 85) -> str:
    """Optimize image file size for upload (JPEG compression).

    Returns path to the optimized image.
    """
    with Image.open(image_path) as img:
        img = _prepare_for_jpeg(img)
        out = _output_path(image_path, "optimized").with_suffix(".jpg")
        img.save(out, "JPEG", quality=quality)
    return str(out)


def encode_image_base64(image_path: str) -> tuple[str, str]:
    """Read image file and return (base64_data, media_type).

    Re-encodes through PIL to strip EXIF metadata (GPS, camera serial, etc.)
    before base64-encoding.
    """
    with Image.open(image_path) as img:
        img = _prepare_for_jpeg(img)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        data = buf.getvalue()
    return base64.b64encode(data).decode("utf-8"), "image/jpeg"
