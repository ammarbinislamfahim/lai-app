"""Phase 2, Phase 3, Item 2, and Item 4 tests:
- Method A calibration accuracy (<= 0.5%) across all synthetic images.
- Item 2: Rotated square pixel-area calibration accuracy (<= 0.5%) at 0°, 10°, 17°, 30°, 45° across 100, 60, and 40 px/cm,
  plus scale disagreement warning (> 1% difference between area-based and edge-based scale -> MEDIUM confidence).
- Item 4: Mild/moderate perspective tilt (2% < side diff <= 15%) triggers perspective warp correction with MEDIUM confidence,
  while extreme tilt (> 15%) is not warped and returns LOW confidence with a retake warning.
- Method B (DPI fallback) and Method C (manual scale).
"""

import json
import math
from pathlib import Path

import cv2
import numpy as np
import pytest

from app import config
from app.pipeline.calibration import detect_calibration
from app.pipeline.loader import load_image
from app.pipeline.measurement import measure_leaves
from app.pipeline.segmentation import segment_leaves
from tests.make_synthetic import (
    BLUE_SQUARE_BGR,
    BRIGHT_GREEN_LEAF_BGR,
    PAPER_WHITE_BGR,
    draw_aa_ellipse,
    draw_aa_rotated_square,
    generate_all_synthetic_images,
)

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_images"


@pytest.fixture(scope="session", autouse=True)
def ensure_synthetic_images() -> None:
    if not (SAMPLE_DIR / "01_clean_standard.json").exists():
        generate_all_synthetic_images(SAMPLE_DIR, include_large_suite_on_disk=True)


def test_method_a_calibration_accuracy_all_synthetic() -> None:
    """Recovered px/cm on all original synthetic images must be within 0.5% of true value (100.0 px/cm)."""
    json_files = sorted(SAMPLE_DIR.glob("0*.json"))
    assert len(json_files) >= 9

    for jf in json_files:
        meta = json.loads(jf.read_text(encoding="utf-8"))
        loaded = load_image(SAMPLE_DIR / meta["image_filename"])
        cal = detect_calibration(
            loaded.image_bgr,
            known_side_cm=meta["calib_side_cm"],
            color=meta["calib_color"],
            dpi=loaded.dpi,
        )
        assert cal.method_used == "calibration_square", f"Failed on {jf.stem}"
        assert cal.px_per_cm is not None
        rel_err_pct = abs(cal.px_per_cm - meta["true_px_per_cm"]) / meta["true_px_per_cm"] * 100.0
        assert rel_err_pct <= 0.5, f"{jf.stem}: calibration error {rel_err_pct:.4f}% > 0.5%"
        assert cal.confidence == "HIGH"


def test_item2_rotated_squares_across_angles_and_resolutions() -> None:
    """Item 2: Test square rotated by 0, 10, 17, 30, and 45 deg at 100, 60, and 40 px/cm (scale error <= 0.5%)."""
    for scale in (100.0, 60.0, 40.0):
        w = max(800, int(round(24.0 * scale)))
        h = max(800, int(round(20.0 * scale)))
        for angle in (0.0, 10.0, 17.0, 30.0, 45.0):
            canvas = np.full((h, w, 3), PAPER_WHITE_BGR, dtype=np.uint8)
            draw_aa_rotated_square(
                canvas,
                center_px=(5.0 * scale, 5.0 * scale),
                side_px=2.0 * scale,
                angle_deg=angle,
                color_bgr=BLUE_SQUARE_BGR,
            )
            cal = detect_calibration(canvas, known_side_cm=2.0, color="blue")
            assert cal.method_used == "calibration_square"
            assert cal.px_per_cm is not None
            err_pct = abs(cal.px_per_cm - scale) / scale * 100.0
            assert err_pct <= 0.5, (
                f"Rotated square scale={scale}, angle={angle}°: error {err_pct:.4f}% > 0.5%"
            )


def test_item2_scale_disagreement_warning() -> None:
    """Item 2: If area-based scale and edge-length scale differ by > 1%, flag warning and lower confidence to MEDIUM."""
    canvas = np.full((1000, 1000, 3), PAPER_WHITE_BGR, dtype=np.uint8)
    # Draw a 200x196 rectangle (aspect ratio 1.02, side diff 2.0% <= 2% tilt limit,
    # or a slightly rounded/chamfered square where pixel area differs from edge length by > 1%)
    canvas[200:400, 200:400] = BLUE_SQUARE_BGR
    # Carve out a small interior notch or chamfer that keeps 4 outer corners and solidity > 0.94
    # while reducing pixel area by ~2.5% (> 1% scale difference = ~2% area difference)
    canvas[290:310, 290:310] = PAPER_WHITE_BGR
    # Wait: cv2.drawContours(raw_fill_mask, [contour], -1, 1, thickness=-1) fills the outer contour!
    # To make outer contour area differ from edge length by > 1% without failing tilt check (< 2% side diff),
    # draw a slightly pinched 4-corner cushion shape (sides bow inward by 3 px while corners stay 200x200)
    canvas[:] = PAPER_WHITE_BGR
    pts = np.array([
        [200, 200], [300, 204], [400, 200],
        [396, 300], [400, 400],
        [300, 396], [200, 400],
        [204, 300],
    ], dtype=np.int32)
    cv2.fillPoly(canvas, [pts], BLUE_SQUARE_BGR)
    cal = detect_calibration(canvas, known_side_cm=2.0, color="blue")
    assert cal.method_used == "calibration_square"
    assert cal.confidence == "MEDIUM"
    assert any("calibration square measurements disagree" in w for w in cal.warnings)


def test_item4_perspective_tilt_correction_and_extreme_tilt_rejection() -> None:
    """Item 4: Mild tilt (~8 deg) warps image, sets MEDIUM confidence, and achieves <= 2% area error near square;
    extreme tilt (> 15%) does NOT warp and returns LOW confidence with retake warning.
    """
    w, h = 2400, 1600
    canvas = np.full((h, w, 3), PAPER_WHITE_BGR, dtype=np.uint8)
    # 2x2 cm square at (200..400, 200..400) -> 100 px/cm
    canvas[200:400, 200:400] = BLUE_SQUARE_BGR
    # Leaf 1 near the calibration square: 6x4 cm ellipse centered at (750, 400)
    true_leaf_cm2 = float(math.pi * 3.0 * 2.0)
    draw_aa_ellipse(canvas, (750.0, 400.0), 300.0, 200.0, 0.0, BRIGHT_GREEN_LEAF_BGR)
    # Leaf 2 far from the calibration square: 6x4 cm ellipse centered at (1850, 1150)
    draw_aa_ellipse(canvas, (1850.0, 1150.0), 300.0, 200.0, 0.0, BRIGHT_GREEN_LEAF_BGR)

    # Apply ~8 degree perspective tilt homography (~3.8% side difference on calibration square)
    src_sheet = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    dst_sheet = np.array([[110, 80], [w - 110, 60], [w - 20, h - 40], [20, h - 20]], dtype=np.float32)
    H_tilt = cv2.getPerspectiveTransform(src_sheet, dst_sheet)
    tilted_img = cv2.warpPerspective(
        canvas, H_tilt, (w, h), flags=cv2.INTER_LINEAR, borderValue=PAPER_WHITE_BGR
    )

    cal = detect_calibration(tilted_img, known_side_cm=2.0, color="blue")
    assert cal.perspective_corrected is True
    assert cal.rectified_image_bgr is not None
    assert cal.confidence == "MEDIUM"
    assert any("perspective corrected from calibration square only" in w for w in cal.warnings)

    seg = segment_leaves(cal.rectified_image_bgr, cal.px_per_cm, cal.calibration_square_mask)
    meas = measure_leaves(seg.leaf_mask, cal.px_per_cm)
    assert meas.leaf_count == 2

    # Sort leaves by distance from calibration square (top-left)
    near_leaf = min(meas.leaves, key=lambda l: math.hypot(l.centroid_px[0], l.centroid_px[1]))
    far_leaf = max(meas.leaves, key=lambda l: math.hypot(l.centroid_px[0], l.centroid_px[1]))

    near_err_pct = abs(near_leaf.area_cm2 - true_leaf_cm2) / true_leaf_cm2 * 100.0
    far_err_pct = abs(far_leaf.area_cm2 - true_leaf_cm2) / true_leaf_cm2 * 100.0
    print(
        f"Perspective ~8° tilt correction -> near-square leaf error: {near_err_pct:.3f}% (<= 2.0% limit), "
        f"far-from-square leaf error: {far_err_pct:.3f}%"
    )
    assert near_err_pct <= 2.0, f"Near-square leaf error {near_err_pct:.3f}% > 2.0%"

    # Extreme tilt (> 15% side difference): must NOT warp, must return LOW confidence & retake warning
    canvas_ext = np.full((1200, 1200, 3), PAPER_WHITE_BGR, dtype=np.uint8)
    pts_ext = np.array([[200, 200], [370, 200], [420, 410], [180, 410]], dtype=np.int32)
    cv2.fillPoly(canvas_ext, [pts_ext], BLUE_SQUARE_BGR)
    cal_ext = detect_calibration(canvas_ext, known_side_cm=2.0, color="blue")
    assert cal_ext.perspective_corrected is False
    assert cal_ext.rectified_image_bgr is None
    assert cal_ext.confidence == "LOW"
    assert any("retaken" in w or "camera tilt detected" in w for w in cal_ext.warnings)


def test_method_b_dpi_fallback() -> None:
    """When no calibration square is present, fallback to DPI metadata with MEDIUM confidence and warning."""
    canvas = np.full((1200, 1200, 3), PAPER_WHITE_BGR, dtype=np.uint8)
    cal = detect_calibration(canvas, known_side_cm=2.0, color="blue", dpi=254.0)
    assert cal.method_used == "dpi_metadata"
    assert cal.px_per_cm == pytest.approx(100.0, rel=1e-4)
    assert cal.confidence == "MEDIUM"
    assert any("scale came from file metadata, not verified" in w for w in cal.warnings)


def test_method_c_needs_manual_scale_and_manual_override() -> None:
    """When both Method A and Method B fail, return needs_manual_scale=True and never guess a scale."""
    canvas = np.full((1200, 1200, 3), PAPER_WHITE_BGR, dtype=np.uint8)
    cal_missing = detect_calibration(canvas, known_side_cm=2.0, color="blue", dpi=None)
    assert cal_missing.needs_manual_scale is True
    assert cal_missing.px_per_cm is None
    assert cal_missing.method_used == "none"

    cal_manual = detect_calibration(
        canvas, known_side_cm=2.0, color="blue", dpi=None, manual_px_per_cm=120.0
    )
    assert cal_manual.needs_manual_scale is False
    assert cal_manual.px_per_cm == pytest.approx(120.0)
    assert cal_manual.method_used == "manual"
    assert cal_manual.confidence == "LOW"
