"""Connected components leaf area measurement, per-leaf morphometrics, and touching-leaf detection (Phase 5)."""

from dataclasses import dataclass, field

import cv2
import numpy as np

from app import config


@dataclass(frozen=True)
class LeafObject:
    """Single connected leaf object measurements (float64 accuracy)."""

    leaf_id: int
    area_px: int
    area_cm2: float
    perimeter_px: float
    perimeter_cm: float
    bbox: tuple[int, int, int, int]  # (x, y, width, height) in px
    length_cm: float
    width_cm: float
    centroid_px: tuple[float, float]
    solidity: float
    is_possible_touching: bool = False


@dataclass(frozen=True)
class MeasurementResult:
    """Aggregate and per-leaf measurements for a single image."""

    leaves: list[LeafObject]
    total_area_px: int
    total_area_cm2: float
    total_perimeter_px: float
    leaf_count: int
    mean_area_cm2: float
    std_area_cm2: float
    touching_leaves_detected: bool
    labeled_mask: np.ndarray
    warnings: list[str] = field(default_factory=list)


def _has_narrow_neck_pinch(roi_mask: np.ndarray, solidity: float) -> bool:
    """Check if an object has >=2 distinct interior leaf bodies separated by a narrow neck constriction.

    A single star, spiky, or deeply lobed leaf has low solidity (0.30-0.75) due to V-shaped
    concavities between radiating points/lobes, but its Euclidean distance transform has a single
    central core peak from which all spikes taper monotonically outward.
    In contrast, two touching or overlapping leaves have >=2 distinct distance-transform peaks
    (interior bodies) separated by a saddle/neck constriction where the distance transform drops
    significantly below both peaks.
    """
    if solidity > config.MERGED_LEAF_MAX_SOLIDITY:
        return False
    dist = cv2.distanceTransform(roi_mask, cv2.DIST_L2, 5)
    max_d = float(np.max(dist))
    if max_d < 12.0:
        return False

    h, w = roi_mask.shape[:2]
    for frac in (0.70, 0.60, 0.50, 0.40, 0.35):
        thr = frac * max_d
        if thr < 6.0:
            continue
        _, cores = cv2.threshold(dist, thr, 255, cv2.THRESH_BINARY)
        num_cc, cc_labels, cc_stats, _ = cv2.connectedComponentsWithStats(
            cores.astype(np.uint8), connectivity=8
        )
        if (num_cc - 1) < 2:
            continue

        valid_peaks: list[tuple[float, float, float]] = []
        for cid in range(1, num_cc):
            if int(cc_stats[cid, cv2.CC_STAT_AREA]) < 16:
                continue
            comp_mask = cc_labels == cid
            p_val = float(np.max(dist[comp_mask]))
            if p_val >= max(8.0, 0.30 * max_d):
                ys, xs = np.nonzero(comp_mask & (dist >= p_val - 1e-3))
                valid_peaks.append((p_val, float(np.mean(xs)), float(np.mean(ys))))

        if len(valid_peaks) >= 2:
            valid_peaks.sort(key=lambda t: t[0], reverse=True)
            p1_val, x1, y1 = valid_peaks[0]
            p2_val, x2, y2 = valid_peaks[1]
            n_steps = max(20, int(np.hypot(x2 - x1, y2 - y1)))
            xs_line = np.clip(np.round(np.linspace(x1, x2, n_steps)).astype(int), 0, w - 1)
            ys_line = np.clip(np.round(np.linspace(y1, y2, n_steps)).astype(int), 0, h - 1)
            neck_val = float(np.min(dist[ys_line, xs_line]))
            if neck_val <= 0.78 * min(p1_val, p2_val):
                return True
    return False


def measure_leaves(
    leaf_mask: np.ndarray,
    px_per_cm: float,
) -> MeasurementResult:
    """Measure connected leaf objects using 8-connectivity and float64 precision.

    Rules enforced:
    - Area always comes from exact pixel counts converted with `px_per_cm^2`.
    - Each pixel is counted at most once (no double counting).
    - Touching/overlapping leaves are detected via multi-core distance-transform neck pinch
      so single spiky, star-shaped, or lobed leaves are never falsely flagged by low solidity alone.
    """
    if px_per_cm <= 0:
        raise ValueError(f"px_per_cm must be positive, got {px_per_cm}.")

    mask_u8 = (leaf_mask > 0).astype(np.uint8)
    px_per_cm_f64 = np.float64(px_per_cm)
    px_per_cm2_f64 = np.float64(px_per_cm_f64 * px_per_cm_f64)

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask_u8, connectivity=config.CC_CONNECTIVITY
    )

    raw_objects: list[dict] = []
    for label_idx in range(1, num_labels):
        area_px = int(stats[label_idx, cv2.CC_STAT_AREA])
        if area_px <= 0:
            continue
        x = int(stats[label_idx, cv2.CC_STAT_LEFT])
        y = int(stats[label_idx, cv2.CC_STAT_TOP])
        w = int(stats[label_idx, cv2.CC_STAT_WIDTH])
        h = int(stats[label_idx, cv2.CC_STAT_HEIGHT])
        cx, cy = float(centroids[label_idx][0]), float(centroids[label_idx][1])

        roi_mask = (labels[y : y + h, x : x + w] == label_idx).astype(np.uint8)
        contours, _ = cv2.findContours(roi_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue
        main_cnt = max(contours, key=cv2.contourArea)
        peri_px = float(cv2.arcLength(main_cnt, True))

        hull = cv2.convexHull(main_cnt)
        hull_area = float(cv2.contourArea(hull))
        cnt_area = float(cv2.contourArea(main_cnt))
        solidity = float(cnt_area / hull_area) if hull_area > 0 else 1.0

        _, (rect_w, rect_h), _ = cv2.minAreaRect(main_cnt)
        dim1_px = float(rect_w + 1.0)
        dim2_px = float(rect_h + 1.0)
        length_px = max(dim1_px, dim2_px)
        width_px = min(dim1_px, dim2_px)

        pinch = _has_narrow_neck_pinch(roi_mask, solidity)

        raw_objects.append({
            "label_idx": label_idx,
            "area_px": area_px,
            "area_cm2": float(np.float64(area_px) / px_per_cm2_f64),
            "perimeter_px": peri_px,
            "perimeter_cm": float(np.float64(peri_px) / px_per_cm_f64),
            "bbox": (x, y, w, h),
            "length_cm": float(np.float64(length_px) / px_per_cm_f64),
            "width_cm": float(np.float64(width_px) / px_per_cm_f64),
            "centroid_px": (cx, cy),
            "solidity": solidity,
            "pinch": pinch,
        })

    raw_objects.sort(key=lambda o: (round(o["centroid_px"][1] / 100.0), o["centroid_px"][0]))

    leaves: list[LeafObject] = []
    relabeled_mask = np.zeros_like(labels, dtype=np.int32)
    touching_detected = False

    for idx, obj in enumerate(raw_objects, start=1):
        is_touching = bool(obj["pinch"])
        if is_touching:
            touching_detected = True

        relabeled_mask[labels == obj["label_idx"]] = idx
        leaves.append(
            LeafObject(
                leaf_id=idx,
                area_px=obj["area_px"],
                area_cm2=obj["area_cm2"],
                perimeter_px=obj["perimeter_px"],
                perimeter_cm=obj["perimeter_cm"],
                bbox=obj["bbox"],
                length_cm=obj["length_cm"],
                width_cm=obj["width_cm"],
                centroid_px=obj["centroid_px"],
                solidity=obj["solidity"],
                is_possible_touching=is_touching,
            )
        )

    total_area_px = int(np.count_nonzero(mask_u8))
    total_area_cm2 = float(np.float64(total_area_px) / px_per_cm2_f64)
    total_perimeter_px = float(np.sum([l.perimeter_px for l in leaves], dtype=np.float64))
    leaf_count = len(leaves)

    if leaf_count > 0:
        arr_f64 = np.array([l.area_cm2 for l in leaves], dtype=np.float64)
        mean_area_cm2 = float(np.mean(arr_f64))
        std_area_cm2 = float(np.std(arr_f64, ddof=0))
    else:
        mean_area_cm2 = 0.0
        std_area_cm2 = 0.0

    warnings: list[str] = []
    if touching_detected:
        warnings.append("possible touching leaves, per-leaf values may be unreliable.")

    return MeasurementResult(
        leaves=leaves,
        total_area_px=total_area_px,
        total_area_cm2=total_area_cm2,
        total_perimeter_px=total_perimeter_px,
        leaf_count=leaf_count,
        mean_area_cm2=mean_area_cm2,
        std_area_cm2=std_area_cm2,
        touching_leaves_detected=touching_detected,
        labeled_mask=relabeled_mask,
        warnings=warnings,
    )
