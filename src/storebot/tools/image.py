def resize_for_listing(image_path: str, max_size: tuple[int, int] = (1200, 1200)) -> str:
    """Resize image for marketplace listing upload.

    Returns path to the resized image.
    """
    # TODO: Implement with Pillow — resize, maintain aspect ratio
    raise NotImplementedError("resize_for_listing not yet implemented")


def resize_for_analysis(image_path: str, max_size: tuple[int, int] = (800, 800)) -> str:
    """Resize image for Claude vision analysis (lower res to save tokens).

    Returns path to the resized image.
    """
    # TODO: Implement with Pillow
    raise NotImplementedError("resize_for_analysis not yet implemented")


def optimize_for_upload(image_path: str, quality: int = 85) -> str:
    """Optimize image file size for upload (JPEG compression).

    Returns path to the optimized image.
    """
    # TODO: Implement with Pillow — convert to JPEG, compress
    raise NotImplementedError("optimize_for_upload not yet implemented")
