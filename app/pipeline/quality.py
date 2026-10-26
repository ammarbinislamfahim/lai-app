"""Quality control, warning aggregation, confidence scoring, and edge-uncertainty estimation (Phase 7 & Issue B)."""

from dataclasses import dataclass

import numpy as np

from app import config
from app.pipeline.calibration import CalibrationResult
from app.pipeline.measurement import MeasurementResult
from app.pipeline.segmentation import SegmentationResult


@dataclass(frozen=True)
class QualityReport:
    """Comprehensive quality control report for a single analyzed image."""

    confidence: str             # "HIGH", "MEDIUM", or "LOW"
    warnings: list[str]         # Ordered list of all warnings (never hidden)
    uncertainty_cm2: float      # Edge pixel uncertainty: ± (perimeter_px * 0.5) / (px_per_cm^2)
    uncertainty_pct: float      # Uncertainty as percentage of total leaf area
    leaf_area_fraction: float   # Fraction of total image area covered by leaves


def evaluate_quality(
    image_width: int,
    image_height: int,
    calibration: CalibrationResult,
    segmentation: SegmentationResult,
    measurement: MeasurementResult,
) -> QualityReport:
    """Evaluate all Phase 7 quality checks, uncertainty, and overall confidence level."""
    warnings: list[str] = []

    # Combine extra calibration square counts from calibration and segmentation (Issue B)
    total_extra_squares = getattr(calibration, "extra_squares_excluded", 0) + getattr(
        segmentation, "extra_squares_removed", 0
    )

    # 1. Include calibration warnings (tilt, DPI fallback, manual scale)
    for w in calibration.warnings:
        if "extra calibration-sized square(s) detected and excluded from leaf area." in w:
            continue
        if w not in warnings:
            warnings.append(w)

    # 2. Include segmentation warnings (border-touching leaves)
    for w in segmentation.warnings:
        if "extra calibration-sized square(s) detected and excluded from leaf area." in w:
            continue
        if w not in warnings:
            warnings.append(w)

    if total_extra_squares > 0:
        warnings.append(
            f"{total_extra_squares} extra calibration-sized square(s) detected and excluded from leaf area."
        )

    # 3. Include measurement warnings (touching/overlapping leaves)
    for w in measurement.warnings:
        if w not in warnings:
            warnings.append(w)

    px_per_cm = float(calibration.px_per_cm or 0.0)
    px_per_cm2 = float(px_per_cm ** 2) if px_per_cm > 0 else 1.0

    # 4. Edge-pixel uncertainty estimate: ± (perimeter_px * 0.5 px) converted to cm^2
    uncertainty_px = float(np.float64(measurement.total_perimeter_px) * np.float64(config.EDGE_UNCERTAINTY_PX))
    uncertainty_cm2 = float(np.float64(uncertainty_px) / np.float64(px_per_cm2)) if px_per_cm > 0 else 0.0
    uncertainty_pct = (
        float((uncertainty_cm2 / measurement.total_area_cm2) * 100.0)
        if measurement.total_area_cm2 > 0
        else 0.0
    )

    # 5. Low resolution check (< 50 px/cm)
    low_res = False
    if 0 < px_per_cm < config.LOW_RESOLUTION_PX_PER_CM:
        low_res = True
        warnings.append(
            f"low image resolution ({px_per_cm:.1f} px/cm < {config.LOW_RESOLUTION_PX_PER_CM:.0f} px/cm); "
            f"estimated edge uncertainty is ±{uncertainty_cm2:.2f} cm² (±{uncertainty_pct:.1f}%)."
        )

    # 6. Contrast check
    low_contrast = False
    if measurement.leaf_count > 0 and segmentation.contrast_score < config.MIN_CONTRAST_FOREGROUND_SCORE:
        low_contrast = True
        warnings.append(
            f"low contrast between leaf and background (score {segmentation.contrast_score:.1f} < "
            f"{config.MIN_CONTRAST_FOREGROUND_SCORE:.1f})."
        )

    # 7. Suspicious results check (zero leaves found, or leaf area > 60% of image)
    total_image_px = max(1, image_width * image_height)
    leaf_area_fraction = float(measurement.total_area_px / total_image_px)
    suspicious = False

    if measurement.leaf_count == 0:
        suspicious = True
        warnings.append("no leaves detected in the image (total leaf area is 0.00 cm²).")
    elif leaf_area_fraction > config.MAX_REASONABLE_LEAF_AREA_FRACTION:
        suspicious = True
        warnings.append(
            f"suspicious segmentation: leaf area covers {leaf_area_fraction * 100:.1f}% of the image "
            f"(exceeds {config.MAX_REASONABLE_LEAF_AREA_FRACTION * 100:.0f}% threshold; check background lighting)."
        )

    # Determine overall confidence (HIGH / MEDIUM / LOW)
    confidence = calibration.confidence
    if (
        calibration.confidence == "LOW"
        or calibration.method_used in {"manual", "none"}
        or suspicious
        or low_contrast
    ):
        confidence = "LOW"
    elif (
        calibration.method_used != "calibration_square"
        or low_res
        or segmentation.border_objects_removed > 0
        or measurement.touching_leaves_detected
    ):
        if confidence == "HIGH":
            confidence = "MEDIUM"

    return QualityReport(
        confidence=confidence,
        warnings=warnings,
        uncertainty_cm2=uncertainty_cm2,
        uncertainty_pct=uncertainty_pct,
        leaf_area_fraction=leaf_area_fraction,
    )
