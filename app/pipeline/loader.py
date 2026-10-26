"""Image loading, full-resolution decoding, EXIF orientation correction, and DPI extraction."""

from dataclasses import dataclass
import io
from pathlib import Path
from typing import Optional, Union

import cv2
import numpy as np
from PIL import Image, ImageOps

from app import config


class ImageLoadError(ValueError):
    """Raised when an uploaded file is not a valid image, is corrupt, or is below minimum resolution."""


@dataclass(frozen=True)
class LoadedImage:
    """Immutable container for a full-resolution BGR image and its metadata."""

    image_bgr: np.ndarray
    width: int
    height: int
    dpi: Optional[float]
    exif_orientation_applied: bool
    filename: str
    format_name: str


def _extract_dpi(pil_img: Image.Image) -> Optional[float]:
    """Extract horizontal/vertical DPI from PIL image metadata or EXIF tags if valid."""
    info_dpi = pil_img.info.get("dpi")
    if info_dpi and isinstance(info_dpi, (tuple, list)) and len(info_dpi) >= 2:
        try:
            dpi_x = float(info_dpi[0])
            dpi_y = float(info_dpi[1])
            if dpi_x > 10.0 and dpi_y > 10.0:
                return float((dpi_x + dpi_y) / 2.0)
        except (TypeError, ValueError):
            pass

    # Fallback: check EXIF XResolution (282) / YResolution (283) and ResolutionUnit (296)
    try:
        exif = pil_img.getexif()
        if exif:
            x_res = exif.get(282)
            y_res = exif.get(283)
            unit = exif.get(296, 2)  # 2 = inches, 3 = centimeters
            if x_res is not None and y_res is not None:
                val_x = float(x_res[0] / x_res[1]) if isinstance(x_res, tuple) else float(x_res)
                val_y = float(y_res[0] / y_res[1]) if isinstance(y_res, tuple) else float(y_res)
                mean_res = (val_x + val_y) / 2.0
                if unit == 3 and mean_res > 4.0:
                    # Convert pixels per cm to DPI
                    return float(mean_res * config.CM_PER_INCH)
                if unit == 2 and mean_res > 10.0 and mean_res != 72.0:
                    return float(mean_res)
                if unit == 2 and mean_res == 72.0:
                    return 72.0
    except Exception:
        pass

    return None


def load_image_from_bytes(data: bytes, filename: str = "upload.png") -> LoadedImage:
    """Load JPG/PNG/TIFF from raw bytes at full resolution with EXIF orientation correction.

    Never resizes the measurement image. Rejects non-images, corrupt files,
    unsupported formats, or images smaller than 800x800 px.
    """
    if not data or len(data) == 0:
        raise ImageLoadError(f"Uploaded file '{filename}' is empty.")

    ext = Path(filename).suffix.lower()
    if ext and ext not in config.ALLOWED_EXTENSIONS:
        allowed_str = ", ".join(sorted(config.ALLOWED_EXTENSIONS))
        raise ImageLoadError(
            f"Unsupported file extension '{ext}' for '{filename}'. Allowed formats: {allowed_str}."
        )

    # First verify integrity and read EXIF/DPI with Pillow
    try:
        with Image.open(io.BytesIO(data)) as pil_check:
            pil_check.verify()
    except Exception as exc:
        raise ImageLoadError(
            f"File '{filename}' is not a valid image or is corrupt: {exc}"
        ) from exc

    try:
        pil_img = Image.open(io.BytesIO(data))
        format_name = (pil_img.format or "").upper()
        if format_name not in {"JPEG", "PNG", "TIFF", "MPO"}:
            raise ImageLoadError(
                f"Unsupported image format '{format_name}' in '{filename}'. Only JPG, PNG, and TIFF are supported."
            )

        dpi = _extract_dpi(pil_img)

        # Check if EXIF orientation tag (0x0112 = 274) is present and != 1
        exif = pil_img.getexif()
        orientation_tag = exif.get(274, 1) if exif else 1
        exif_orientation_applied = orientation_tag not in (None, 1)

        if exif_orientation_applied:
            # Apply lossless EXIF transpose via PIL and convert to RGB, then BGR for OpenCV
            pil_oriented = ImageOps.exif_transpose(pil_img)
            rgb_arr = np.asarray(pil_oriented.convert("RGB"), dtype=np.uint8)
            image_bgr = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2BGR)
        else:
            # Decode at full resolution directly with OpenCV
            buf = np.frombuffer(data, dtype=np.uint8)
            decoded = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            if decoded is None:
                # Fallback for esoteric 16-bit/CMYK TIFFs via PIL
                rgb_arr = np.asarray(pil_img.convert("RGB"), dtype=np.uint8)
                image_bgr = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2BGR)
            else:
                image_bgr = decoded
    except ImageLoadError:
        raise
    except Exception as exc:
        raise ImageLoadError(
            f"Failed to decode full-resolution image '{filename}': {exc}"
        ) from exc

    if image_bgr is None or image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        raise ImageLoadError(f"Decoded image '{filename}' does not have 3 color channels.")

    height, width = int(image_bgr.shape[0]), int(image_bgr.shape[1])
    if width < config.MIN_IMAGE_WIDTH_PX or height < config.MIN_IMAGE_HEIGHT_PX:
        raise ImageLoadError(
            f"Image '{filename}' resolution ({width}×{height} px) is too small. "
            f"Minimum required size is {config.MIN_IMAGE_WIDTH_PX}×{config.MIN_IMAGE_HEIGHT_PX} px "
            f"to ensure accurate leaf area measurement."
        )

    return LoadedImage(
        image_bgr=image_bgr,
        width=width,
        height=height,
        dpi=dpi,
        exif_orientation_applied=exif_orientation_applied,
        filename=filename,
        format_name=format_name,
    )


def load_image(path: Union[str, Path]) -> LoadedImage:
    """Load an image file from disk at full resolution."""
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise ImageLoadError(f"Image file not found: '{file_path}'")
    return load_image_from_bytes(file_path.read_bytes(), filename=file_path.name)
