"""Phase 1 tests: Full-resolution image loading, EXIF orientation, DPI metadata extraction, and invalid input rejection."""

import io
import numpy as np
from PIL import Image
import pytest
from app.pipeline.loader import ImageLoadError, load_image_from_bytes


def _make_png_bytes(width: int = 1200, height: int = 900, dpi: tuple[int, int] | None = (300, 300)) -> bytes:
    arr = np.full((height, width, 3), 245, dtype=np.uint8)
    pil_img = Image.fromarray(arr)
    buf = io.BytesIO()
    if dpi is not None:
        pil_img.save(buf, format="PNG", dpi=dpi)
    else:
        pil_img.save(buf, format="PNG")
    return buf.getvalue()


def test_load_full_resolution_png_and_dpi() -> None:
    raw = _make_png_bytes(width=1600, height=1200, dpi=(300, 300))
    loaded = load_image_from_bytes(raw, filename="test_scan.png")
    assert loaded.width == 1600
    assert loaded.height == 1200
    assert loaded.image_bgr.shape == (1200, 1600, 3)
    assert loaded.dpi is not None
    assert abs(loaded.dpi - 300.0) < 0.5
    assert loaded.format_name == "PNG"


def test_load_tiff_full_resolution() -> None:
    arr = np.full((1000, 1400, 3), 240, dtype=np.uint8)
    pil_img = Image.fromarray(arr)
    buf = io.BytesIO()
    pil_img.save(buf, format="TIFF", dpi=(600, 600))
    loaded = load_image_from_bytes(buf.getvalue(), filename="flatbed.tiff")
    assert loaded.width == 1400
    assert loaded.height == 1000
    assert loaded.dpi is not None
    assert abs(loaded.dpi - 600.0) < 0.5


def test_exif_orientation_correction() -> None:
    arr = np.zeros((1200, 900, 3), dtype=np.uint8)
    arr[:100, :, :] = (255, 0, 0)
    pil_img = Image.fromarray(arr)
    exif = pil_img.getexif()
    exif[274] = 6
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", exif=exif.tobytes(), quality=95)

    loaded = load_image_from_bytes(buf.getvalue(), filename="rotated_exif.jpg")
    assert loaded.exif_orientation_applied is True
    assert loaded.width == 1200
    assert loaded.height == 900


def test_reject_small_image() -> None:
    raw_small = _make_png_bytes(width=640, height=480)
    with pytest.raises(ImageLoadError, match="too small"):
        load_image_from_bytes(raw_small, filename="tiny.png")


def test_reject_non_image_and_corrupt_bytes() -> None:
    with pytest.raises(ImageLoadError, match="not a valid image|Unsupported"):
        load_image_from_bytes(b"not an image at all", filename="fake.png")

    with pytest.raises(ImageLoadError, match="Unsupported file extension"):
        load_image_from_bytes(b"hello world", filename="notes.txt")

    with pytest.raises(ImageLoadError, match="empty"):
        load_image_from_bytes(b"", filename="empty.jpg")
