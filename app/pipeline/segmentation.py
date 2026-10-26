"""Automatic leaf segmentation (Phase 4, Item 1.2, Item 3, Item 6, Issue B, Phase 9 Memory Optimization):
- Masked normalized-convolution illumination correction (never uses leaf pixels; float32 channel-wise lighting field).
- CIELAB + Excess Green foreground-ness score (detects green, yellow, brown, red, and blue leaves).
- Automatic Otsu threshold + 3 px boundary midpoint refinement (`edge_threshold`).
- Shadow rejection and `cv2.connectedComponentsWithStats` speckle/pinhole cleanup (zero deprecation warnings).
- Geometry-only safeguard excluding any extra calibration-sized squares while preserving non-square colored leaves.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np
from skimage.filters import threshold_otsu

from app import config
from app.pipeline.calibration import is_calibration_sized_square_contour


@dataclass(frozen=True)
class SegmentationResult:
    """Result of automatic leaf segmentation."""

    leaf_mask: np.ndarray            # Binary uint8 mask (1 = leaf, 0 = background)
    otsu_threshold: float            # Traceable initial Otsu threshold on [0, 255] foreground score scale
    edge_threshold: float            # Refined boundary threshold (midpoint of interior & exterior means)
    border_objects_removed: int      # Count of objects removed because they touched the image border
    contrast_score: float            # Mean foreground-background separation score for quality check
    extra_squares_removed: int = 0   # Count of extra calibration-sized squares excluded in segmentation
    warnings: list[str] = field(default_factory=list)


def _remove_small_objects_cc(mask: np.ndarray, min_size_px: int) -> np.ndarray:
    """Remove connected foreground components smaller than `min_size_px` using OpenCV connectedComponentsWithStats."""
    mask_bool = np.asarray(mask, dtype=bool)
    if min_size_px <= 1 or not np.any(mask_bool):
        return mask_bool.copy()
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask_bool.astype(np.uint8), connectivity=config.CC_CONNECTIVITY
    )
    areas = stats[:, cv2.CC_STAT_AREA]
    keep_labels = areas >= min_size_px
    keep_labels[0] = False  # Background label 0 is always False
    res = keep_labels[labels]
    del labels, stats
    return res


def _remove_small_holes_cc(mask: np.ndarray, max_hole_px: int) -> np.ndarray:
    """Fill internal background holes smaller than or equal to `max_hole_px` using OpenCV connectedComponentsWithStats."""
    mask_bool = np.asarray(mask, dtype=bool)
    if max_hole_px <= 0 or not np.any(mask_bool):
        return mask_bool.copy()
    inv_u8 = (~mask_bool).astype(np.uint8)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        inv_u8, connectivity=config.CC_CONNECTIVITY
    )
    del inv_u8
    h, w = mask_bool.shape[:2]
    border_labels = set(np.unique(labels[0, :]).tolist())
    border_labels.update(np.unique(labels[h - 1, :]).tolist())
    border_labels.update(np.unique(labels[:, 0]).tolist())
    border_labels.update(np.unique(labels[:, w - 1]).tolist())

    areas = stats[:, cv2.CC_STAT_AREA]
    fill_lut = np.zeros(num_labels, dtype=bool)
    for lbl in range(1, num_labels):
        if lbl not in border_labels and areas[lbl] <= max_hole_px:
            fill_lut[lbl] = True
    res = mask_bool | fill_lut[labels]
    del labels, stats
    return res


def _normalize_illumination_legacy(image_bgr: np.ndarray, calib_mask: np.ndarray) -> np.ndarray:
    """Legacy morphological-closing illumination estimate (kept only for regression comparison tests)."""
    h, w = image_bgr.shape[:2]
    k_size = max(
        config.SEG_ILLUMINATION_MIN_KERNEL_PX,
        int(min(h, w) * config.SEG_ILLUMINATION_KERNEL_FRACTION) | 1,
    )
    if k_size % 2 == 0:
        k_size += 1
    scale = config.SEG_ILLUM_DOWNSAMPLE_SCALE
    small_w = max(32, int(w * scale))
    small_h = max(32, int(h * scale))
    small_bgr = cv2.resize(image_bgr, (small_w, small_h), interpolation=cv2.INTER_AREA)
    small_k = max(15, int(k_size * scale) | 1)
    if small_k % 2 == 0:
        small_k += 1
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (small_k, small_k))
    closed_small = cv2.morphologyEx(small_bgr, cv2.MORPH_CLOSE, se)
    bg_small = cv2.GaussianBlur(closed_small.astype(np.float32), (small_k, small_k), 0)
    bg_field = cv2.resize(bg_small, (w, h), interpolation=cv2.INTER_LINEAR)
    np.maximum(bg_field, 60.0, out=bg_field)
    target_white = np.float32(max(float(np.percentile(bg_small, config.SEG_BG_PERCENTILE)), 220.0))
    np.divide(target_white, bg_field, out=bg_field)
    np.multiply(bg_field, image_bgr, out=bg_field, casting="unsafe")
    np.clip(bg_field, 0.0, 255.0, out=bg_field)
    return bg_field.astype(np.uint8)


def _normalize_illumination(
    image_bgr: np.ndarray,
    calib_mask: np.ndarray,
    px_per_cm: float | None = None,
) -> np.ndarray:
    """Estimate smooth background illumination field using masked normalized convolution (Item 1.2 & Phase 9)."""
    h, w = image_bgr.shape[:2]
    scale = config.SEG_ILLUM_DOWNSAMPLE_SCALE
    small_w = max(32, int(round(w * scale)))
    small_h = max(32, int(round(h * scale)))
    small_bgr = cv2.resize(image_bgr, (small_w, small_h), interpolation=cv2.INTER_AREA).astype(np.float64)
    small_short = min(small_h, small_w)

    if calib_mask is not None and np.any(calib_mask):
        small_calib = (
            cv2.resize(calib_mask.astype(np.uint8), (small_w, small_h), interpolation=cv2.INTER_NEAREST) > 0
        )
        se_cal = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        small_calib = cv2.dilate(small_calib.astype(np.uint8), se_cal) > 0
    else:
        small_calib = np.zeros((small_h, small_w), dtype=bool)

    non_calib = ~small_calib
    gray_small = np.mean(small_bgr, axis=2)
    p50 = (
        float(np.percentile(gray_small[non_calib], config.SEG_ILLUM_BRIGHT_PERCENTILE))
        if np.any(non_calib)
        else 200.0
    )
    bright_half = non_calib & (gray_small >= p50)
    if np.any(bright_half):
        med_color = np.median(small_bgr[bright_half], axis=0)
    else:
        med_color = np.array([246.0, 248.0, 248.0], dtype=np.float64)

    dist = np.linalg.norm(small_bgr - med_color[None, None, :], axis=2)
    otsu_s = float(threshold_otsu(dist[non_calib])) if np.any(non_calib) else 20.0
    otsu_s = max(otsu_s, 14.0)
    rough_fg = (dist > otsu_s) | small_calib

    if px_per_cm is not None and px_per_cm > 0:
        dilate_r = max(2, int(round(config.SEG_ILLUM_DILATE_CM * px_per_cm * scale)))
    else:
        dilate_r = max(2, int(round(config.SEG_ILLUM_FALLBACK_DILATE_FRAC * float(small_short))))
    k_dil = 2 * dilate_r + 1
    se_dil = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_dil, k_dil))
    dilated_fg = cv2.dilate(rough_fg.astype(np.uint8), se_dil) > 0

    w_mask = (~dilated_fg).astype(np.float64)
    if np.count_nonzero(w_mask) < 16:
        w_mask = (~small_calib).astype(np.float64)

    sigma = max(3.0, config.SEG_ILLUM_SIGMA_FRAC * float(small_short))
    w_blur = cv2.GaussianBlur(w_mask, (0, 0), sigmaX=sigma, sigmaY=sigma, borderType=cv2.BORDER_REPLICATE)
    valid_w_base = w_blur >= config.SEG_ILLUM_MIN_WEIGHT

    bg_small = np.zeros_like(small_bgr, dtype=np.float64)
    for c in range(3):
        chan = small_bgr[:, :, c]
        num = cv2.GaussianBlur(
            chan * w_mask, (0, 0), sigmaX=sigma, sigmaY=sigma, borderType=cv2.BORDER_REPLICATE
        )
        field_c = np.zeros((small_h, small_w), dtype=np.float64)
        valid_w = valid_w_base.copy()
        field_c[valid_w] = num[valid_w] / w_blur[valid_w]
        if not np.all(valid_w):
            for mult in (2.5, 5.0, 10.0):
                still_missing = ~valid_w
                if not np.any(still_missing):
                    break
                wb2 = cv2.GaussianBlur(
                    w_mask, (0, 0), sigmaX=sigma * mult, sigmaY=sigma * mult, borderType=cv2.BORDER_REPLICATE
                )
                nm2 = cv2.GaussianBlur(
                    chan * w_mask, (0, 0), sigmaX=sigma * mult, sigmaY=sigma * mult, borderType=cv2.BORDER_REPLICATE
                )
                ok2 = still_missing & (wb2 >= 1e-5)
                field_c[ok2] = nm2[ok2] / wb2[ok2]
                valid_w = valid_w | ok2
            if not np.all(valid_w):
                field_c[~valid_w] = float(med_color[c])
        bg_small[:, :, c] = field_c

    target_white = np.maximum(np.median(bg_small, axis=(0, 1)), 180.0)

    # Upsample and normalize one channel at a time in-place (single 1-channel buffer instead of 4x 3-channel arrays)
    out_bgr = np.empty_like(image_bgr, dtype=np.uint8)
    for c in range(3):
        bg_c = cv2.resize(bg_small[:, :, c], (w, h), interpolation=cv2.INTER_LINEAR)
        np.maximum(bg_c, 40.0, out=bg_c)
        np.divide(float(target_white[c]), bg_c, out=bg_c)
        np.multiply(bg_c, image_bgr[:, :, c], out=bg_c, casting="unsafe")
        np.clip(bg_c, 0.0, 255.0, out=bg_c)
        out_bgr[:, :, c] = bg_c.astype(np.uint8)
        del bg_c

    return out_bgr


def segment_leaves(
    image_bgr: np.ndarray,
    px_per_cm: float,
    calibration_square_mask: np.ndarray | None = None,
    known_side_cm: float = config.DEFAULT_CALIBRATION_SIDE_CM,
) -> SegmentationResult:
    """Segment leaves from white background with zero manual thresholds and <1 GB peak RAM on 12 MP images."""
    if px_per_cm <= 0:
        raise ValueError(f"px_per_cm must be positive for segmentation, got {px_per_cm}.")

    h, w = image_bgr.shape[:2]
    calib_bool = (
        (calibration_square_mask > 0)
        if calibration_square_mask is not None
        else np.zeros((h, w), dtype=bool)
    )
    warnings: list[str] = []

    # Step 1: Light Gaussian blur (3x3) on full-resolution image
    blurred_bgr = cv2.GaussianBlur(image_bgr, config.SEG_GAUSSIAN_BLUR_KERNEL, 0)

    # Step 2: Masked normalized-convolution illumination normalization
    try:
        norm_bgr = _normalize_illumination(blurred_bgr, calib_bool, px_per_cm)
    except TypeError:
        norm_bgr = _normalize_illumination(blurred_bgr, calib_bool)  # type: ignore[call-arg]
    del blurred_bgr

    # Step 3: Convert to CIELAB (uint8) and compute foreground-ness image with immediate array cleanup
    lab_u8 = cv2.cvtColor(norm_bgr, cv2.COLOR_BGR2LAB)
    L_u8 = lab_u8[..., 0]
    a_u8 = lab_u8[..., 1]
    b_u8 = lab_u8[..., 2]

    non_calib = ~calib_bool
    l_thresh = float(np.percentile(L_u8[non_calib], config.SEG_BG_PERCENTILE))
    bg_sample_mask = non_calib & (L_u8 >= l_thresh)
    if np.any(bg_sample_mask):
        bg_L = float(np.median(L_u8[bg_sample_mask]))
        bg_a = float(np.median(a_u8[bg_sample_mask]))
        bg_b = float(np.median(b_u8[bg_sample_mask]))
    else:
        bg_L, bg_a, bg_b = 248.0, 128.0, 128.0
    del bg_sample_mask

    # Compute chroma_dist, lab_dist, exg, and foreground_score in-place to avoid temporary 96 MB buffers
    chroma_dist = a_u8.astype(np.float64)
    chroma_dist -= bg_a
    b_diff = b_u8.astype(np.float64)
    b_diff -= bg_b
    np.hypot(chroma_dist, b_diff, out=chroma_dist)
    del b_diff

    L_chan = L_u8.astype(np.float64)
    del lab_u8, L_u8, a_u8, b_u8

    lab_dist = np.maximum(0.0, bg_L - L_chan)
    np.square(lab_dist, out=lab_dist)
    np.multiply(lab_dist, 0.35, out=lab_dist)
    c_sq = np.square(chroma_dist)
    np.multiply(c_sq, 2.2, out=c_sq)
    lab_dist += c_sq
    del c_sq
    np.sqrt(lab_dist, out=lab_dist)

    exg = norm_bgr[..., 1].astype(np.float64)
    np.multiply(exg, 2.0, out=exg)
    exg -= norm_bgr[..., 2].astype(np.float64)
    exg -= norm_bgr[..., 0].astype(np.float64)
    del norm_bgr
    np.divide(exg, 255.0, out=exg)
    np.maximum(exg, 0.0, out=exg)

    foreground_score_clipped = lab_dist
    np.multiply(foreground_score_clipped, config.SEG_WEIGHT_LAB_DIST, out=foreground_score_clipped)
    exg_term = exg * (config.SEG_WEIGHT_EXG * 127.5)
    foreground_score_clipped += exg_term
    del exg_term
    np.clip(foreground_score_clipped, 0.0, 255.0, out=foreground_score_clipped)

    # Step 4: Compute shadow mask (12 MB bool) and free chroma_dist, exg, L_chan (288 MB) before Otsu
    is_shadow = (
        (
            (chroma_dist < config.SHADOW_MAX_CHROMA_AB)
            & (exg < config.SHADOW_MAX_EXG_NORM)
            & (L_chan > config.SHADOW_MIN_LIGHTNESS_L)
        )
        | ((chroma_dist < 4.5) & (exg < 0.02))
    )
    del chroma_dist, exg, L_chan

    # Step 5: Automatic threshold with Otsu's method
    otsu_val = float(threshold_otsu(foreground_score_clipped[non_calib]))
    otsu_mask_no_shadow = (foreground_score_clipped > otsu_val) & non_calib & (~is_shadow)

    # Item 3: Refine anti-aliased edges within 3 px of the Otsu boundary using midpoint of interior & exterior means
    rad_px = config.EDGE_REFINE_RADIUS_PX
    k_edge = 2 * rad_px + 1
    se_edge = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_edge, k_edge))
    mask_u8 = otsu_mask_no_shadow.astype(np.uint8)
    eroded = (cv2.erode(mask_u8, se_edge) > 0) & non_calib
    dilated = (cv2.dilate(mask_u8, se_edge) > 0) & non_calib
    del mask_u8
    outside = (~dilated) & non_calib & (~is_shadow)

    if np.any(eroded) and np.any(outside):
        mean_in = float(np.mean(foreground_score_clipped[eroded]))
        mean_out = float(np.mean(foreground_score_clipped[outside]))
        edge_threshold = float(0.5 * (mean_in + mean_out))
        boundary_band = (dilated ^ eroded) & non_calib & (~is_shadow)
        mask_refined = otsu_mask_no_shadow
        mask_refined[boundary_band] = foreground_score_clipped[boundary_band] > edge_threshold
        del boundary_band
    else:
        edge_threshold = otsu_val
        mask_refined = otsu_mask_no_shadow
    del eroded, dilated, outside, is_shadow, non_calib

    # Step 6: Conservative morphological cleanup using connectedComponentsWithStats (Item 6)
    px_per_cm2 = float(px_per_cm ** 2)
    min_speck_px = max(4, int(round(config.MIN_SPECK_AREA_CM2 * px_per_cm2)))
    max_hole_px = max(2, int(round(config.MAX_NOISE_HOLE_AREA_CM2 * px_per_cm2)))

    cleaned_bool = _remove_small_objects_cc(mask_refined, min_size_px=min_speck_px)
    del mask_refined
    cleaned_bool = _remove_small_holes_cc(cleaned_bool, max_hole_px=max_hole_px)

    # Step 7: Ensure calibration square is excluded
    cleaned_bool[calib_bool] = False

    # Step 7b (Issue B safeguard in segmentation.py): Check remaining connected components for any
    # extra calibration-sized squares that were not already in calibration_square_mask
    target_calib_area_px = float((known_side_cm * px_per_cm) ** 2)
    num_cc, cc_labels, cc_stats, _ = cv2.connectedComponentsWithStats(
        cleaned_bool.astype(np.uint8), connectivity=config.CC_CONNECTIVITY
    )
    extra_seg_mask = np.zeros((h, w), dtype=np.uint8)
    extra_seg_count = 0
    for lbl in range(1, num_cc):
        comp_area = int(cc_stats[lbl, cv2.CC_STAT_AREA])
        x = int(cc_stats[lbl, cv2.CC_STAT_LEFT])
        y = int(cc_stats[lbl, cv2.CC_STAT_TOP])
        cw = int(cc_stats[lbl, cv2.CC_STAT_WIDTH])
        ch = int(cc_stats[lbl, cv2.CC_STAT_HEIGHT])
        roi = (cc_labels[y : y + ch, x : x + cw] == lbl).astype(np.uint8)
        contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue
        cnt = max(contours, key=cv2.contourArea)
        if is_calibration_sized_square_contour(cnt, comp_area, target_calib_area_px):
            cnt_shifted = cnt + np.array([[[x, y]]], dtype=cnt.dtype)
            cv2.drawContours(extra_seg_mask, [cnt_shifted], -1, 1, thickness=-1)
            extra_seg_count += 1
    del cc_labels, cc_stats

    if extra_seg_count > 0:
        if config.CALIB_MASK_DILATION_PX > 0:
            d_size = 2 * config.CALIB_MASK_DILATION_PX + 1
            d_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (d_size, d_size))
            extra_seg_dilated = cv2.dilate(extra_seg_mask, d_kernel) > 0
        else:
            extra_seg_dilated = extra_seg_mask > 0
        cleaned_bool[extra_seg_dilated] = False
        calib_bool = calib_bool | extra_seg_dilated
        if calibration_square_mask is not None and calibration_square_mask.shape == (h, w):
            try:
                calibration_square_mask[extra_seg_dilated] = 1
            except ValueError:
                pass
        del extra_seg_dilated
        warnings.append(
            f"{extra_seg_count} extra calibration-sized square(s) detected and excluded from leaf area."
        )
    del extra_seg_mask

    # Step 8: Remove objects touching the image border and flag warning
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        cleaned_bool.astype(np.uint8), connectivity=config.CC_CONNECTIVITY
    )
    margin = config.BORDER_MARGIN_PX
    border_labels: set[int] = set()
    border_labels.update(int(x) for x in np.unique(labels[:margin, :]))
    border_labels.update(int(x) for x in np.unique(labels[h - margin :, :]))
    border_labels.update(int(x) for x in np.unique(labels[:, :margin]))
    border_labels.update(int(x) for x in np.unique(labels[:, w - margin :]))
    border_labels.discard(0)

    border_objects_removed = len(border_labels)
    if border_objects_removed > 0:
        for lbl in border_labels:
            cleaned_bool[labels == lbl] = False
        warnings.append(
            f"leaf cut off by image edge ({border_objects_removed} object(s) touching image border excluded)."
        )
    del labels, stats

    final_mask = cleaned_bool.astype(np.uint8)

    if np.any(cleaned_bool) and np.any(~cleaned_bool & (~calib_bool)):
        fg_mean = float(np.mean(foreground_score_clipped[cleaned_bool]))
        bg_mean = float(np.mean(foreground_score_clipped[~cleaned_bool & (~calib_bool)]))
        contrast_score = float(fg_mean - bg_mean)
    else:
        contrast_score = 0.0
    del foreground_score_clipped, cleaned_bool, calib_bool

    return SegmentationResult(
        leaf_mask=final_mask,
        otsu_threshold=otsu_val,
        edge_threshold=edge_threshold,
        border_objects_removed=border_objects_removed,
        contrast_score=contrast_score,
        extra_squares_removed=extra_seg_count,
        warnings=warnings,
    )
