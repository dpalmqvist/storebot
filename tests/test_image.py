import base64
import os

from PIL import Image

from storebot.tools.image import (
    encode_image_base64,
    optimize_for_upload,
    resize_for_analysis,
    resize_for_listing,
)


def _create_test_image(path, size=(2000, 1500), mode="RGB"):
    """Create a test image with the given size and mode."""
    img = Image.new(mode, size, color="red")
    img.save(str(path))
    return str(path)


def _create_gradient_image(path, size=(800, 600)):
    """Create a gradient test image that compresses differently at various quality levels."""
    img = Image.new("RGB", size)
    for x in range(size[0]):
        for y in range(size[1]):
            img.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
    img.save(str(path))
    return str(path)


class TestResizeForListing:
    def test_shrinks_large_image(self, tmp_path):
        src = _create_test_image(tmp_path / "big.jpg", size=(3000, 2000))
        out = resize_for_listing(src)

        img = Image.open(out)
        assert img.width <= 1200
        assert img.height <= 1200
        assert out.endswith("_listing.jpg")

    def test_preserves_aspect_ratio(self, tmp_path):
        src = _create_test_image(tmp_path / "wide.jpg", size=(2400, 1200))
        out = resize_for_listing(src)

        img = Image.open(out)
        assert img.width == 1200
        assert img.height == 600

    def test_does_not_upscale_small(self, tmp_path):
        src = _create_test_image(tmp_path / "small.jpg", size=(400, 300))
        out = resize_for_listing(src)

        img = Image.open(out)
        assert img.width == 400
        assert img.height == 300

    def test_converts_rgba_to_rgb(self, tmp_path):
        src = _create_test_image(tmp_path / "alpha.png", size=(800, 600), mode="RGBA")
        out = resize_for_listing(src)

        img = Image.open(out)
        assert img.mode == "RGB"

    def test_custom_max_size(self, tmp_path):
        src = _create_test_image(tmp_path / "big.jpg", size=(2000, 1500))
        out = resize_for_listing(src, max_size=(600, 600))

        img = Image.open(out)
        assert img.width <= 600
        assert img.height <= 600


class TestResizeForAnalysis:
    def test_shrinks_to_800(self, tmp_path):
        src = _create_test_image(tmp_path / "big.jpg", size=(2000, 1500))
        out = resize_for_analysis(src)

        img = Image.open(out)
        assert img.width <= 800
        assert img.height <= 800
        assert out.endswith("_analysis.jpg")

    def test_correct_suffix(self, tmp_path):
        src = _create_test_image(tmp_path / "photo.png", size=(1000, 800))
        out = resize_for_analysis(src)

        assert "_analysis.jpg" in out


class TestOptimizeForUpload:
    def test_produces_jpeg(self, tmp_path):
        src = _create_test_image(tmp_path / "photo.png", size=(800, 600))
        out = optimize_for_upload(src)

        img = Image.open(out)
        assert img.format == "JPEG"
        assert out.endswith("_optimized.jpg")

    def test_custom_quality(self, tmp_path):
        src_high = _create_gradient_image(tmp_path / "gradient_high.jpg")
        src_low = _create_gradient_image(tmp_path / "gradient_low.jpg")
        out_high = optimize_for_upload(src_high, quality=95)
        out_low = optimize_for_upload(src_low, quality=30)

        # Lower quality produces a smaller file (gradient image has enough detail)
        assert os.path.getsize(out_low) < os.path.getsize(out_high)

    def test_converts_rgba(self, tmp_path):
        src = _create_test_image(tmp_path / "alpha.png", size=(400, 300), mode="RGBA")
        out = optimize_for_upload(src)

        img = Image.open(out)
        assert img.mode == "RGB"


class TestEncodeImageBase64:
    def test_valid_base64_jpg(self, tmp_path):
        src = _create_test_image(tmp_path / "test.jpg", size=(100, 100))
        data, media_type = encode_image_base64(src)

        assert media_type == "image/jpeg"
        decoded = base64.b64decode(data)
        assert len(decoded) > 0

    def test_png_media_type(self, tmp_path):
        src = _create_test_image(tmp_path / "test.png", size=(100, 100))
        _, media_type = encode_image_base64(src)

        assert media_type == "image/png"

    def test_webp_media_type(self, tmp_path):
        img = Image.new("RGB", (100, 100), color="blue")
        path = tmp_path / "test.webp"
        img.save(str(path), "WEBP")

        _, media_type = encode_image_base64(str(path))
        assert media_type == "image/webp"

    def test_roundtrip(self, tmp_path):
        src = _create_test_image(tmp_path / "test.jpg", size=(100, 100))
        data, _ = encode_image_base64(src)

        # Decode and verify it's valid image data
        decoded = base64.b64decode(data)
        with open(tmp_path / "decoded.jpg", "wb") as f:
            f.write(decoded)
        img = Image.open(tmp_path / "decoded.jpg")
        assert img.size == (100, 100)
