"""Centralized configuration and constants for the Leaf Area & LAI Measurement Pipeline.

All numerical thresholds, color ranges, morphological parameters, and accuracy
guardrails live in this module so no magic numbers are scattered across the codebase.
"""

import os
from typing import Final

# Application metadata (single source of truth for version across CLI, UI, exports, and installers)
SOFTWARE_NAME: Final[str] = "LeafArea & LAI Analyzer"
SOFTWARE_VERSION: Final[str] = "1.5.6"

# Phase 2 Packaging: Configurable upload size limit (default 60 MB)
MAX_UPLOAD_MB: int = int(os.environ.get("LEAFAREA_MAX_UPLOAD_MB", "60"))
MAX_UPLOAD_BYTES: int = MAX_UPLOAD_MB * 1024 * 1024

# Phase 1: Image Loading & Validation
ALLOWED_EXTENSIONS: Final[frozenset[str]] = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff"})
ALLOWED_MIME_TYPES: Final[frozenset[str]] = frozenset({
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/x-tiff",
})
MIN_IMAGE_WIDTH_PX: Final[int] = 800       # Reject images narrower than 800 px
MIN_IMAGE_HEIGHT_PX: Final[int] = 800      # Reject images shorter than 800 px
DISPLAY_MAX_DIMENSION_PX: Final[int] = 1400  # Max width/height for browser overlay preview ONLY
CM_PER_INCH: Final[float] = 2.54           # Exact cm per inch for DPI conversion

# Phase 3: Calibration Square Detection
DEFAULT_CALIBRATION_SIDE_CM: Final[float] = 2.00  # Default side length of calibration square (cm)
SUPPORTED_CALIBRATION_COLORS: Final[frozenset[str]] = frozenset({"blue", "red"})

# OpenCV HSV ranges: H in [0, 179], S in [0, 255], V in [0, 255]
# Saturation threshold 115 corresponds to the 50% anti-aliased edge midpoint for royal blue/red on white paper
BLUE_HSV_LOWER: Final[tuple[int, int, int]] = (95, 115, 50)
BLUE_HSV_UPPER: Final[tuple[int, int, int]] = (138, 255, 255)

RED_HSV_LOWER_1: Final[tuple[int, int, int]] = (0, 115, 50)
RED_HSV_UPPER_1: Final[tuple[int, int, int]] = (10, 255, 255)
RED_HSV_LOWER_2: Final[tuple[int, int, int]] = (165, 115, 50)
RED_HSV_UPPER_2: Final[tuple[int, int, int]] = (179, 255, 255)

CALIB_MIN_AREA_PX: Final[int] = 900               # Minimum pixel area for calibration square candidate (~30x30 px)
CALIB_MAX_AREA_FRACTION: Final[float] = 0.25      # Max fraction of image area for calibration square
CALIB_MIN_ASPECT_RATIO: Final[float] = 0.85       # Min aspect ratio (width/height) of minAreaRect (allows mild tilt)
CALIB_MAX_ASPECT_RATIO: Final[float] = 1.18       # Max aspect ratio (width/height) of minAreaRect (allows mild tilt)
CALIB_MIN_SOLIDITY: Final[float] = 0.94           # Minimum contour solidity (area / convex_hull_area)
CALIB_APPROX_POLY_EPSILON_FACTOR: Final[float] = 0.035  # Epsilon multiplier for cv2.approxPolyDP perimeter
CALIB_EXPECTED_CORNERS: Final[int] = 4            # Expected polygon vertex count for calibration square
CALIB_MAX_SIDE_DIFF_RATIO: Final[float] = 0.02    # 2% max side length difference before perspective correction
CALIB_EXTREME_TILT_RATIO: Final[float] = 0.15     # 15% max side length difference; above this, reject correction
CALIB_SCALE_DISAGREE_RATIO: Final[float] = 0.01   # 1% max disagreement between area-based and edge-based scale
CALIB_MASK_DILATION_PX: Final[int] = 5            # Safety dilation (px) when masking out calibration square
PERSPECTIVE_MAX_CANVAS_MULTIPLIER: Final[float] = 2.5  # Cap warped canvas dimensions at 2.5x original

# Issue B: Geometry-only safeguard for extra calibration-sized squares
EXTRA_CALIB_MIN_ASPECT_RATIO: Final[float] = 0.90  # Aspect ratio lower bound (0.9 to 1.1)
EXTRA_CALIB_MAX_ASPECT_RATIO: Final[float] = 0.10 + 1.00  # Aspect ratio upper bound (0.9 to 1.1)
EXTRA_CALIB_MIN_SOLIDITY: Final[float] = 0.95      # Minimum solidity (>= 0.95)
EXTRA_CALIB_AREA_TOLERANCE: Final[float] = 0.15    # Pixel area within ±15% of (known_side_cm * px_per_cm)^2
EXTRA_CALIB_MIN_EXTENT: Final[float] = 0.88        # Rectangular fill ratio to distinguish squares from circles

# Phase 4: Leaf Segmentation & Masked Illumination Normalization (Item 1 & Item 3)
SEG_GAUSSIAN_BLUR_KERNEL: Final[tuple[int, int]] = (3, 3)  # Light 3x3 Gaussian blur for sensor noise
SEG_ILLUMINATION_KERNEL_FRACTION: Final[float] = 0.4       # Stopgap morphological kernel fraction (Item 1.1)
SEG_ILLUMINATION_MIN_KERNEL_PX: Final[int] = 101           # Minimum odd kernel size
SEG_ILLUM_DOWNSAMPLE_SCALE: Final[float] = 0.125           # 1/8 downsample factor for masked lighting field
SEG_ILLUM_BRIGHT_PERCENTILE: Final[float] = 50.0           # Brightest 50% of pixels used for initial paper color
SEG_ILLUM_DILATE_CM: Final[float] = 1.0                    # Dilate rough foreground mask by ~1.0 cm
SEG_ILLUM_FALLBACK_DILATE_FRAC: Final[float] = 0.03        # Fallback dilation: 3% of short side if scale unknown
SEG_ILLUM_SIGMA_FRAC: Final[float] = 0.10                  # Gaussian sigma = 10% of small image short side
SEG_ILLUM_MIN_WEIGHT: Final[float] = 1e-3                  # Minimum GaussianBlur(w) weight before fallback fill
SEG_BG_PERCENTILE: Final[float] = 90.0                     # High-brightness percentile to estimate paper Lab color
SEG_WEIGHT_LAB_DIST: Final[float] = 0.65                   # Weight of CIELAB color/lightness distance from white background
SEG_WEIGHT_EXG: Final[float] = 0.35                        # Weight of Excess Green / chromaticity index
EDGE_REFINE_RADIUS_PX: Final[int] = 3                      # 3 px erosion/dilation band for edge midpoint refinement (Item 3)

# Shadow rejection parameters in CIELAB & Excess Green
SHADOW_MAX_CHROMA_AB: Final[float] = 9.5          # Maximum Lab chroma sqrt(a_diff^2 + b_diff^2) for a neutral gray shadow
SHADOW_MIN_LIGHTNESS_L: Final[float] = 115.0      # Minimum OpenCV L* (0..255 scale) for cast shadows on white background
SHADOW_MAX_EXG_NORM: Final[float] = 0.06          # Max normalized Excess Green for a neutral shadow pixel

# Morphological cleanup thresholds (converted to pixels dynamically using px_per_cm)
MIN_SPECK_AREA_CM2: Final[float] = 0.05           # Remove dust/specks smaller than 0.05 cm^2
MAX_NOISE_HOLE_AREA_CM2: Final[float] = 0.01      # Fill only tiny noise holes smaller than 0.01 cm^2; keep insect holes!
BORDER_MARGIN_PX: Final[int] = 2                  # Pixel margin from image edge to detect cut-off border leaves

# Phase 5: Connected Components & Measurement
CC_CONNECTIVITY: Final[int] = 8                   # 8-connectivity for connectedComponentsWithStats
MERGED_LEAF_MAX_SOLIDITY: Final[float] = 0.95     # Pre-filter solidity above which an object is convex (cannot be pinched)
MERGED_LEAF_AREA_MULTIPLIER: Final[float] = 2.6   # Area > 2.6x median leaf area in multi-leaf batches
WATERSHED_MIN_PEAK_DIST_CM: Final[float] = 0.6    # Minimum distance between leaf centers for watershed splitting

# Phase 6: LAI Calculation
CM2_PER_M2: Final[float] = 10000.0                # 1 m^2 = 10,000 cm^2

# Phase 7: Quality Control & Uncertainty
LOW_RESOLUTION_PX_PER_CM: Final[float] = 50.0     # Warn if scale < 50 px/cm
EDGE_UNCERTAINTY_PX: Final[float] = 0.5           # Half-pixel edge uncertainty per perimeter pixel
MAX_REASONABLE_LEAF_AREA_FRACTION: Final[float] = 0.60  # Warn if leaf area exceeds 60% of total image area
MIN_CONTRAST_FOREGROUND_SCORE: Final[float] = 18.0      # Warn if Otsu foreground/background separation is weak

# Display rounding rules (Rule 8: float64 internally, round only for display)
DISPLAY_DECIMALS_CM2: Final[int] = 2
DISPLAY_DECIMALS_LAI: Final[int] = 3
DISPLAY_DECIMALS_SCALE: Final[int] = 2
