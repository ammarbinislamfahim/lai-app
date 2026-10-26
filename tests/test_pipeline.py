"""Phase 4, 5, 6, 7 and Follow-Up Items 1, 3, 5, 6 plus Items B, C, E tests:
- Item 1.3: Large-leaf anti-aliased suite (Cases A, B, C, D across 100, 60, 40, 25 px/cm, 0° & 17°, clean & JPEG90+blur0.8+noise).
- Item 3: Edge threshold refinement (`edge_threshold`) achieves mean bias < 0.05% on clean synthetic images.
- Item 5: ImageJ validation template, guide, and `compare.py` verification.
- Item 6: Zero deprecation warnings during segmentation cleanup.
- Issue B & Item C:
  1. Synthetic image with blue 2 cm square, red 2 cm square, and green 10 cm x 10 cm square (100 cm^2):
     asserts area within 1% of 100 cm^2, leaf_count == 1, and extra calibration-sized square warning appears.
  2. Synthetic image with blue 2 cm square and red 3 cm x 1.5 cm elliptical leaf:
     asserts red leaf IS measured and NOT removed by the safeguard.
- Issue E: Calibration sheet image at ~59.1 px/cm with blue 2 cm square, red 2 cm square, and 10x10 cm green square:
  reports both area-based and edge-based scale estimates and verifies area-based scale eliminates the +0.25% scale / -0.5% area error.
"""

import json
import math
from pathlib import Path
import warnings

import cv2
import numpy as np
import pytest

from app import config
from app.pipeline import segmentation as seg_mod
from app.pipeline.calibration import detect_calibration
from app.pipeline.lai import calculate_lai
from app.pipeline.loader import load_image
from app.pipeline.measurement import measure_leaves
from app.pipeline.quality import evaluate_quality
from app.pipeline.segmentation import _normalize_illumination_legacy, segment_leaves
from tests.make_synthetic import (
    BLUE_SQUARE_BGR,
    GREEN_LEAF_BGR,
    PAPER_WHITE_BGR,
    RED_SQUARE_BGR,
    draw_aa_rotated_square,
    generate_all_synthetic_images,
    render_large_leaf_scene,
)
from validation.compare import compare_validation_csv

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_images"
VALIDATION_DIR = Path(__file__).resolve().parent.parent / "validation"


@pytest.fixture(scope="session", autouse=True)
def ensure_synthetic_images() -> None:
    if not (SAMPLE_DIR / "10_extra_calib_square.json").exists():
        generate_all_synthetic_images(SAMPLE_DIR, include_large_suite_on_disk=True)


def test_segmentation_and_measurement_accuracy_across_all_synthetic() -> None:
    """Verify segmented area error <= 0.5% on clean images and <= 1.0% on all original synthetic variants,
    and verify mean bias on clean images is < 0.05% (Item 3).
    """
    clean_cases = {"01_clean_standard", "02_leaf_with_hole", "07_dust_specks", "08_yellow_brown_leaves"}
    json_files = sorted(SAMPLE_DIR.glob("0*.json"))
    clean_signed_errors: list[float] = []

    for jf in json_files:
        meta = json.loads(jf.read_text(encoding="utf-8"))
        loaded = load_image(SAMPLE_DIR / meta["image_filename"])
        cal = detect_calibration(
            loaded.image_bgr,
            known_side_cm=meta["calib_side_cm"],
            color=meta["calib_color"],
            dpi=loaded.dpi,
        )
        assert cal.px_per_cm is not None

        with warnings.catch_warnings(record=True) as caught_warns:
            warnings.simplefilter("always", DeprecationWarning)
            seg = segment_leaves(loaded.image_bgr, cal.px_per_cm, cal.calibration_square_mask)
            dep_warns = [w for w in caught_warns if issubclass(w.category, DeprecationWarning)]
            assert len(dep_warns) == 0, f"DeprecationWarning raised: {dep_warns}"

        assert seg.edge_threshold > 0
        meas = measure_leaves(seg.leaf_mask, cal.px_per_cm)

        signed_err_pct = (meas.total_area_cm2 - meta["true_area_cm2"]) / meta["true_area_cm2"] * 100.0
        err_pct = abs(signed_err_pct)
        if jf.stem in clean_cases:
            clean_signed_errors.append(signed_err_pct)
            assert err_pct <= 0.5, f"Clean case {jf.stem} error {err_pct:.3f}% exceeds 0.5%"
        else:
            assert err_pct <= 1.0, f"Variant case {jf.stem} error {err_pct:.3f}% exceeds 1.0%"

        assert meas.leaf_count == meta["true_leaf_count"], (
            f"{jf.stem}: expected {meta['true_leaf_count']} leaves, got {meas.leaf_count}"
        )

        if meta.get("expects_border_warning"):
            assert seg.border_objects_removed >= 1
            assert any("leaf cut off by image edge" in w for w in seg.warnings)

    mean_clean_bias = abs(float(np.mean(clean_signed_errors)))
    assert mean_clean_bias < 0.05, f"Mean bias on clean synthetic images {mean_clean_bias:.4f}% >= 0.05%"


def test_item_c1_extra_calibration_square_excluded_and_warned() -> None:
    """Item C.1 & Issue B: Synthetic image with blue 2 cm square, red 2 cm square, and green 10x10 cm square (100 cm^2).
    Asserts total leaf area is within 1% of 100 cm^2, leaf_count is 1, and the Issue B warning appears.
    """
    meta = json.loads((SAMPLE_DIR / "10_extra_calib_square.json").read_text(encoding="utf-8"))
    loaded = load_image(SAMPLE_DIR / meta["image_filename"])
    cal = detect_calibration(loaded.image_bgr, known_side_cm=2.0, color="blue")
    assert cal.px_per_cm == pytest.approx(100.0, rel=0.005)
    assert cal.extra_squares_excluded == 1

    seg = segment_leaves(loaded.image_bgr, cal.px_per_cm, cal.calibration_square_mask, known_side_cm=2.0)
    meas = measure_leaves(seg.leaf_mask, cal.px_per_cm)
    qual = evaluate_quality(loaded.width, loaded.height, cal, seg, meas)

    assert meas.leaf_count == 1, f"Expected 1 leaf (10x10 cm square), got {meas.leaf_count}"
    area_err_pct = abs(meas.total_area_cm2 - 100.0) / 100.0 * 100.0
    assert area_err_pct <= 1.0, f"Area error {area_err_pct:.4f}% exceeds 1.0% (measured {meas.total_area_cm2:.4f} cm^2)"
    assert any(
        "1 extra calibration-sized square(s) detected and excluded from leaf area." in w
        for w in qual.warnings
    ), f"Expected extra calibration square warning in {qual.warnings}"


def test_item_c2_red_elliptical_leaf_is_measured_not_excluded() -> None:
    """Item C.2 & Issue B.4: Image with a blue 2 cm square and a red 3 cm x 1.5 cm elliptical leaf.
    Asserts that the red leaf IS measured and NOT removed by the geometry-only safeguard.
    """
    meta = json.loads((SAMPLE_DIR / "11_red_elliptical_leaf.json").read_text(encoding="utf-8"))
    loaded = load_image(SAMPLE_DIR / meta["image_filename"])
    cal = detect_calibration(loaded.image_bgr, known_side_cm=2.0, color="blue")
    assert cal.px_per_cm == pytest.approx(100.0, rel=0.005)
    assert cal.extra_squares_excluded == 0

    seg = segment_leaves(loaded.image_bgr, cal.px_per_cm, cal.calibration_square_mask, known_side_cm=2.0)
    meas = measure_leaves(seg.leaf_mask, cal.px_per_cm)
    qual = evaluate_quality(loaded.width, loaded.height, cal, seg, meas)

    assert meas.leaf_count == 1, f"Red elliptical leaf must be measured as 1 leaf, got {meas.leaf_count}"
    true_ellipse_cm2 = float(math.pi * 1.5 * 0.75)  # 3.5342917 cm^2
    err_pct = abs(meas.total_area_cm2 - true_ellipse_cm2) / true_ellipse_cm2 * 100.0
    assert err_pct <= 1.0, f"Red elliptical leaf area error {err_pct:.3f}% > 1.0%"
    assert not any("extra calibration-sized square" in w for w in qual.warnings)


def test_issue_e_sheet_at_59_1_px_per_cm_scale_precision() -> None:
    """Issue E: Test sheet image at 59.1 px/cm with blue 2 cm square, red 2 cm square, and 10x10 cm green square.
    Verifies both area_px_per_cm and edge_px_per_cm are reported, and area_px_per_cm eliminates the +0.25% scale error.
    """
    true_scale = 59.1
    w, h = 1600, 1200
    canvas = np.full((h, w, 3), PAPER_WHITE_BGR, dtype=np.uint8)
    # Render anti-aliased 2.00 cm blue square (118.2 x 118.2 px) and 2.00 cm red square (118.2 x 118.2 px)
    draw_aa_rotated_square(canvas, (180.0, 180.0), 2.0 * true_scale, 2.5, BLUE_SQUARE_BGR, ss=8)
    draw_aa_rotated_square(canvas, (450.0, 180.0), 2.0 * true_scale, 2.5, RED_SQUARE_BGR, ss=8)
    # Render anti-aliased 10.00 cm x 10.00 cm green square (591.0 x 591.0 px -> true area 100.0000 cm^2)
    draw_aa_rotated_square(canvas, (850.0, 620.0), 10.0 * true_scale, 2.5, GREEN_LEAF_BGR, ss=8)

    cal = detect_calibration(canvas, known_side_cm=2.0, color="blue")
    assert cal.area_px_per_cm is not None
    assert cal.edge_px_per_cm is not None
    assert cal.extra_squares_excluded == 1

    scale_err_pct = abs(cal.px_per_cm - true_scale) / true_scale * 100.0
    assert scale_err_pct <= 0.1, f"Expected area-based scale error <= 0.1% at 59.1 px/cm, got {scale_err_pct:.4f}%"

    seg = segment_leaves(canvas, cal.px_per_cm, cal.calibration_square_mask, known_side_cm=2.0)
    meas = measure_leaves(seg.leaf_mask, cal.px_per_cm)
    assert meas.leaf_count == 1
    area_err_pct = abs(meas.total_area_cm2 - 100.0) / 100.0 * 100.0
    assert area_err_pct <= 0.2, f"Expected leaf area error <= 0.2% on 10x10 cm square at 59.1 px/cm, got {area_err_pct:.4f}%"


def test_item1_large_leaves_fail_on_old_code_and_pass_on_new_code() -> None:
    """Item 1.3: Verify large-leaf test cases fail on the old closing-based code (0.12)
    and pass all accuracy thresholds (scale <= 0.5%, clean area <= 1.0%, degraded area <= 2.0%) on new code.
    """
    img_b, meta_b = render_large_leaf_scene("B", scale_px_per_cm=100.0, angle_deg=0.0, degraded=False)
    cal_b = detect_calibration(img_b, known_side_cm=2.0, color="blue")
    orig_fn = seg_mod._normalize_illumination
    orig_frac = config.SEG_ILLUMINATION_KERNEL_FRACTION
    try:
        config.SEG_ILLUMINATION_KERNEL_FRACTION = 0.12  # type: ignore[misc]
        seg_mod._normalize_illumination = _normalize_illumination_legacy
        seg_old = segment_leaves(img_b, cal_b.px_per_cm, cal_b.calibration_square_mask)
        meas_old = measure_leaves(seg_old.leaf_mask, cal_b.px_per_cm)
        old_err_pct = abs(meas_old.total_area_cm2 - meta_b["true_area_cm2"]) / meta_b["true_area_cm2"] * 100.0
        assert old_err_pct > 25.0, (
            f"Expected old closing-based code (0.12) to hollow out large leaves (>25% error), got {old_err_pct:.2f}%"
        )
    finally:
        config.SEG_ILLUMINATION_KERNEL_FRACTION = orig_frac  # type: ignore[misc]
        seg_mod._normalize_illumination = orig_fn

    large_json_files = [
        SAMPLE_DIR / f"large_{cid}_s{int(sc)}_r{int(ang)}_{'jpg90' if deg else 'clean'}.json"
        for cid in ("A", "B", "C", "D")
        for sc in (100.0, 60.0, 40.0, 25.0)
        for ang in (0.0, 17.0)
        for deg in (False, True)
        if (SAMPLE_DIR / f"large_{cid}_s{int(sc)}_r{int(ang)}_{'jpg90' if deg else 'clean'}.json").is_file()
    ]
    assert len(large_json_files) == 64

    clean_errors_signed: list[float] = []
    for jf in large_json_files:
        meta = json.loads(jf.read_text(encoding="utf-8"))
        loaded = load_image(SAMPLE_DIR / meta["image_filename"])
        cal = detect_calibration(
            loaded.image_bgr,
            known_side_cm=meta["calib_side_cm"],
            color=meta["calib_color"],
        )
        assert cal.px_per_cm is not None
        scale_err_pct = abs(cal.px_per_cm - meta["true_px_per_cm"]) / meta["true_px_per_cm"] * 100.0
        assert scale_err_pct <= 0.5, (
            f"{jf.stem}: scale error {scale_err_pct:.4f}% > 0.5%"
        )

        seg = segment_leaves(loaded.image_bgr, cal.px_per_cm, cal.calibration_square_mask)
        meas = measure_leaves(seg.leaf_mask, cal.px_per_cm)
        signed_area_err = (meas.total_area_cm2 - meta["true_area_cm2"]) / meta["true_area_cm2"] * 100.0
        area_err_pct = abs(signed_area_err)

        if meta["degraded"]:
            assert area_err_pct <= 2.0, (
                f"Degraded large-leaf {jf.stem}: area error {area_err_pct:.3f}% > 2.0%"
            )
        else:
            if meta["case_id"] in {"A", "B", "C"}:
                clean_errors_signed.append(signed_area_err)
            assert area_err_pct <= 1.0, (
                f"Clean large-leaf {jf.stem}: area error {area_err_pct:.3f}% > 1.0%"
            )

    mean_large_clean_bias = abs(float(np.mean(clean_errors_signed)))
    assert mean_large_clean_bias < 0.05, (
        f"Mean bias on clean large-leaf cases {mean_large_clean_bias:.4f}% >= 0.05%"
    )


def test_real_holes_preserved_and_tiny_noise_holes_filled() -> None:
    """Ensure large insect-damage holes in 02_leaf_with_hole are NOT filled."""
    meta = json.loads((SAMPLE_DIR / "02_leaf_with_hole.json").read_text(encoding="utf-8"))
    loaded = load_image(SAMPLE_DIR / meta["image_filename"])
    cal = detect_calibration(loaded.image_bgr, known_side_cm=2.0, color="blue")
    seg = segment_leaves(loaded.image_bgr, cal.px_per_cm, cal.calibration_square_mask)

    assert seg.leaf_mask[980, 1450] == 0, "Large insect hole 1 was erroneously filled!"
    assert seg.leaf_mask[1060, 1650] == 0, "Large insect hole 2 was erroneously filled!"
    assert seg.leaf_mask[902, 1352] == 1, "Tiny 4x4 noise pinhole was not filled!"


def test_touching_leaves_detection_and_total_area_integrity() -> None:
    """When two leaves touch/merge, total area stays exact while a touching-leaves warning is raised."""
    canvas = np.full((1200, 1600, 3), PAPER_WHITE_BGR, dtype=np.uint8)
    mask_true = np.zeros((1200, 1600), dtype=np.uint8)
    cv2.circle(mask_true, (600, 600), 140, 1, thickness=-1)
    cv2.circle(mask_true, (870, 600), 140, 1, thickness=-1)
    mask_true[590:610, 600:870] = 1
    canvas[mask_true == 1] = GREEN_LEAF_BGR

    meas = measure_leaves(mask_true, px_per_cm=100.0)
    assert meas.touching_leaves_detected is True
    assert any("possible touching leaves" in w for w in meas.warnings)
    expected_cm2 = float(np.count_nonzero(mask_true)) / 10000.0
    assert meas.total_area_cm2 == pytest.approx(expected_cm2, rel=1e-6)


def test_lai_calculation_modes_and_validation() -> None:
    """Test Mode 1, Mode 2, batch summation, and input validation in lai.py."""
    res1 = calculate_lai(leaf_areas_cm2=5000.0, ground_area_m2=0.25, uncertainty_cm2=25.0)
    assert res1.mode_used == "mode_1"
    assert res1.lai == pytest.approx(2.0)
    assert res1.lai_uncertainty == pytest.approx(0.01)

    res2 = calculate_lai(
        leaf_areas_cm2=[3000.0, 3000.0],
        num_plants=4,
        area_per_plant_m2=0.10,
    )
    assert res2.mode_used == "mode_2"
    assert res2.total_leaf_area_cm2 == pytest.approx(6000.0)
    assert res2.ground_area_m2 == pytest.approx(0.40)
    assert res2.lai == pytest.approx(1.5)

    with pytest.raises(ValueError, match="positive"):
        calculate_lai(100.0, ground_area_m2=0.0)
    with pytest.raises(ValueError, match="Mode 2 requires both"):
        calculate_lai(100.0, num_plants=3)


def test_quality_warnings_low_resolution_and_blank_image() -> None:
    """Verify quality module flags low resolution (<50 px/cm) and blank images (0 leaves)."""
    canvas = np.full((1000, 1000, 3), PAPER_WHITE_BGR, dtype=np.uint8)
    cal = detect_calibration(canvas, manual_px_per_cm=30.0)
    seg = segment_leaves(canvas, cal.px_per_cm, cal.calibration_square_mask)
    meas = measure_leaves(seg.leaf_mask, cal.px_per_cm)
    qual = evaluate_quality(1000, 1000, cal, seg, meas)

    assert qual.confidence == "LOW"
    assert any("low image resolution" in w for w in qual.warnings)
    assert any("no leaves detected" in w for w in qual.warnings)


def test_item5_imagej_validation_folder_and_compare_script() -> None:
    """Item 5: Verify validation_template.csv, validation_guide.md, and compare.py exist and work."""
    csv_file = VALIDATION_DIR / "validation_template.csv"
    guide_file = VALIDATION_DIR / "validation_guide.md"
    comp_file = VALIDATION_DIR / "compare.py"

    assert csv_file.is_file()
    assert guide_file.is_file()
    assert comp_file.is_file()

    stats = compare_validation_csv(csv_file)
    assert stats["count"] >= 3
    assert stats["max_abs_diff_pct"] < 1.0


def test_star_and_spiky_leaf_not_flagged_as_touching() -> None:
    """Verify a spiky / 5-pointed star single leaf (low solidity ~0.48) is NOT flagged as touching."""
    mask_star = np.zeros((1000, 1000), dtype=np.uint8)
    pts = []
    for i in range(10):
        ang = i * math.pi / 5.0 - math.pi / 2.0
        r = 220 if i % 2 == 0 else 85
        pts.append([int(round(500 + r * math.cos(ang))), int(round(500 + r * math.sin(ang)))])
    cv2.fillPoly(mask_star, [np.array(pts, dtype=np.int32)], 1)

    meas = measure_leaves(mask_star, px_per_cm=100.0)
    assert meas.leaf_count == 1
    assert meas.leaves[0].solidity < 0.65
    assert meas.leaves[0].is_possible_touching is False
    assert meas.touching_leaves_detected is False
    assert not any("possible touching leaves" in w for w in meas.warnings)


def test_phase9_memory_under_1gb_on_12mp_image() -> None:
    """Phase 9: Verify peak pipeline memory on a 12 MP (4000x3000) image stays well under 1 GB."""
    import tracemalloc
    from tests.make_synthetic import draw_aa_ellipse

    w, h = 4000, 3000
    scale = 100.0
    canvas = np.full((h, w, 3), PAPER_WHITE_BGR, dtype=np.uint8)
    draw_aa_rotated_square(canvas, (250.0, 250.0), 2.0 * scale, 0.0, BLUE_SQUARE_BGR, ss=4)
    draw_aa_ellipse(canvas, (w * 0.45, h * 0.45), 4.0 * scale, 2.5 * scale, 12.0, GREEN_LEAF_BGR, ss=4)
    draw_aa_ellipse(canvas, (w * 0.70, h * 0.65), 5.0 * scale, 3.0 * scale, -18.0, GREEN_LEAF_BGR, ss=4)

    tracemalloc.start()
    try:
        cal = detect_calibration(canvas, known_side_cm=2.0, color="blue")
        seg = segment_leaves(canvas, cal.px_per_cm, cal.calibration_square_mask, known_side_cm=2.0)
        meas = measure_leaves(seg.leaf_mask, cal.px_per_cm)
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    peak_mb = peak_bytes / (1024.0 * 1024.0)
    assert peak_mb < 1024.0, f"12 MP peak memory {peak_mb:.1f} MB exceeded 1024 MB limit"
    assert meas.leaf_count == 2
    assert meas.total_area_cm2 == pytest.approx(78.5427, rel=1e-4)
