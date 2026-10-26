"""Automatic scale detection, perspective tilt correction, and extra-square safeguard (Phase 3, Item 2, Item 4, Issue B, Issue E).

Implements:
- Method A (primary): Detect solid blue/red calibration square in HSV space.
  - Item 2 & Issue E: Computes scale from the filled contour pixel count (`side_px = sqrt(pixel_count)`,
    `px_per_cm = side_px / known_side_cm`), which is rotation-invariant, and also reports `edge_px_per_cm`.
    Compares area-based scale with edge-length scale; if they differ by > 1%, flags
    `"calibration square measurements disagree"` and lowers confidence to `MEDIUM`.
  - Issue B: After the main calibration square is found, searches the image for any OTHER object that looks
    like a calibration square using geometry only: aspect ratio 0.9 to 1.1, solidity >= 0.95, and pixel area
    within ±15% of `(known_side_cm * px_per_cm)^2`. Adds every such object (dilated by `CALIB_MASK_DILATION_PX`)
    to `calibration_square_mask` and emits `"N extra calibration-sized square(s) detected and excluded from leaf area."`
  - Item 4: When the 4 side lengths differ by > 2% and <= 15%, computes a perspective transform
    (`cv2.getPerspectiveTransform`) mapping the 4 ordered sub-pixel corners to a square of side
    `known_side_cm * reference_px_per_cm`, warps the entire image onto an enlarged canvas so no
    part of the image is cut off, re-detects the square on the warped image, sets confidence to `MEDIUM`,
    and adds the perspective warning. If side lengths differ by > 15% (extreme tilt), does NOT warp,
    returns `LOW` confidence, and warns that the photo must be retaken.
- Method B (fallback): Image DPI metadata (`px_per_cm = dpi / 2.54`, `MEDIUM` confidence).
- Method C (last resort): User manual scale (`needs_manual_scale = True`).
"""

from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
from skimage.filters import threshold_otsu

from app import config


@dataclass(frozen=True)
class CalibrationResult:
    """Result of automatic scale calibration and optional perspective rectification."""

    px_per_cm: Optional[float]
    method_used: str  # "calibration_square", "dpi_metadata", "manual", or "none"
    confidence: str   # "HIGH", "MEDIUM", or "LOW"
    calibration_square_mask: np.ndarray
    needs_manual_scale: bool = False
    warnings: list[str] = field(default_factory=list)
    detected_corners: Optional[np.ndarray] = None
    side_lengths_px: Optional[list[float]] = None
    max_side_diff_ratio: Optional[float] = None
    area_px_per_cm: Optional[float] = None
    edge_px_per_cm: Optional[float] = None
    known_side_cm: float = config.DEFAULT_CALIBRATION_SIDE_CM
    extra_squares_excluded: int = 0
    perspective_corrected: bool = False
    rectified_image_bgr: Optional[np.ndarray] = None


def _get_color_mask(image_hsv: np.ndarray, color: str) -> np.ndarray:
    """Create binary HSV mask for the specified calibration square color ('blue' or 'red')."""
    c = color.lower().strip()
    if c == "blue":
        lower = np.array(config.BLUE_HSV_LOWER, dtype=np.uint8)
        upper = np.array(config.BLUE_HSV_UPPER, dtype=np.uint8)
        return cv2.inRange(image_hsv, lower, upper)
    if c == "red":
        l1 = np.array(config.RED_HSV_LOWER_1, dtype=np.uint8)
        u1 = np.array(config.RED_HSV_UPPER_1, dtype=np.uint8)
        l2 = np.array(config.RED_HSV_LOWER_2, dtype=np.uint8)
        u2 = np.array(config.RED_HSV_UPPER_2, dtype=np.uint8)
        return cv2.bitwise_or(cv2.inRange(image_hsv, l1, u1), cv2.inRange(image_hsv, l2, u2))
    raise ValueError(
        f"Unsupported calibration square color '{color}'. Supported: {sorted(config.SUPPORTED_CALIBRATION_COLORS)}"
    )


def _order_quad_corners(pts: np.ndarray) -> np.ndarray:
    """Order 4 corners consistently: top-left, top-right, bottom-right, bottom-left."""
    pts = pts.reshape(4, 2).astype(np.float64)
    center = np.mean(pts, axis=0)
    angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    order = np.argsort(angles)
    sorted_pts = pts[order]
    tl_idx = int(np.argmin(sorted_pts[:, 0] + sorted_pts[:, 1]))
    return np.roll(sorted_pts, -tl_idx, axis=0)


def _refine_quad_sides_from_contour(
    contour: np.ndarray,
    init_corners: np.ndarray,
    mask_shape: tuple[int, int],
    image_bgr: Optional[np.ndarray] = None,
) -> tuple[np.ndarray, list[float], float]:
    """Compute sub-pixel corners, 4 edge lengths (for tilt check), and pixel-area side length (Item 2)."""
    ordered = _order_quad_corners(init_corners)
    poly_edges_init = [
        float(np.linalg.norm(ordered[(i + 1) % 4] - ordered[i]))
        for i in range(4)
    ]
    mean_poly_init = float(np.mean(poly_edges_init)) if poly_edges_init else 1.0
    poly_diff_init = (max(poly_edges_init) - min(poly_edges_init)) / max(mean_poly_init, 1.0)
    if mean_poly_init < 70.0 and poly_diff_init < 0.08:
        seed_corners = _order_quad_corners(cv2.boxPoints(cv2.minAreaRect(contour)))
    else:
        seed_corners = ordered
    pts = contour.reshape(-1, 2).astype(np.float64)

    lines: list[tuple[float, float, float, float]] = []
    for i in range(4):
        p1 = seed_corners[i]
        p2 = seed_corners[(i + 1) % 4]
        v = p2 - p1
        edge_len = float(np.linalg.norm(v))
        if edge_len < 1e-6:
            lines.append((float(p1[0]), float(p1[1]), 1.0, 0.0))
            continue
        u = v / edge_len
        n = np.array([-u[1], u[0]])
        rel = pts - p1
        proj = rel @ u
        perp = np.abs(rel @ n)
        mask_edge = (proj >= 0.15 * edge_len) & (proj <= 0.85 * edge_len) & (perp <= 2.5)
        edge_pts = pts[mask_edge]
        if len(edge_pts) >= 5:
            vx, vy, x0, y0 = cv2.fitLine(edge_pts.astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01).ravel()
            if float(vx * u[0] + vy * u[1]) < 0:
                vx, vy = -vx, -vy
            lines.append((float(x0), float(y0), float(vx), float(vy)))
        else:
            lines.append((float(p1[0]), float(p1[1]), float(u[0]), float(u[1])))

    refined_corners = np.zeros((4, 2), dtype=np.float64)
    for i in range(4):
        x1, y1, vx1, vy1 = lines[(i - 1) % 4]
        x2, y2, vx2, vy2 = lines[i]
        det = vx1 * vy2 - vy1 * vx2
        if abs(det) < 1e-7:
            refined_corners[i] = ordered[i]
        else:
            t = ((x2 - x1) * vy2 - (y2 - y1) * vx2) / det
            inter = np.array([x1 + t * vx1, y1 + t * vy1], dtype=np.float64)
            if np.linalg.norm(inter - seed_corners[i]) <= 6.0:
                refined_corners[i] = inter
            else:
                refined_corners[i] = ordered[i]

    fitted_edges = [
        float(np.linalg.norm(refined_corners[(i + 1) % 4] - refined_corners[i]) + 1.0)
        for i in range(4)
    ]
    poly_edges = [
        float(np.linalg.norm(ordered[(i + 1) % 4] - ordered[i]) + 1.0)
        for i in range(4)
    ]
    raw_edges = fitted_edges
    if float(np.mean(fitted_edges)) > 100.0 and abs(float(np.mean(poly_edges)) - float(np.mean(fitted_edges))) / float(np.mean(fitted_edges)) > 0.012:
        raw_edges = poly_edges

    h, w = mask_shape
    raw_fill_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.drawContours(raw_fill_mask, [contour], -1, 1, thickness=-1)
    pixel_count = int(np.count_nonzero(raw_fill_mask))
    area_side_px = float(np.sqrt(np.float64(pixel_count)))

    if image_bgr is not None and mean_poly_init >= 80.0:
        x_b, y_b, cw_b, ch_b = cv2.boundingRect(contour)
        pad_b = 8
        x0_b, y0_b = max(0, x_b - pad_b), max(0, y_b - pad_b)
        x1_b, y1_b = min(w, x_b + cw_b + pad_b), min(h, y_b + ch_b + pad_b)
        roi_bgr = image_bgr[y0_b:y1_b, x0_b:x1_b].astype(np.float64)
        roi_mask = raw_fill_mask[y0_b:y1_b, x0_b:x1_b]
        k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        k7 = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
        core = cv2.erode(roi_mask, k3) > 0
        band_dil = cv2.dilate(roi_mask, k3) > 0
        outer_bg = (cv2.dilate(roi_mask, k7) > 0) & (~band_dil)
        if np.count_nonzero(core) >= 16 and np.count_nonzero(outer_bg) >= 16:
            c_sq = np.median(roi_bgr[core], axis=0)
            c_bg = np.median(roi_bgr[outer_bg], axis=0)
            diff_c = c_sq - c_bg
            denom_c = float(np.dot(diff_c, diff_c))
            if denom_c >= 100.0:
                boundary_b = band_dil & (~core)
                pts_b = roi_bgr[boundary_b] - c_bg
                alpha_b = np.clip((pts_b @ diff_c) / denom_c, 0.0, 1.0)
                mid_mask = (alpha_b > 0.05) & (alpha_b < 0.95)
                if np.count_nonzero(mid_mask) >= 4:
                    total_alpha = float(np.count_nonzero(core)) + float(np.sum(alpha_b, dtype=np.float64))
                    subpx_side = float(np.sqrt(np.float64(total_alpha)))
                    if abs(subpx_side - area_side_px) / max(area_side_px, 1.0) <= 0.015:
                        area_side_px = subpx_side

    return refined_corners, raw_edges, area_side_px


def is_calibration_sized_square_contour(
    contour: np.ndarray,
    pixel_area: int,
    target_area_px: float,
) -> bool:
    """Check whether a contour matches calibration-square geometry (Issue B).

    Uses geometry only (regardless of color):
    - Pixel area within ±15% of `target_area_px = (known_side_cm * px_per_cm)^2`.
    - Solidity >= 0.95 (`contour_area / convex_hull_area >= 0.95`).
    - Aspect ratio between 0.9 and 1.1 (`minAreaRect` width / height).
    - Rectangular extent >= 0.88 (so circular/elliptical leaves are never mistaken for squares).
    """
    if target_area_px <= 0 or pixel_area <= 0:
        return False
    min_area = (1.0 - config.EXTRA_CALIB_AREA_TOLERANCE) * target_area_px
    max_area = (1.0 + config.EXTRA_CALIB_AREA_TOLERANCE) * target_area_px
    if not (min_area <= float(pixel_area) <= max_area):
        return False

    hull = cv2.convexHull(contour)
    hull_area = float(cv2.contourArea(hull))
    cnt_area = float(cv2.contourArea(contour))
    if hull_area <= 0:
        return False
    solidity = cnt_area / hull_area
    if solidity < config.EXTRA_CALIB_MIN_SOLIDITY:
        return False

    _, (rw, rh), _ = cv2.minAreaRect(contour)
    if rw <= 0 or rh <= 0:
        return False
    aspect_ratio = float(rw / rh)
    if not (config.EXTRA_CALIB_MIN_ASPECT_RATIO <= aspect_ratio <= config.EXTRA_CALIB_MAX_ASPECT_RATIO):
        return False

    rect_area = float((rw + 1.0) * (rh + 1.0))
    extent = float(pixel_area) / max(rect_area, 1.0)
    if extent < config.EXTRA_CALIB_MIN_EXTENT:
        return False

    return True


def _find_extra_calibration_squares(
    image_bgr: np.ndarray,
    main_calib_mask: np.ndarray,
    known_side_cm: float,
    px_per_cm: float,
) -> tuple[np.ndarray, int]:
    """Search the image for any OTHER object that looks like a calibration square (Issue B).

    Tests every non-background object (whatever its color) against `is_calibration_sized_square_contour`.
    Adds every matching object (dilated by `CALIB_MASK_DILATION_PX`) to `updated_calib_mask`.
    """
    h, w = image_bgr.shape[:2]
    target_area_px = float((known_side_cm * px_per_cm) ** 2)
    main_bool = main_calib_mask > 0
    non_main = ~main_bool
    if not np.any(non_main):
        return main_calib_mask.copy(), 0

    blurred = cv2.GaussianBlur(image_bgr, config.SEG_GAUSSIAN_BLUR_KERNEL, 0)
    lab_u8 = cv2.cvtColor(blurred, cv2.COLOR_BGR2LAB)
    L_u8 = lab_u8[..., 0]
    a_u8 = lab_u8[..., 1]
    b_u8 = lab_u8[..., 2]

    l_thresh = float(np.percentile(L_u8[non_main], config.SEG_BG_PERCENTILE))
    bg_sample = non_main & (L_u8 >= l_thresh)
    if np.any(bg_sample):
        bg_L = float(np.median(L_u8[bg_sample]))
        bg_a = float(np.median(a_u8[bg_sample]))
        bg_b = float(np.median(b_u8[bg_sample]))
    else:
        bg_L, bg_a, bg_b = 248.0, 128.0, 128.0
    del bg_sample

    chroma_dist = np.hypot(a_u8.astype(np.float32) - np.float32(bg_a), b_u8.astype(np.float32) - np.float32(bg_b))
    L_chan = L_u8.astype(np.float32)
    del lab_u8, L_u8, a_u8, b_u8

    dL = np.maximum(np.float32(0.0), np.float32(bg_L) - L_chan)
    lab_dist = np.sqrt(np.float32(0.35) * (dL * dL) + np.float32(2.2) * (chroma_dist * chroma_dist))
    del dL

    exg = (
        np.float32(2.0) * blurred[..., 1].astype(np.float32)
        - blurred[..., 2].astype(np.float32)
        - blurred[..., 0].astype(np.float32)
    ) * np.float32(1.0 / 255.0)
    np.maximum(exg, np.float32(0.0), out=exg)
    fg_score = np.clip(
        np.float32(config.SEG_WEIGHT_LAB_DIST) * lab_dist + np.float32(config.SEG_WEIGHT_EXG * 127.5) * exg,
        np.float32(0.0),
        np.float32(255.0),
    )
    del lab_dist

    is_shadow = (
        (chroma_dist < config.SHADOW_MAX_CHROMA_AB)
        & (exg < config.SHADOW_MAX_EXG_NORM)
        & (L_chan > config.SHADOW_MIN_LIGHTNESS_L)
    )
    del chroma_dist, exg, L_chan
    otsu_val = float(threshold_otsu(fg_score[non_main]))
    candidate_mask = (fg_score > otsu_val) & (~is_shadow) & non_main
    del fg_score, is_shadow

    # Also union HSV blue and red masks outside main_bool so colored squares are never missed
    # even if a very dark/saturated object shifts the global Otsu threshold
    hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
    del blurred
    blue_m = (_get_color_mask(hsv, "blue") > 0) & non_main
    red_m = (_get_color_mask(hsv, "red") > 0) & non_main
    del hsv
    combined_mask = (candidate_mask | blue_m | red_m).astype(np.uint8)
    del candidate_mask, blue_m, red_m

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        combined_mask, connectivity=config.CC_CONNECTIVITY
    )

    extra_raw_mask = np.zeros((h, w), dtype=np.uint8)
    extra_count = 0

    min_area = (1.0 - config.EXTRA_CALIB_AREA_TOLERANCE) * target_area_px
    max_area = (1.0 + config.EXTRA_CALIB_AREA_TOLERANCE) * target_area_px

    for lbl in range(1, num_labels):
        comp_area_px = int(stats[lbl, cv2.CC_STAT_AREA])
        # Quick bounding filter before contour extraction (allow small hole filling up to +5%)
        if comp_area_px < 0.75 * min_area or comp_area_px > 1.25 * max_area:
            continue
        x = int(stats[lbl, cv2.CC_STAT_LEFT])
        y = int(stats[lbl, cv2.CC_STAT_TOP])
        cw = int(stats[lbl, cv2.CC_STAT_WIDTH])
        ch = int(stats[lbl, cv2.CC_STAT_HEIGHT])
        roi = (labels[y : y + ch, x : x + cw] == lbl).astype(np.uint8)
        contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue
        cnt = max(contours, key=cv2.contourArea)
        # Count filled contour pixels in ROI
        filled_roi = np.zeros_like(roi)
        cv2.drawContours(filled_roi, [cnt], -1, 1, thickness=-1)
        filled_area_px = int(np.count_nonzero(filled_roi))

        if is_calibration_sized_square_contour(cnt, filled_area_px, target_area_px):
            cnt_shifted = cnt + np.array([[[x, y]]], dtype=cnt.dtype)
            cv2.drawContours(extra_raw_mask, [cnt_shifted], -1, 1, thickness=-1)
            extra_count += 1

    if extra_count == 0:
        return main_calib_mask.copy(), 0

    if config.CALIB_MASK_DILATION_PX > 0:
        d_size = 2 * config.CALIB_MASK_DILATION_PX + 1
        d_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (d_size, d_size))
        extra_dilated = cv2.dilate(extra_raw_mask, d_kernel)
    else:
        extra_dilated = extra_raw_mask

    updated_mask = np.where((main_calib_mask > 0) | (extra_dilated > 0), 1, 0).astype(np.uint8)
    return updated_mask, extra_count


def _find_best_square_candidate(
    image_bgr: np.ndarray,
    color: str,
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Find the most square, solid 4-corner contour matching `color` in HSV space."""
    h, w = image_bgr.shape[:2]
    image_hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    color_mask = _get_color_mask(image_hsv, color)

    contours, _ = cv2.findContours(color_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    max_allowed_area = float(h * w) * config.CALIB_MAX_AREA_FRACTION

    best_candidate: Optional[tuple[float, np.ndarray, np.ndarray]] = None

    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < config.CALIB_MIN_AREA_PX or area > max_allowed_area:
            continue

        hull = cv2.convexHull(cnt)
        hull_area = float(cv2.contourArea(hull))
        if hull_area <= 0:
            continue
        solidity = area / hull_area
        if solidity < config.CALIB_MIN_SOLIDITY:
            continue

        _, (rw, rh), _ = cv2.minAreaRect(cnt)
        if rw <= 0 or rh <= 0:
            continue
        aspect_ratio = float(rw / rh)
        if not (config.CALIB_MIN_ASPECT_RATIO <= aspect_ratio <= config.CALIB_MAX_ASPECT_RATIO):
            continue

        peri = float(cv2.arcLength(hull, True))
        approx = None
        for eps_factor in (config.CALIB_APPROX_POLY_EPSILON_FACTOR, 0.025, 0.045, 0.055):
            cand_approx = cv2.approxPolyDP(hull, eps_factor * peri, True)
            if len(cand_approx) == config.CALIB_EXPECTED_CORNERS:
                approx = cand_approx
                break
        if approx is None:
            continue

        squareness = 1.0 - abs(1.0 - aspect_ratio)
        score = float(squareness * solidity)
        if best_candidate is None or score > best_candidate[0]:
            best_candidate = (score, cnt, approx)

    if best_candidate is None:
        return None
    return best_candidate[1], best_candidate[2]


def _warp_perspective_from_square(
    image_bgr: np.ndarray,
    corners: np.ndarray,
    known_side_cm: float,
    reference_px_per_cm: float,
) -> np.ndarray:
    """Warp the entire image using `cv2.getPerspectiveTransform` & `cv2.warpPerspective` (Item 4)."""
    h, w = image_bgr.shape[:2]
    target_side_px = float(known_side_cm * reference_px_per_cm)
    cx = float(np.mean(corners[:, 0]))
    cy = float(np.mean(corners[:, 1]))
    half = 0.5 * target_side_px

    top_vec = corners[1] - corners[0]
    angle_rad = float(np.arctan2(top_vec[1], top_vec[0]))
    ca, sa = float(np.cos(angle_rad)), float(np.sin(angle_rad))

    local_sq = np.array([[-half, -half], [half, -half], [half, half], [-half, half]], dtype=np.float64)
    dst_sq = np.zeros((4, 2), dtype=np.float32)
    for i in range(4):
        lx, ly = local_sq[i]
        dst_sq[i, 0] = float(cx + lx * ca - ly * sa)
        dst_sq[i, 1] = float(cy + lx * sa + ly * ca)

    H_mat = cv2.getPerspectiveTransform(corners.astype(np.float32), dst_sq)

    frame_pts = np.array([[[0.0, 0.0]], [[float(w), 0.0]], [[float(w), float(h)]], [[0.0, float(h)]]], dtype=np.float32)
    warped_frame_pts = cv2.perspectiveTransform(frame_pts, H_mat).reshape(4, 2)

    min_x = float(np.floor(np.min(warped_frame_pts[:, 0])))
    min_y = float(np.floor(np.min(warped_frame_pts[:, 1])))
    max_x = float(np.ceil(np.max(warped_frame_pts[:, 0])))
    max_y = float(np.ceil(np.max(warped_frame_pts[:, 1])))

    pad = 8.0
    tx = float(-min(0.0, min_x) + pad)
    ty = float(-min(0.0, min_y) + pad)
    T_shift = np.array([[1.0, 0.0, tx], [0.0, 1.0, ty], [0.0, 0.0, 1.0]], dtype=np.float64)
    H_shifted = T_shift @ H_mat

    max_w_cap = int(round(w * config.PERSPECTIVE_MAX_CANVAS_MULTIPLIER))
    max_h_cap = int(round(h * config.PERSPECTIVE_MAX_CANVAS_MULTIPLIER))
    out_w = min(max_w_cap, max(w, int(np.ceil(max_x + tx + pad))))
    out_h = min(max_h_cap, max(h, int(np.ceil(max_y + ty + pad))))

    border_samples = np.concatenate([image_bgr[0, :], image_bgr[h - 1, :], image_bgr[:, 0], image_bgr[:, w - 1]], axis=0)
    bg_color = tuple(int(round(x)) for x in np.median(border_samples, axis=0))

    warped_bgr = cv2.warpPerspective(
        image_bgr,
        H_shifted,
        (out_w, out_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=bg_color,
    )
    return warped_bgr


def detect_calibration(
    image_bgr: np.ndarray,
    known_side_cm: float = config.DEFAULT_CALIBRATION_SIDE_CM,
    color: str = "blue",
    dpi: Optional[float] = None,
    manual_px_per_cm: Optional[float] = None,
    allow_perspective_warp: bool = True,
) -> CalibrationResult:
    """Determine scale (pixels per cm) following Phase 3, Item 2, Item 4, Issue B, and Issue E."""
    if known_side_cm <= 0:
        raise ValueError(f"Calibration square side length must be positive, got {known_side_cm} cm.")

    h, w = image_bgr.shape[:2]
    empty_mask = np.zeros((h, w), dtype=np.uint8)
    warnings: list[str] = []

    # --- METHOD A: Detect calibration square ---
    cand = _find_best_square_candidate(image_bgr, color)
    if cand is not None:
        chosen_cnt, chosen_approx = cand
        ordered_corners, side_lengths, area_side_px = _refine_quad_sides_from_contour(
            chosen_cnt, chosen_approx, (h, w), image_bgr=image_bgr
        )
        mean_edge_px = float(np.mean(side_lengths, dtype=np.float64))
        edge_px_per_cm = float(mean_edge_px / float(known_side_cm))
        area_px_per_cm = float(area_side_px / float(known_side_cm))

        min_side = float(np.min(side_lengths))
        max_side = float(np.max(side_lengths))
        max_diff_ratio = float((max_side - min_side) / mean_edge_px) if mean_edge_px > 0 else 0.0

        # Item 4: Check tilt severity
        if max_diff_ratio > config.CALIB_EXTREME_TILT_RATIO:
            warnings.append(
                f"camera tilt detected: calibration square side lengths differ by {max_diff_ratio * 100:.1f}% "
                f"(exceeds {config.CALIB_EXTREME_TILT_RATIO * 100:.0f}% extreme tilt limit). "
                f"Photo must be retaken from directly above."
            )
            confidence = "LOW"
            px_per_cm = area_px_per_cm
            calib_mask = np.zeros((h, w), dtype=np.uint8)
            cv2.drawContours(calib_mask, [chosen_cnt], -1, 1, thickness=-1)
            if config.CALIB_MASK_DILATION_PX > 0:
                d_size = 2 * config.CALIB_MASK_DILATION_PX + 1
                d_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (d_size, d_size))
                calib_mask = cv2.dilate(calib_mask, d_kernel)
            calib_mask, extra_sq_count = _find_extra_calibration_squares(
                image_bgr, calib_mask, known_side_cm, px_per_cm
            )
            if extra_sq_count > 0:
                warnings.append(
                    f"{extra_sq_count} extra calibration-sized square(s) detected and excluded from leaf area."
                )
            return CalibrationResult(
                px_per_cm=px_per_cm,
                method_used="calibration_square",
                confidence=confidence,
                calibration_square_mask=calib_mask,
                needs_manual_scale=False,
                warnings=warnings,
                detected_corners=ordered_corners,
                side_lengths_px=side_lengths,
                max_side_diff_ratio=max_diff_ratio,
                area_px_per_cm=area_px_per_cm,
                edge_px_per_cm=edge_px_per_cm,
                known_side_cm=float(known_side_cm),
                extra_squares_excluded=extra_sq_count,
                perspective_corrected=False,
                rectified_image_bgr=None,
            )

        if max_diff_ratio > config.CALIB_MAX_SIDE_DIFF_RATIO and allow_perspective_warp:
            warped_bgr = _warp_perspective_from_square(
                image_bgr,
                ordered_corners,
                known_side_cm=known_side_cm,
                reference_px_per_cm=edge_px_per_cm,
            )
            warped_cal = detect_calibration(
                warped_bgr,
                known_side_cm=known_side_cm,
                color=color,
                dpi=dpi,
                manual_px_per_cm=manual_px_per_cm,
                allow_perspective_warp=False,
            )
            warped_warnings = [
                "camera tilt detected: perspective corrected from calibration square only; "
                "accuracy is lower far from the square. Re-shoot from directly above for best accuracy."
            ]
            for w_msg in warped_cal.warnings:
                if "camera tilt detected" not in w_msg and w_msg not in warped_warnings:
                    warped_warnings.append(w_msg)

            final_px_per_cm = warped_cal.px_per_cm if warped_cal.px_per_cm is not None else edge_px_per_cm
            return CalibrationResult(
                px_per_cm=final_px_per_cm,
                method_used="calibration_square",
                confidence="MEDIUM",
                calibration_square_mask=warped_cal.calibration_square_mask,
                needs_manual_scale=False,
                warnings=warped_warnings,
                detected_corners=warped_cal.detected_corners,
                side_lengths_px=side_lengths,
                max_side_diff_ratio=max_diff_ratio,
                area_px_per_cm=warped_cal.area_px_per_cm if warped_cal.area_px_per_cm is not None else final_px_per_cm,
                edge_px_per_cm=edge_px_per_cm,
                known_side_cm=float(known_side_cm),
                extra_squares_excluded=warped_cal.extra_squares_excluded,
                perspective_corrected=True,
                rectified_image_bgr=warped_bgr,
            )

        # Item 2 & Issue E: Primary scale comes from the square's pixel area (`side_px = sqrt(pixel_count)`)
        px_per_cm = area_px_per_cm
        confidence = "HIGH"

        if max_diff_ratio > config.CALIB_MAX_SIDE_DIFF_RATIO:
            warnings.append(
                f"camera tilt detected: calibration square side lengths differ by {max_diff_ratio * 100:.1f}% "
                f"(exceeds {config.CALIB_MAX_SIDE_DIFF_RATIO * 100:.1f}% limit)."
            )
            confidence = "LOW"

        # Compare area-based scale vs edge-length scale (Item 2: warn if disagreement > 1%)
        scale_disagree = abs(area_px_per_cm - edge_px_per_cm) / max(area_px_per_cm, 1e-9)
        if scale_disagree > config.CALIB_SCALE_DISAGREE_RATIO:
            warnings.append(
                f"calibration square measurements disagree: area-based scale ({area_px_per_cm:.2f} px/cm) "
                f"and edge-based scale ({edge_px_per_cm:.2f} px/cm) differ by {scale_disagree * 100:.2f}%."
            )
            if confidence == "HIGH":
                confidence = "MEDIUM"

        # Build exclusion mask for the main calibration square (dilated by CALIB_MASK_DILATION_PX)
        calib_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.drawContours(calib_mask, [chosen_cnt], -1, 1, thickness=-1)
        if config.CALIB_MASK_DILATION_PX > 0:
            d_size = 2 * config.CALIB_MASK_DILATION_PX + 1
            d_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (d_size, d_size))
            calib_mask = cv2.dilate(calib_mask, d_kernel)

        # Issue B: Search image for any OTHER object matching calibration-square geometry
        calib_mask, extra_sq_count = _find_extra_calibration_squares(
            image_bgr, calib_mask, known_side_cm, px_per_cm
        )
        if extra_sq_count > 0:
            warnings.append(
                f"{extra_sq_count} extra calibration-sized square(s) detected and excluded from leaf area."
            )

        return CalibrationResult(
            px_per_cm=px_per_cm,
            method_used="calibration_square",
            confidence=confidence,
            calibration_square_mask=calib_mask,
            needs_manual_scale=False,
            warnings=warnings,
            detected_corners=ordered_corners,
            side_lengths_px=side_lengths,
            max_side_diff_ratio=max_diff_ratio,
            area_px_per_cm=area_px_per_cm,
            edge_px_per_cm=edge_px_per_cm,
            known_side_cm=float(known_side_cm),
            extra_squares_excluded=extra_sq_count,
            perspective_corrected=False,
            rectified_image_bgr=None,
        )

    # Manual scale override if provided
    if manual_px_per_cm is not None:
        if manual_px_per_cm <= 0:
            raise ValueError(f"Manual scale (px_per_cm) must be positive, got {manual_px_per_cm}.")
        warnings.append("scale entered manually by user; no calibration square detected.")
        return CalibrationResult(
            px_per_cm=float(manual_px_per_cm),
            method_used="manual",
            confidence="LOW",
            calibration_square_mask=empty_mask,
            needs_manual_scale=False,
            warnings=warnings,
            area_px_per_cm=float(manual_px_per_cm),
            edge_px_per_cm=None,
            known_side_cm=float(known_side_cm),
        )

    # --- METHOD B: Fallback to image DPI metadata ---
    if dpi is not None and dpi > 0:
        px_per_cm = float(dpi / config.CM_PER_INCH)
        warnings.append("scale came from file metadata, not verified.")
        return CalibrationResult(
            px_per_cm=px_per_cm,
            method_used="dpi_metadata",
            confidence="MEDIUM",
            calibration_square_mask=empty_mask,
            needs_manual_scale=False,
            warnings=warnings,
            area_px_per_cm=px_per_cm,
            edge_px_per_cm=None,
            known_side_cm=float(known_side_cm),
        )

    # --- METHOD C: Last resort -> require user manual input ---
    warnings.append(
        "Calibration failed: no calibration square detected and no DPI metadata found. Manual scale (px/cm) required."
    )
    return CalibrationResult(
        px_per_cm=None,
        method_used="none",
        confidence="LOW",
        calibration_square_mask=empty_mask,
        needs_manual_scale=True,
        warnings=warnings,
        known_side_cm=float(known_side_cm),
    )
