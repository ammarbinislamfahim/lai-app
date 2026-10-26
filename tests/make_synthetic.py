"""Synthetic ground-truth image generator for Leaf Area & LAI Measurement tests.

Generates:
1. Original Phase 2 synthetic test images (`01_clean_standard` .. `09_border_and_red_calib`) at 3000x2000 px (100 px/cm).
2. Item 1.3 mandatory large-leaf anti-aliased synthetic test suite (`large_A_*`, `large_B_*`, `large_C_*`, `large_D_*`):
   - Case A: one large ellipse, 8 cm × 5 cm (analytical true area = pi * 4.0 * 2.5 = 31.4159265 cm²).
   - Case B: three leaves with widths 3, 5, and 7 cm (6×3 cm, 9×5 cm, 12×7 cm ellipses;
     analytical true area = pi * (3.0*1.5 + 4.5*2.5 + 6.0*3.5) = 115.45353 cm²).
   - Case C: one very large leaf, 12 cm wide, covering ~30% of the frame (23×12 cm ellipse;
     analytical true area = pi * 11.5 * 6.0 = 216.76989 cm²).
   - Case D: Case B on top of a strong brightness gradient and soft gray cast shadow.
   - Rendered at 100, 60, 40, and 25 px/cm, rotated 0° and 17°, both clean PNG and degraded JPEG (quality 90 + Gaussian blur sigma 0.8 + small sensor noise).
"""

import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


SYNTHETIC_WIDTH_PX: int = 3000
SYNTHETIC_HEIGHT_PX: int = 2000
TRUE_PX_PER_CM: float = 100.0
CALIB_SIDE_CM: float = 2.00
CALIB_SIDE_PX: int = int(round(CALIB_SIDE_CM * TRUE_PX_PER_CM))  # 200 px

# Colors in BGR
PAPER_WHITE_BGR: tuple[int, int, int] = (248, 248, 246)
BLUE_SQUARE_BGR: tuple[int, int, int] = (210, 60, 15)     # Strong royal blue (HSV ~111, 236, 210)
RED_SQUARE_BGR: tuple[int, int, int] = (25, 25, 215)      # Strong red (HSV ~0, 223, 215)
GREEN_LEAF_BGR: tuple[int, int, int] = (42, 138, 55)      # Healthy green leaf
BRIGHT_GREEN_LEAF_BGR: tuple[int, int, int] = (50, 155, 65)  # Natural mid-green leaf
DARK_GREEN_LEAF_BGR: tuple[int, int, int] = (32, 110, 42)
YELLOW_LEAF_BGR: tuple[int, int, int] = (30, 185, 215)    # Senescent yellow/amber leaf
BROWN_LEAF_BGR: tuple[int, int, int] = (35, 95, 145)      # Dry brown leaf


def _create_blank_canvas(
    width: int = SYNTHETIC_WIDTH_PX,
    height: int = SYNTHETIC_HEIGHT_PX,
    bg_bgr: tuple[int, int, int] = PAPER_WHITE_BGR,
) -> np.ndarray:
    canvas = np.empty((height, width, 3), dtype=np.uint8)
    canvas[:] = bg_bgr
    return canvas


def _draw_calibration_square(
    canvas: np.ndarray,
    top_left: tuple[int, int] = (180, 180),
    side_px: int = CALIB_SIDE_PX,
    color_bgr: tuple[int, int, int] = BLUE_SQUARE_BGR,
) -> np.ndarray:
    """Draw axis-aligned calibration square and return its binary mask (uint8 0/1)."""
    x0, y0 = top_left
    calib_mask = np.zeros(canvas.shape[:2], dtype=np.uint8)
    calib_mask[y0 : y0 + side_px, x0 : x0 + side_px] = 1
    canvas[calib_mask == 1] = color_bgr
    return calib_mask


def draw_aa_rotated_square(
    canvas: np.ndarray,
    center_px: tuple[float, float],
    side_px: float,
    angle_deg: float,
    color_bgr: tuple[int, int, int] = BLUE_SQUARE_BGR,
    ss: int = 4,
) -> None:
    """Render an anti-aliased rotated square of exact analytical side `side_px` using ROI supersampling."""
    h, w = canvas.shape[:2]
    cx, cy = center_px
    r_bound = int(math.ceil(side_px * 0.85)) + 4
    x0, y0 = max(0, int(cx) - r_bound), max(0, int(cy) - r_bound)
    x1, y1 = min(w, int(cx) + r_bound), min(h, int(cy) + r_bound)
    if x1 <= x0 or y1 <= y0:
        return

    xs = (np.arange(x0 * ss, x1 * ss, dtype=np.float32) + 0.5) / float(ss) - float(cx)
    ys = (np.arange(y0 * ss, y1 * ss, dtype=np.float32) + 0.5) / float(ss) - float(cy)
    rad = math.radians(angle_deg)
    ca, sa = float(math.cos(rad)), float(math.sin(rad))
    ux = xs[None, :] * ca + ys[:, None] * sa
    uy = -xs[None, :] * sa + ys[:, None] * ca
    half = 0.5 * float(side_px)
    inside = (np.abs(ux) <= half) & (np.abs(uy) <= half)
    alpha = inside.reshape(y1 - y0, ss, x1 - x0, ss).mean(axis=(1, 3))[:, :, None]
    roi = canvas[y0:y1, x0:x1].astype(np.float32)
    col = np.array(color_bgr, dtype=np.float32)[None, None, :]
    canvas[y0:y1, x0:x1] = np.round(roi * (1.0 - alpha) + col * alpha).astype(np.uint8)


def draw_aa_ellipse(
    canvas: np.ndarray,
    center_px: tuple[float, float],
    semi_major_px: float,
    semi_minor_px: float,
    angle_deg: float,
    color_bgr: tuple[int, int, int] = BRIGHT_GREEN_LEAF_BGR,
    ss: int = 4,
) -> None:
    """Render an anti-aliased ellipse of exact analytical area `pi * a * b` using ROI supersampling."""
    h, w = canvas.shape[:2]
    cx, cy = center_px
    r_bound = int(math.ceil(max(semi_major_px, semi_minor_px))) + 4
    x0, y0 = max(0, int(cx) - r_bound), max(0, int(cy) - r_bound)
    x1, y1 = min(w, int(cx) + r_bound), min(h, int(cy) + r_bound)
    if x1 <= x0 or y1 <= y0:
        return

    xs = (np.arange(x0 * ss, x1 * ss, dtype=np.float32) + 0.5) / float(ss) - float(cx)
    ys = (np.arange(y0 * ss, y1 * ss, dtype=np.float32) + 0.5) / float(ss) - float(cy)
    rad = math.radians(angle_deg)
    ca, sa = float(math.cos(rad)), float(math.sin(rad))
    ux = xs[None, :] * ca + ys[:, None] * sa
    uy = -xs[None, :] * sa + ys[:, None] * ca
    inside = (ux / float(semi_major_px)) ** 2 + (uy / float(semi_minor_px)) ** 2 <= 1.0
    alpha = inside.reshape(y1 - y0, ss, x1 - x0, ss).mean(axis=(1, 3))[:, :, None]
    roi = canvas[y0:y1, x0:x1].astype(np.float32)
    col = np.array(color_bgr, dtype=np.float32)[None, None, :]
    canvas[y0:y1, x0:x1] = np.round(roi * (1.0 - alpha) + col * alpha).astype(np.uint8)


def _make_leaf_polygon(center_x: int, center_y: int, length_px: int, width_px: int) -> np.ndarray:
    """Create a smooth, realistic ovate leaf polygon with 120 vertices."""
    t = np.linspace(0, 2 * np.pi, 120, endpoint=False)
    x = 0.5 * length_px * np.cos(t)
    taper = 0.75 + 0.25 * np.cos(t)
    y = 0.5 * width_px * np.sin(t) * taper
    pts = np.stack([center_x + x, center_y + y], axis=1)
    return np.round(pts).astype(np.int32)


def _save_case(
    output_dir: Path,
    name: str,
    canvas: np.ndarray,
    leaf_masks: list[np.ndarray],
    px_per_cm: float = TRUE_PX_PER_CM,
    calib_side_cm: float = CALIB_SIDE_CM,
    calib_color: str = "blue",
    description: str = "",
    dpi: int = 254,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Save PNG image and companion ground-truth JSON with exact pixel-derived cm^2 areas."""
    output_dir.mkdir(parents=True, exist_ok=True)
    img_path = output_dir / f"{name}.png"
    json_path = output_dir / f"{name}.json"

    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)
    pil_img.save(img_path, format="PNG", dpi=(dpi, dpi))

    combined_mask = np.zeros(canvas.shape[:2], dtype=np.uint8)
    per_leaf_areas_cm2: list[float] = []
    per_leaf_areas_px: list[int] = []
    px_per_cm2 = float(px_per_cm ** 2)

    for m in leaf_masks:
        m_bool = m > 0
        combined_mask[m_bool] = 1
        px_count = int(np.count_nonzero(m_bool))
        per_leaf_areas_px.append(px_count)
        per_leaf_areas_cm2.append(float(px_count / px_per_cm2))

    total_px = int(np.count_nonzero(combined_mask))
    total_area_cm2 = float(total_px / px_per_cm2)

    meta: dict[str, Any] = {
        "image_filename": img_path.name,
        "description": description,
        "width_px": int(canvas.shape[1]),
        "height_px": int(canvas.shape[0]),
        "true_px_per_cm": float(px_per_cm),
        "calib_side_cm": float(calib_side_cm),
        "calib_color": calib_color,
        "true_leaf_count": len(leaf_masks),
        "true_total_pixels": total_px,
        "true_area_cm2": total_area_cm2,
        "per_leaf_areas_px": per_leaf_areas_px,
        "per_leaf_areas_cm2": per_leaf_areas_cm2,
    }
    if extra_meta:
        meta.update(extra_meta)

    json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def render_large_leaf_scene(
    case_id: str,
    scale_px_per_cm: float,
    angle_deg: float = 0.0,
    degraded: bool = False,
    rng_seed: int = 123,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Render an anti-aliased large-leaf synthetic scene (Cases A, B, C, D) in memory or for disk storage.

    Physical frame is 32 cm × 32 cm so that even at 25 px/cm the image is 800×800 px.
    Returns `(image_bgr, ground_truth_metadata)`.
    """
    w = max(800, int(round(32.0 * scale_px_per_cm)))
    h = max(800, int(round(32.0 * scale_px_per_cm)))
    canvas = _create_blank_canvas(width=w, height=h)

    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)

    def rot_cm_to_px(x_cm: float, y_cm: float) -> tuple[float, float]:
        dx, dy = x_cm - 16.0, y_cm - 16.0
        rx = 16.0 + dx * cos_a - dy * sin_a
        ry = 16.0 + dx * sin_a + dy * cos_a
        return rx * scale_px_per_cm, ry * scale_px_per_cm

    # Draw 2.00 cm blue calibration square centered at (4.2 cm, 4.2 cm), rotated by angle_deg
    cal_cx, cal_cy = rot_cm_to_px(4.2, 4.2)
    draw_aa_rotated_square(
        canvas,
        center_px=(cal_cx, cal_cy),
        side_px=CALIB_SIDE_CM * scale_px_per_cm,
        angle_deg=angle_deg,
        color_bgr=BLUE_SQUARE_BGR,
    )

    c_upper = case_id.upper().strip()
    per_leaf_true_cm2: list[float] = []

    if c_upper == "A":
        # One large ellipse, 8 cm x 5 cm -> semi-axes a = 4.0 cm, b = 2.5 cm
        a_cm, b_cm = 4.0, 2.5
        draw_aa_ellipse(
            canvas,
            center_px=rot_cm_to_px(17.0, 16.0),
            semi_major_px=a_cm * scale_px_per_cm,
            semi_minor_px=b_cm * scale_px_per_cm,
            angle_deg=angle_deg,
            color_bgr=BRIGHT_GREEN_LEAF_BGR,
        )
        per_leaf_true_cm2.append(float(math.pi * a_cm * b_cm))
        desc = f"Case A: 8x5 cm large ellipse at {scale_px_per_cm:.0f} px/cm, rot {angle_deg:.0f} deg"

    elif c_upper in {"B", "D"}:
        # Three leaves with widths 3, 5, and 7 cm: (6x3 cm, 9x5 cm, 12x7 cm ellipses)
        specs = [
            (11.5, 10.5, 3.0, 1.5),
            (21.5, 10.5, 4.5, 2.5),
            (16.5, 21.0, 6.0, 3.5),
        ]
        for lx, ly, la, lb in specs:
            draw_aa_ellipse(
                canvas,
                center_px=rot_cm_to_px(lx, ly),
                semi_major_px=la * scale_px_per_cm,
                semi_minor_px=lb * scale_px_per_cm,
                angle_deg=angle_deg,
                color_bgr=BRIGHT_GREEN_LEAF_BGR,
            )
            per_leaf_true_cm2.append(float(math.pi * la * lb))
        desc = f"Case {c_upper}: 3, 5, 7 cm wide leaves at {scale_px_per_cm:.0f} px/cm, rot {angle_deg:.0f} deg"

    elif c_upper == "C":
        # One very large leaf, 12 cm wide, covering ~27-30% of the frame (23x12 cm ellipse -> semi-axes 11.5 x 6.0 cm)
        a_cm, b_cm = 11.5, 6.0
        draw_aa_ellipse(
            canvas,
            center_px=rot_cm_to_px(17.0, 17.5),
            semi_major_px=a_cm * scale_px_per_cm,
            semi_minor_px=b_cm * scale_px_per_cm,
            angle_deg=angle_deg,
            color_bgr=BRIGHT_GREEN_LEAF_BGR,
        )
        per_leaf_true_cm2.append(float(math.pi * a_cm * b_cm))
        desc = f"Case C: 23x12 cm very large leaf at {scale_px_per_cm:.0f} px/cm, rot {angle_deg:.0f} deg"
    else:
        raise ValueError(f"Unknown large-leaf case_id: {case_id}")

    if c_upper == "D":
        # Add soft gray cast shadow and strong brightness gradient
        sh = np.zeros((h, w), dtype=np.float64)
        for lx, ly, la, lb in [(11.5, 10.5, 3.0, 1.5), (21.5, 10.5, 4.5, 2.5), (16.5, 21.0, 6.0, 3.5)]:
            sx_px, sy_px = rot_cm_to_px(lx + 0.4, ly + 0.4)
            cv2.ellipse(
                sh,
                (int(round(sx_px)), int(round(sy_px))),
                (int(round((la + 0.1) * scale_px_per_cm)), int(round((lb + 0.1) * scale_px_per_cm))),
                angle_deg,
                0,
                360,
                1.0,
                thickness=-1,
            )
        k_sh = max(15, int(round(0.6 * scale_px_per_cm)) | 1)
        if k_sh % 2 == 0:
            k_sh += 1
        sh = cv2.GaussianBlur(sh, (k_sh, k_sh), 0)
        is_paper = canvas[:, :, 2] > 180
        for c in range(3):
            ch = canvas[:, :, c].astype(np.float64)
            ch[is_paper] *= 1.0 - 0.22 * sh[is_paper]
            canvas[:, :, c] = np.clip(ch, 0, 255).astype(np.uint8)

        xg = np.linspace(0.78, 1.04, w, dtype=np.float64)[None, :, None]
        yg = np.linspace(0.84, 1.02, h, dtype=np.float64)[:, None, None]
        canvas = np.clip(canvas.astype(np.float64) * xg * yg, 0, 255).astype(np.uint8)

    if degraded:
        rng = np.random.default_rng(rng_seed)
        canvas_blur = cv2.GaussianBlur(canvas.astype(np.float64), (0, 0), sigmaX=0.8, sigmaY=0.8)
        noise = rng.normal(0.0, 2.5, size=canvas.shape)
        canvas_noisy = np.clip(canvas_blur + noise, 0, 255).astype(np.uint8)
        ok, buf = cv2.imencode(".jpg", canvas_noisy, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if ok:
            canvas = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        desc += " (JPEG90 + blur sigma 0.8 + sensor noise)"

    true_total_cm2 = float(sum(per_leaf_true_cm2))
    meta = {
        "case_id": c_upper,
        "description": desc,
        "width_px": w,
        "height_px": h,
        "true_px_per_cm": float(scale_px_per_cm),
        "calib_side_cm": float(CALIB_SIDE_CM),
        "calib_color": "blue",
        "angle_deg": float(angle_deg),
        "degraded": bool(degraded),
        "true_leaf_count": len(per_leaf_true_cm2),
        "true_area_cm2": true_total_cm2,
        "per_leaf_areas_cm2": per_leaf_true_cm2,
    }
    return canvas, meta


def generate_all_synthetic_images(
    output_dir: Path | str,
    include_large_suite_on_disk: bool = True,
) -> dict[str, dict[str, Any]]:
    """Generate the complete suite of synthetic ground-truth images and return their metadata."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}

    # 1. Clean multi-shape reference image (circle, ellipse, rectangle, leaf polygon)
    canvas1 = _create_blank_canvas()
    _draw_calibration_square(canvas1, top_left=(180, 180))
    masks1: list[np.ndarray] = []

    m_rect = np.zeros(canvas1.shape[:2], dtype=np.uint8)
    m_rect[300:600, 650:1050] = 1
    canvas1[m_rect == 1] = GREEN_LEAF_BGR
    masks1.append(m_rect)

    m_circ = np.zeros(canvas1.shape[:2], dtype=np.uint8)
    cv2.circle(m_circ, (1550, 500), 180, 1, thickness=-1)
    canvas1[m_circ == 1] = GREEN_LEAF_BGR
    masks1.append(m_circ)

    m_ell = np.zeros(canvas1.shape[:2], dtype=np.uint8)
    cv2.ellipse(m_ell, (2300, 520), (260, 140), 15, 0, 360, 1, thickness=-1)
    canvas1[m_ell == 1] = DARK_GREEN_LEAF_BGR
    masks1.append(m_ell)

    m_poly = np.zeros(canvas1.shape[:2], dtype=np.uint8)
    poly_pts = _make_leaf_polygon(1100, 1300, 640, 380)
    cv2.fillPoly(m_poly, [poly_pts], 1)
    canvas1[m_poly == 1] = GREEN_LEAF_BGR
    masks1.append(m_poly)

    results["01_clean_standard"] = _save_case(
        out,
        "01_clean_standard",
        canvas1,
        masks1,
        description="Clean white background with blue 2cm square and 4 standard green shapes",
    )

    # 2. Leaf with a real hole (insect herbivory damage) + tiny noise holes
    canvas2 = _create_blank_canvas()
    _draw_calibration_square(canvas2, top_left=(180, 180))
    m_holed = np.zeros(canvas2.shape[:2], dtype=np.uint8)
    poly_pts2 = _make_leaf_polygon(1500, 1000, 800, 500)
    cv2.fillPoly(m_holed, [poly_pts2], 1)
    cv2.circle(m_holed, (1450, 980), 75, 0, thickness=-1)
    cv2.circle(m_holed, (1650, 1060), 45, 0, thickness=-1)
    canvas2[m_holed == 1] = GREEN_LEAF_BGR
    canvas2[900:904, 1350:1354] = PAPER_WHITE_BGR

    results["02_leaf_with_hole"] = _save_case(
        out,
        "02_leaf_with_hole",
        canvas2,
        [m_holed],
        description="Green leaf with two large insect-damage holes (must remain excluded) and one tiny noise pinhole",
    )

    # 3. Mild Gaussian sensor noise
    rng = np.random.default_rng(42)
    canvas3 = canvas1.copy()
    noise = rng.normal(0.0, 4.5, size=canvas3.shape)
    canvas3 = np.clip(canvas3.astype(np.float64) + noise, 0, 255).astype(np.uint8)
    results["03_mild_gaussian_noise"] = _save_case(
        out,
        "03_mild_gaussian_noise",
        canvas3,
        masks1,
        description="Standard shapes with mild Gaussian sensor noise (sigma=4.5)",
    )

    # 4. Soft gray cast shadow next to and around leaves
    canvas4 = _create_blank_canvas()
    _draw_calibration_square(canvas4, top_left=(180, 180))
    masks4: list[np.ndarray] = []

    m_s1 = np.zeros(canvas4.shape[:2], dtype=np.uint8)
    poly_s1 = _make_leaf_polygon(1100, 950, 620, 360)
    cv2.fillPoly(m_s1, [poly_s1], 1)
    masks4.append(m_s1)

    m_s2 = np.zeros(canvas4.shape[:2], dtype=np.uint8)
    poly_s2 = _make_leaf_polygon(2050, 1100, 560, 340)
    cv2.fillPoly(m_s2, [poly_s2], 1)
    masks4.append(m_s2)

    shadow_mask = np.zeros(canvas4.shape[:2], dtype=np.float64)
    M_shift = np.float32([[1, 0, 40], [0, 1, 35]])
    for m in masks4:
        shifted = cv2.warpAffine(m.astype(np.float64), M_shift, (canvas4.shape[1], canvas4.shape[0]))
        shadow_mask = np.maximum(shadow_mask, shifted)
    cv2.ellipse(shadow_mask, (1550, 1550), (350, 120), 0, 0, 360, 0.85, thickness=-1)
    shadow_blur = cv2.GaussianBlur(shadow_mask, (51, 51), 18.0)

    attenuation = 1.0 - 0.26 * shadow_blur[..., None]
    canvas4 = np.clip(canvas4.astype(np.float64) * attenuation, 0, 255).astype(np.uint8)
    canvas4[m_s1 == 1] = GREEN_LEAF_BGR
    canvas4[m_s2 == 1] = DARK_GREEN_LEAF_BGR

    results["04_soft_gray_shadow"] = _save_case(
        out,
        "04_soft_gray_shadow",
        canvas4,
        masks4,
        description="Leaves with realistic soft gray drop shadows and background shadow patch",
    )

    # 5. Brightness / illumination gradient across the scene
    canvas5 = canvas1.copy()
    x_grid = np.linspace(0.82, 1.04, canvas5.shape[1], dtype=np.float64)[None, :, None]
    y_grid = np.linspace(0.88, 1.02, canvas5.shape[0], dtype=np.float64)[:, None, None]
    illum_field = x_grid * y_grid
    canvas5 = np.clip(canvas5.astype(np.float64) * illum_field, 0, 255).astype(np.uint8)
    results["05_brightness_gradient"] = _save_case(
        out,
        "05_brightness_gradient",
        canvas5,
        masks1,
        description="Standard shapes under uneven lighting gradient across X and Y axes",
    )

    # 6. Rotated whole image / objects by 7 degrees
    canvas6 = _create_blank_canvas()
    angle_deg = 7.0
    center = (SYNTHETIC_WIDTH_PX // 2, SYNTHETIC_HEIGHT_PX // 2)
    rot_mat = cv2.getRotationMatrix2D(center, angle_deg, 1.0)

    calib_unrot = np.zeros(canvas6.shape[:2], dtype=np.uint8)
    calib_unrot[280 : 280 + CALIB_SIDE_PX, 280 : 280 + CALIB_SIDE_PX] = 1
    calib_rot = cv2.warpAffine(
        calib_unrot, rot_mat, (SYNTHETIC_WIDTH_PX, SYNTHETIC_HEIGHT_PX), flags=cv2.INTER_NEAREST
    )
    canvas6[calib_rot == 1] = BLUE_SQUARE_BGR

    masks6: list[np.ndarray] = []
    for m_orig, col in zip(masks1, [GREEN_LEAF_BGR, GREEN_LEAF_BGR, DARK_GREEN_LEAF_BGR, GREEN_LEAF_BGR]):
        m_rot = cv2.warpAffine(
            m_orig, rot_mat, (SYNTHETIC_WIDTH_PX, SYNTHETIC_HEIGHT_PX), flags=cv2.INTER_NEAREST
        )
        canvas6[m_rot == 1] = col
        masks6.append(m_rot)

    results["06_rotated_image"] = _save_case(
        out,
        "06_rotated_image",
        canvas6,
        masks6,
        description="Calibration square and leaves rotated by 7 degrees",
    )

    # 7. Tiny dust specks on the background
    canvas7 = canvas1.copy()
    speck_coords = [
        (450, 900, 8),
        (520, 1100, 6),
        (1900, 1400, 9),
        (2500, 1200, 7),
        (1600, 1700, 5),
        (800, 1750, 10),
    ]
    for sx, sy, sr in speck_coords:
        cv2.circle(canvas7, (sx, sy), sr, (40, 80, 50), thickness=-1)

    results["07_dust_specks"] = _save_case(
        out,
        "07_dust_specks",
        canvas7,
        masks1,
        description="Standard shapes plus 6 dark dust/soil specks (< 0.05 cm^2 each) that must be ignored",
    )

    # 8. Yellow/brown senescent leaf alongside green leaves
    canvas8 = _create_blank_canvas()
    _draw_calibration_square(canvas8, top_left=(180, 180))
    masks8: list[np.ndarray] = []

    m_g1 = np.zeros(canvas8.shape[:2], dtype=np.uint8)
    cv2.fillPoly(m_g1, [_make_leaf_polygon(950, 700, 580, 340)], 1)
    canvas8[m_g1 == 1] = GREEN_LEAF_BGR
    masks8.append(m_g1)

    m_y1 = np.zeros(canvas8.shape[:2], dtype=np.uint8)
    cv2.fillPoly(m_y1, [_make_leaf_polygon(1950, 720, 600, 360)], 1)
    canvas8[m_y1 == 1] = YELLOW_LEAF_BGR
    masks8.append(m_y1)

    m_b1 = np.zeros(canvas8.shape[:2], dtype=np.uint8)
    cv2.fillPoly(m_b1, [_make_leaf_polygon(1450, 1400, 540, 320)], 1)
    canvas8[m_b1 == 1] = BROWN_LEAF_BGR
    masks8.append(m_b1)

    results["08_yellow_brown_leaves"] = _save_case(
        out,
        "08_yellow_brown_leaves",
        canvas8,
        masks8,
        description="Combination of healthy green, senescent yellow, and dry brown leaves",
    )

    # 9. Border-touching object + Red calibration square
    canvas9 = _create_blank_canvas()
    _draw_calibration_square(canvas9, top_left=(180, 180), color_bgr=RED_SQUARE_BGR)
    masks9: list[np.ndarray] = []

    m_valid = np.zeros(canvas9.shape[:2], dtype=np.uint8)
    cv2.fillPoly(m_valid, [_make_leaf_polygon(1400, 1000, 640, 380)], 1)
    canvas9[m_valid == 1] = GREEN_LEAF_BGR
    masks9.append(m_valid)

    m_border = np.zeros(canvas9.shape[:2], dtype=np.uint8)
    m_border[700:1100, 2750:3000] = 1
    canvas9[m_border == 1] = GREEN_LEAF_BGR

    results["09_border_and_red_calib"] = _save_case(
        out,
        "09_border_and_red_calib",
        canvas9,
        masks9,
        calib_color="red",
        description="Red calibration square, one valid interior leaf, and one leaf cut off by the right image border",
        extra_meta={"expects_border_warning": True},
    )

    # 10. Item C.1 / Issue B: Blue 2 cm square + Red 2 cm extra square + 10 cm x 10 cm green square (100 cm^2)
    canvas10 = _create_blank_canvas()
    _draw_calibration_square(canvas10, top_left=(180, 180), color_bgr=BLUE_SQUARE_BGR)
    _draw_calibration_square(canvas10, top_left=(520, 180), color_bgr=RED_SQUARE_BGR)
    m_green10 = np.zeros(canvas10.shape[:2], dtype=np.uint8)
    m_green10[550:1550, 950:1950] = 1
    canvas10[m_green10 == 1] = GREEN_LEAF_BGR

    results["10_extra_calib_square"] = _save_case(
        out,
        "10_extra_calib_square",
        canvas10,
        [m_green10],
        calib_color="blue",
        description="Blue 2cm calibration square, extra Red 2cm square (must be excluded), and 10x10cm green square (100 cm^2)",
        extra_meta={"expects_extra_square_warning": True},
    )

    # 11. Item C.2 / Issue B: Blue 2 cm square + Red 3 cm x 1.5 cm elliptical leaf (must NOT be excluded)
    canvas11 = _create_blank_canvas()
    _draw_calibration_square(canvas11, top_left=(180, 180), color_bgr=BLUE_SQUARE_BGR)
    m_red_leaf = np.zeros(canvas11.shape[:2], dtype=np.uint8)
    cv2.ellipse(m_red_leaf, (1400, 1000), (150, 75), 0, 0, 360, 1, thickness=-1)
    canvas11[m_red_leaf == 1] = RED_SQUARE_BGR

    results["11_red_elliptical_leaf"] = _save_case(
        out,
        "11_red_elliptical_leaf",
        canvas11,
        [m_red_leaf],
        calib_color="blue",
        description="Blue 2cm calibration square and a red 3.0cm x 1.5cm elliptical leaf (must be measured, not removed)",
    )

    # Item 1.3: Save representative large-leaf anti-aliased images & analytical JSONs to disk as well
    if include_large_suite_on_disk:
        for cid in ("A", "B", "C", "D"):
            for sc in (100.0, 60.0, 40.0, 25.0):
                for ang in (0.0, 17.0):
                    for deg in (False, True):
                        tag = f"large_{cid}_s{int(sc)}_r{int(ang)}_{'jpg90' if deg else 'clean'}"
                        ext = "jpg" if deg else "png"
                        img_bgr, meta = render_large_leaf_scene(cid, sc, ang, deg)
                        img_file = out / f"{tag}.{ext}"
                        json_file = out / f"{tag}.json"
                        if deg:
                            cv2.imwrite(str(img_file), img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                        else:
                            cv2.imwrite(str(img_file), img_bgr)
                        meta["image_filename"] = img_file.name
                        json_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
                        results[tag] = meta

    return results


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "sample_images"
    summary = generate_all_synthetic_images(target, include_large_suite_on_disk=True)
    print(f"Generated {len(summary)} synthetic images in {target}.")
