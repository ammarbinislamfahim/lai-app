"""FastAPI application and API routes for Fully Automatic Leaf Area & LAI Measurement."""

import asyncio
import base64
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Optional
import uuid

import cv2
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
import numpy as np
from pydantic import BaseModel, Field

from app import config
from app.export import export_session_to_csv, export_session_to_xlsx
from app.paths import resource_path, user_data_dir
from app.pipeline.calibration import CalibrationResult, detect_calibration
from app.pipeline.lai import calculate_lai
from app.pipeline.loader import ImageLoadError, load_image_from_bytes
from app.pipeline.measurement import MeasurementResult, measure_leaves
from app.pipeline.quality import evaluate_quality
from app.pipeline.segmentation import segment_leaves

STATIC_DIR: Path = resource_path("app/static")
SAMPLE_IMAGES_DIR: Path = resource_path("sample_images")
CALIBRATION_BLUE_PDF_PATH: Path = resource_path("app/static/calibration_sheet_a4.pdf")
CALIBRATION_RED_PDF_PATH: Path = resource_path("app/static/calibration_sheet_a4_red.pdf")

app = FastAPI(
    title=config.SOFTWARE_NAME,
    version=config.SOFTWARE_VERSION,
    description="Fully automatic leaf area (cm²) and Leaf Area Index (LAI) scientific web application.",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_SESSIONS: dict[str, dict[str, Any]] = {}

# Client heartbeat & desktop lifecycle state (protected by _STATE_LOCK)
_STATE_LOCK = threading.Lock()
_ACTIVE_CLIENTS: dict[str, float] = {}
_HAS_EVER_CONNECTED: bool = False
_LAST_CLIENT_LEFT_AT: Optional[float] = None
_ACTIVE_ANALYZE_COUNT: int = 0
_QUIT_REQUESTED: bool = False
_SHUTDOWN_CALLBACK: Optional[Callable[[], None]] = None

_LOCALHOST_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def _require_localhost(request: Request) -> None:
    """Ensure endpoint is only reachable from 127.0.0.1 / localhost."""
    client_host = request.client.host if request.client is not None else ""
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded and forwarded.split(",")[0].strip() not in _LOCALHOST_HOSTS:
        raise HTTPException(status_code=403, detail="Forbidden: endpoint is restricted to 127.0.0.1.")
    if client_host not in _LOCALHOST_HOSTS:
        raise HTTPException(status_code=403, detail="Forbidden: endpoint is restricted to 127.0.0.1.")


def reset_lifecycle_state() -> None:
    """Reset client heartbeat and lifecycle tracking state (used by launcher startup and tests)."""
    global _HAS_EVER_CONNECTED, _LAST_CLIENT_LEFT_AT, _ACTIVE_ANALYZE_COUNT, _QUIT_REQUESTED
    with _STATE_LOCK:
        _ACTIVE_CLIENTS.clear()
        _HAS_EVER_CONNECTED = False
        _LAST_CLIENT_LEFT_AT = None
        _ACTIVE_ANALYZE_COUNT = 0
        _QUIT_REQUESTED = False


def set_shutdown_callback(callback: Optional[Callable[[], None]]) -> None:
    """Register a callback invoked when `/api/quit` is called."""
    global _SHUTDOWN_CALLBACK
    with _STATE_LOCK:
        _SHUTDOWN_CALLBACK = callback


def get_lifecycle_snapshot(silence_timeout_sec: float = 120.0) -> dict[str, Any]:
    """Prune silent clients (> `silence_timeout_sec`) and return current lifecycle state snapshot."""
    global _LAST_CLIENT_LEFT_AT
    now = time.monotonic()
    with _STATE_LOCK:
        expired = [cid for cid, last_ts in _ACTIVE_CLIENTS.items() if (now - last_ts) > silence_timeout_sec]
        for cid in expired:
            _ACTIVE_CLIENTS.pop(cid, None)
        if _HAS_EVER_CONNECTED and len(_ACTIVE_CLIENTS) == 0 and _LAST_CLIENT_LEFT_AT is None:
            _LAST_CLIENT_LEFT_AT = now
        return {
            "has_ever_connected": _HAS_EVER_CONNECTED,
            "active_client_count": len(_ACTIVE_CLIENTS),
            "last_client_left_at": _LAST_CLIENT_LEFT_AT,
            "active_analyze_count": _ACTIVE_ANALYZE_COUNT,
            "quit_requested": _QUIT_REQUESTED,
            "now": now,
        }


def _max_upload_bytes() -> int:
    """Return active maximum upload size in bytes (supports runtime config or env override)."""
    env_mb = os.environ.get("LEAFAREA_MAX_UPLOAD_MB")
    if env_mb is not None:
        return int(float(env_mb) * 1024 * 1024)
    return int(config.MAX_UPLOAD_MB * 1024 * 1024)


@app.middleware("http")
async def enforce_upload_size_limit(request: Request, call_next: Any) -> Response:
    """Reject oversized uploads early with HTTP 413 when Content-Length exceeds MAX_UPLOAD_MB."""
    if request.url.path == "/api/analyze" and request.method.upper() == "POST":
        max_bytes = _max_upload_bytes()
        max_mb = max_bytes / (1024 * 1024)
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": (
                                f"Upload size ({int(content_length) / (1024 * 1024):.1f} MB) exceeds the "
                                f"maximum allowed limit of {max_mb:.0f} MB."
                            )
                        },
                    )
            except ValueError:
                pass
    return await call_next(request)


class LeafMeasurementOut(BaseModel):
    leaf_id: int
    area_px: int
    area_cm2: float
    area_cm2_display: float
    length_cm: float
    length_cm_display: float
    width_cm: float
    width_cm_display: float
    perimeter_cm: float
    bbox: list[int]
    centroid_px: list[float]
    solidity: float
    is_possible_touching: bool


class ImageAnalysisOut(BaseModel):
    filename: str
    width_px: int
    height_px: int
    dpi: Optional[float] = None
    exif_orientation_applied: bool = False
    needs_manual_scale: bool = False
    px_per_cm: Optional[float] = None
    px_per_cm_display: Optional[float] = None
    area_px_per_cm: Optional[float] = None
    area_px_per_cm_display: Optional[float] = None
    edge_px_per_cm: Optional[float] = None
    edge_px_per_cm_display: Optional[float] = None
    calibration_method: str
    perspective_corrected: bool = False
    extra_squares_excluded: int = 0
    otsu_threshold: Optional[float] = None
    otsu_threshold_display: Optional[float] = None
    edge_threshold: Optional[float] = None
    edge_threshold_display: Optional[float] = None
    leaf_count: int = 0
    total_area_px: int = 0
    total_area_cm2: float = 0.0
    total_area_cm2_display: float = 0.0
    mean_area_cm2: float = 0.0
    mean_area_cm2_display: float = 0.0
    std_area_cm2: float = 0.0
    std_area_cm2_display: float = 0.0
    uncertainty_cm2: float = 0.0
    uncertainty_cm2_display: float = 0.0
    uncertainty_pct: float = 0.0
    confidence: str
    warnings: list[str] = Field(default_factory=list)
    leaves: list[LeafMeasurementOut] = Field(default_factory=list)
    original_preview_b64: Optional[str] = None
    overlay_image_b64: Optional[str] = None


class BatchSummaryOut(BaseModel):
    image_count: int
    total_leaf_count: int
    total_leaf_area_cm2: float
    total_leaf_area_cm2_display: float
    total_leaf_area_m2: float
    mean_leaf_area_cm2: float
    mean_leaf_area_cm2_display: float
    total_uncertainty_cm2: float
    total_uncertainty_cm2_display: float
    ground_area_m2: Optional[float] = None
    lai: Optional[float] = None
    lai_display: Optional[float] = None
    lai_uncertainty: Optional[float] = None
    lai_uncertainty_display: Optional[float] = None
    lai_mode: str = "none"
    overall_confidence: str
    needs_manual_scale: bool = False
    all_warnings: list[str] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    session_id: str
    software_version: str
    timestamp_utc: str
    needs_manual_scale: bool
    images: list[ImageAnalysisOut]
    batch_summary: BatchSummaryOut


def _encode_bgr_to_b64_jpeg(image_bgr: np.ndarray, max_dim: int = config.DISPLAY_MAX_DIMENSION_PX) -> str:
    """Create a browser-friendly base64 JPEG preview (ONLY for display; measurement uses full res)."""
    h, w = image_bgr.shape[:2]
    scale = min(1.0, float(max_dim) / float(max(h, w)))
    if scale < 1.0:
        disp = cv2.resize(
            image_bgr,
            (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        disp = image_bgr
    ok, buf = cv2.imencode(".jpg", disp, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


def _render_verification_overlay(
    image_bgr: np.ndarray,
    calibration: CalibrationResult,
    leaf_mask: np.ndarray,
    measurement: MeasurementResult,
) -> str:
    """Render visual verification overlay showing outlined leaves (green), calibration square (orange), and leaf IDs."""
    overlay = image_bgr.copy()
    h, w = overlay.shape[:2]
    line_thick = max(2, int(round(max(h, w) / 700.0)))
    font_scale = max(0.6, float(max(h, w) / 2400.0))
    font_thick = max(2, int(round(line_thick * 0.9)))

    leaf_bool = leaf_mask > 0
    if np.any(leaf_bool):
        overlay[leaf_bool, 0] = np.uint8(
            np.clip(overlay[leaf_bool, 0].astype(np.uint16) * 72 // 100 + 40 * 28 // 100, 0, 255)
        )
        overlay[leaf_bool, 1] = np.uint8(
            np.clip(overlay[leaf_bool, 1].astype(np.uint16) * 72 // 100 + 230 * 28 // 100, 0, 255)
        )
        overlay[leaf_bool, 2] = np.uint8(
            np.clip(overlay[leaf_bool, 2].astype(np.uint16) * 72 // 100 + 40 * 28 // 100, 0, 255)
        )

    contours, _ = cv2.findContours(
        (leaf_mask > 0).astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(overlay, contours, -1, (0, 255, 100), thickness=line_thick)

    if calibration.detected_corners is not None:
        pts = np.round(calibration.detected_corners).astype(np.int32).reshape((-1, 1, 2))
        cv2.polylines(overlay, [pts], isClosed=True, color=(0, 180, 255), thickness=line_thick + 1)
        cx_cal = int(np.mean(calibration.detected_corners[:, 0]))
        cy_cal = int(np.mean(calibration.detected_corners[:, 1]))
        cv2.putText(
            overlay,
            "CALIB",
            (max(10, cx_cal - 45), max(30, cy_cal)),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale * 0.85,
            (0, 180, 255),
            font_thick,
            cv2.LINE_AA,
        )

    for leaf in measurement.leaves:
        cx, cy = int(round(leaf.centroid_px[0])), int(round(leaf.centroid_px[1]))
        label_str = f"#{leaf.leaf_id}"
        (tw, th), _ = cv2.getTextSize(label_str, cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_thick)
        pad = 6
        x1 = max(0, cx - tw // 2 - pad)
        y1 = max(0, cy - th // 2 - pad)
        x2 = min(w - 1, cx + tw // 2 + pad)
        y2 = min(h - 1, cy + th // 2 + pad)
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (20, 20, 20), thickness=-1)
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 255, 100), thickness=max(1, line_thick // 2))
        cv2.putText(
            overlay,
            label_str,
            (cx - tw // 2, cy + th // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 255, 255),
            font_thick,
            cv2.LINE_AA,
        )

    b64_str = _encode_bgr_to_b64_jpeg(overlay)
    del overlay
    return b64_str


@app.get("/", response_class=HTMLResponse)
async def serve_index() -> HTMLResponse:
    """Serve static/index.html at root `/` with `config.SOFTWARE_VERSION` injected dynamically."""
    index_path = resource_path("app/static/index.html")
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not found.")
    html_content = index_path.read_text(encoding="utf-8")
    html_content = re.sub(r"v\d+\.\d+\.\d+", f"v{config.SOFTWARE_VERSION}", html_content)
    return HTMLResponse(content=html_content)


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    """Return service health status and current software version."""
    return {"status": "OK", "version": config.SOFTWARE_VERSION}


@app.post("/api/ping")
async def client_ping(
    request: Request,
    client_id: str = Query("default", min_length=1, max_length=128),
) -> dict[str, Any]:
    """Record a heartbeat ping from an active browser window (localhost only)."""
    _require_localhost(request)
    global _HAS_EVER_CONNECTED, _LAST_CLIENT_LEFT_AT
    now = time.monotonic()
    with _STATE_LOCK:
        _ACTIVE_CLIENTS[client_id] = now
        _HAS_EVER_CONNECTED = True
        _LAST_CLIENT_LEFT_AT = None
        active_count = len(_ACTIVE_CLIENTS)
    return {"status": "OK", "client_id": client_id, "active_clients": active_count}


@app.post("/api/bye")
async def client_bye(
    request: Request,
    client_id: str = Query("default", min_length=1, max_length=128),
) -> dict[str, Any]:
    """Remove a browser client when its tab/window closes (`pagehide` beacon, localhost only)."""
    _require_localhost(request)
    global _LAST_CLIENT_LEFT_AT
    now = time.monotonic()
    with _STATE_LOCK:
        _ACTIVE_CLIENTS.pop(client_id, None)
        if _HAS_EVER_CONNECTED and len(_ACTIVE_CLIENTS) == 0 and _LAST_CLIENT_LEFT_AT is None:
            _LAST_CLIENT_LEFT_AT = now
        active_count = len(_ACTIVE_CLIENTS)
    return {"status": "OK", "client_id": client_id, "active_clients": active_count}


@app.post("/api/quit")
async def quit_application(request: Request) -> dict[str, str]:
    """Request clean application shutdown from the header Quit button (localhost only)."""
    _require_localhost(request)
    global _QUIT_REQUESTED
    with _STATE_LOCK:
        _QUIT_REQUESTED = True
        cb = _SHUTDOWN_CALLBACK
    if cb is not None:
        cb()
    return {"status": "shutting_down", "message": "You can close this window"}


@app.get("/api/logs/latest", response_class=PlainTextResponse)
async def get_latest_logs(request: Request) -> PlainTextResponse:
    """Return the last 200 lines of `user_data_dir()/logs/app.log` as plain text (localhost only)."""
    _require_localhost(request)
    log_file = user_data_dir() / "logs" / "app.log"
    if not log_file.is_file():
        return PlainTextResponse(
            content=f"Log file not created yet ({log_file}).\n",
            media_type="text/plain; charset=utf-8",
        )
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        tail_text = "\n".join(lines[-200:]) + ("\n" if lines else "")
        return PlainTextResponse(content=tail_text, media_type="text/plain; charset=utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not read log file: {exc}") from exc


@app.get("/api/calibration-sheet/{color}")
async def download_calibration_sheet(color: str) -> FileResponse:
    """Serve the printable A4 calibration sheet PDF via resource_path."""
    c = color.lower().strip()
    if c == "blue":
        pdf_path = CALIBRATION_BLUE_PDF_PATH
        filename = "calibration_sheet_a4.pdf"
    elif c == "red":
        pdf_path = CALIBRATION_RED_PDF_PATH
        filename = "calibration_sheet_a4_red.pdf"
    else:
        raise HTTPException(status_code=400, detail="Color must be 'blue' or 'red'.")
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"Calibration PDF '{filename}' not found.")
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=filename,
    )


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_images(
    files: list[UploadFile] = File(..., description="One or more full-resolution leaf images (JPG, PNG, TIFF)"),
    calibration_side_cm: float = Form(config.DEFAULT_CALIBRATION_SIDE_CM),
    calibration_color: str = Form("blue"),
    manual_px_per_cm: Optional[float] = Form(None),
    lai_mode: str = Form("none"),
    ground_area_m2: Optional[float] = Form(None),
    num_plants: Optional[float] = Form(None),
    area_per_plant_m2: Optional[float] = Form(None),
) -> AnalyzeResponse:
    """Run the full automatic Leaf Area & LAI pipeline on one or more uploaded images."""
    global _ACTIVE_ANALYZE_COUNT
    with _STATE_LOCK:
        _ACTIVE_ANALYZE_COUNT += 1
    try:
        test_delay = os.environ.get("LEAFAREA_TEST_ANALYZE_DELAY_SEC")
        if test_delay:
            try:
                delay_val = float(test_delay)
                if delay_val > 0:
                    await asyncio.sleep(delay_val)
            except ValueError:
                pass

        if not files:
            raise HTTPException(status_code=400, detail="No image files uploaded.")
        if calibration_side_cm <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Calibration square side length must be positive (got {calibration_side_cm} cm).",
            )
        cal_color = calibration_color.lower().strip()
        if cal_color not in config.SUPPORTED_CALIBRATION_COLORS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported calibration color '{calibration_color}'. Must be 'blue' or 'red'.",
            )
        if manual_px_per_cm is not None and manual_px_per_cm <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Manual scale (px/cm) must be positive (got {manual_px_per_cm}).",
            )

        mode_clean = (lai_mode or "none").lower().strip()
        try:
            if mode_clean == "mode_1" or (mode_clean == "none" and ground_area_m2 is not None):
                if ground_area_m2 is None or ground_area_m2 <= 0:
                    raise ValueError("Mode 1 ground area (m²) must be a positive number.")
            elif mode_clean == "mode_2" or (
                mode_clean == "none" and (num_plants is not None or area_per_plant_m2 is not None)
            ):
                if num_plants is None or area_per_plant_m2 is None or num_plants <= 0 or area_per_plant_m2 <= 0:
                    raise ValueError("Mode 2 requires both positive 'num_plants' and positive 'area_per_plant_m2'.")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        max_bytes = _max_upload_bytes()
        max_mb = max_bytes / (1024 * 1024)
        total_uploaded_bytes = 0

        image_results: list[ImageAnalysisOut] = []
        any_needs_manual = False
        all_warnings: list[str] = []

        for up_file in files:
            raw_bytes = await up_file.read()
            total_uploaded_bytes += len(raw_bytes)
            if total_uploaded_bytes > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Upload size ({total_uploaded_bytes / (1024 * 1024):.1f} MB) exceeds the "
                        f"maximum allowed limit of {max_mb:.0f} MB."
                    ),
                )
            fname = up_file.filename or "uploaded_image.png"
            try:
                loaded = load_image_from_bytes(raw_bytes, filename=fname)
            except ImageLoadError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            del raw_bytes

            cal = detect_calibration(
                loaded.image_bgr,
                known_side_cm=calibration_side_cm,
                color=cal_color,
                dpi=loaded.dpi,
                manual_px_per_cm=manual_px_per_cm,
            )

            active_bgr = cal.rectified_image_bgr if cal.rectified_image_bgr is not None else loaded.image_bgr
            active_h, active_w = active_bgr.shape[:2]
            orig_b64 = _encode_bgr_to_b64_jpeg(loaded.image_bgr)

            if cal.needs_manual_scale or cal.px_per_cm is None:
                any_needs_manual = True
                for w in cal.warnings:
                    all_warnings.append(f"[{fname}] {w}")
                image_results.append(
                    ImageAnalysisOut(
                        filename=fname,
                        width_px=loaded.width,
                        height_px=loaded.height,
                        dpi=loaded.dpi,
                        exif_orientation_applied=loaded.exif_orientation_applied,
                        needs_manual_scale=True,
                        px_per_cm=None,
                        px_per_cm_display=None,
                        area_px_per_cm=None,
                        area_px_per_cm_display=None,
                        edge_px_per_cm=None,
                        edge_px_per_cm_display=None,
                        calibration_method="none",
                        perspective_corrected=False,
                        extra_squares_excluded=0,
                        otsu_threshold=None,
                        otsu_threshold_display=None,
                        edge_threshold=None,
                        edge_threshold_display=None,
                        confidence="LOW",
                        warnings=cal.warnings,
                        leaves=[],
                        original_preview_b64=orig_b64,
                        overlay_image_b64=orig_b64,
                    )
                )
                continue

            seg = segment_leaves(
                active_bgr,
                cal.px_per_cm,
                cal.calibration_square_mask,
                known_side_cm=calibration_side_cm,
            )
            meas = measure_leaves(seg.leaf_mask, cal.px_per_cm)
            qual = evaluate_quality(active_w, active_h, cal, seg, meas)
            overlay_b64 = _render_verification_overlay(active_bgr, cal, seg.leaf_mask, meas)

            for w in qual.warnings:
                all_warnings.append(f"[{fname}] {w}")

            leaves_out = [
                LeafMeasurementOut(
                    leaf_id=l.leaf_id,
                    area_px=l.area_px,
                    area_cm2=l.area_cm2,
                    area_cm2_display=round(l.area_cm2, config.DISPLAY_DECIMALS_CM2),
                    length_cm=l.length_cm,
                    length_cm_display=round(l.length_cm, config.DISPLAY_DECIMALS_CM2),
                    width_cm=l.width_cm,
                    width_cm_display=round(l.width_cm, config.DISPLAY_DECIMALS_CM2),
                    perimeter_cm=round(l.perimeter_cm, config.DISPLAY_DECIMALS_CM2),
                    bbox=list(l.bbox),
                    centroid_px=[round(l.centroid_px[0], 1), round(l.centroid_px[1], 1)],
                    solidity=round(l.solidity, 4),
                    is_possible_touching=l.is_possible_touching,
                )
                for l in meas.leaves
            ]

            area_scale = cal.area_px_per_cm if cal.area_px_per_cm is not None else cal.px_per_cm
            edge_scale = cal.edge_px_per_cm
            total_extra_sq = cal.extra_squares_excluded + seg.extra_squares_removed

            image_results.append(
                ImageAnalysisOut(
                    filename=fname,
                    width_px=loaded.width,
                    height_px=loaded.height,
                    dpi=loaded.dpi,
                    exif_orientation_applied=loaded.exif_orientation_applied,
                    needs_manual_scale=False,
                    px_per_cm=cal.px_per_cm,
                    px_per_cm_display=round(cal.px_per_cm, config.DISPLAY_DECIMALS_SCALE),
                    area_px_per_cm=area_scale,
                    area_px_per_cm_display=round(area_scale, config.DISPLAY_DECIMALS_SCALE) if area_scale is not None else None,
                    edge_px_per_cm=edge_scale,
                    edge_px_per_cm_display=round(edge_scale, config.DISPLAY_DECIMALS_SCALE) if edge_scale is not None else None,
                    calibration_method=cal.method_used,
                    perspective_corrected=cal.perspective_corrected,
                    extra_squares_excluded=total_extra_sq,
                    otsu_threshold=seg.otsu_threshold,
                    otsu_threshold_display=round(seg.otsu_threshold, 2),
                    edge_threshold=seg.edge_threshold,
                    edge_threshold_display=round(seg.edge_threshold, 2),
                    leaf_count=meas.leaf_count,
                    total_area_px=meas.total_area_px,
                    total_area_cm2=meas.total_area_cm2,
                    total_area_cm2_display=round(meas.total_area_cm2, config.DISPLAY_DECIMALS_CM2),
                    mean_area_cm2=meas.mean_area_cm2,
                    mean_area_cm2_display=round(meas.mean_area_cm2, config.DISPLAY_DECIMALS_CM2),
                    std_area_cm2=meas.std_area_cm2,
                    std_area_cm2_display=round(meas.std_area_cm2, config.DISPLAY_DECIMALS_CM2),
                    uncertainty_cm2=qual.uncertainty_cm2,
                    uncertainty_cm2_display=round(qual.uncertainty_cm2, config.DISPLAY_DECIMALS_CM2),
                    uncertainty_pct=round(qual.uncertainty_pct, 2),
                    confidence=qual.confidence,
                    warnings=qual.warnings,
                    leaves=leaves_out,
                    original_preview_b64=orig_b64,
                    overlay_image_b64=overlay_b64,
                )
            )

        total_leaf_count = sum(r.leaf_count for r in image_results)
        per_image_areas = [r.total_area_cm2 for r in image_results]
        total_uncertainty_cm2 = float(np.sum([r.uncertainty_cm2 for r in image_results], dtype=np.float64))

        try:
            lai_res = calculate_lai(
                leaf_areas_cm2=per_image_areas,
                ground_area_m2=ground_area_m2 if mode_clean in {"mode_1", "none"} else None,
                num_plants=num_plants if mode_clean in {"mode_2", "none"} else None,
                area_per_plant_m2=area_per_plant_m2 if mode_clean in {"mode_2", "none"} else None,
                uncertainty_cm2=total_uncertainty_cm2,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        all_leaf_areas = [l.area_cm2 for r in image_results for l in r.leaves]
        mean_batch_leaf_cm2 = float(np.mean(all_leaf_areas, dtype=np.float64)) if all_leaf_areas else 0.0

        conf_ranks = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        inv_ranks = {0: "LOW", 1: "MEDIUM", 2: "HIGH"}
        min_rank = min((conf_ranks.get(r.confidence, 0) for r in image_results), default=0)
        overall_conf = inv_ranks[min_rank]

        batch_summary = BatchSummaryOut(
            image_count=len(image_results),
            total_leaf_count=total_leaf_count,
            total_leaf_area_cm2=lai_res.total_leaf_area_cm2,
            total_leaf_area_cm2_display=round(lai_res.total_leaf_area_cm2, config.DISPLAY_DECIMALS_CM2),
            total_leaf_area_m2=lai_res.total_leaf_area_m2,
            mean_leaf_area_cm2=mean_batch_leaf_cm2,
            mean_leaf_area_cm2_display=round(mean_batch_leaf_cm2, config.DISPLAY_DECIMALS_CM2),
            total_uncertainty_cm2=total_uncertainty_cm2,
            total_uncertainty_cm2_display=round(total_uncertainty_cm2, config.DISPLAY_DECIMALS_CM2),
            ground_area_m2=lai_res.ground_area_m2,
            lai=lai_res.lai,
            lai_display=round(lai_res.lai, config.DISPLAY_DECIMALS_LAI) if lai_res.lai is not None else None,
            lai_uncertainty=lai_res.lai_uncertainty,
            lai_uncertainty_display=(
                round(lai_res.lai_uncertainty, config.DISPLAY_DECIMALS_LAI)
                if lai_res.lai_uncertainty is not None
                else None
            ),
            lai_mode=lai_res.mode_used,
            overall_confidence=overall_conf,
            needs_manual_scale=any_needs_manual,
            all_warnings=all_warnings,
        )

        session_id = uuid.uuid4().hex
        timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        response_obj = AnalyzeResponse(
            session_id=session_id,
            software_version=f"{config.SOFTWARE_NAME} v{config.SOFTWARE_VERSION}",
            timestamp_utc=timestamp_utc,
            needs_manual_scale=any_needs_manual,
            images=image_results,
            batch_summary=batch_summary,
        )

        session_dict = response_obj.dict()
        for img_d in session_dict["images"]:
            img_d.pop("original_preview_b64", None)
            img_d.pop("overlay_image_b64", None)
        _SESSIONS[session_id] = session_dict

        return response_obj
    finally:
        with _STATE_LOCK:
            _ACTIVE_ANALYZE_COUNT = max(0, _ACTIVE_ANALYZE_COUNT - 1)


@app.get("/api/export/{session_id}")
async def export_results(
    session_id: str,
    format: str = Query("csv", regex="^(csv|xlsx)$"),
) -> Response:
    """Download analysis session results in CSV or XLSX format."""
    if session_id not in _SESSIONS:
        raise HTTPException(status_code=404, detail=f"Analysis session '{session_id}' not found.")

    session_data = _SESSIONS[session_id]
    fmt = format.lower().strip()
    if fmt == "csv":
        csv_bytes = export_session_to_csv(session_data)
        return Response(
            content=csv_bytes,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="leaf_area_results_{session_id[:8]}.csv"'},
        )
    if fmt == "xlsx":
        xlsx_bytes = export_session_to_xlsx(session_data)
        return Response(
            content=xlsx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="leaf_area_results_{session_id[:8]}.xlsx"'},
        )
    raise HTTPException(status_code=400, detail="Unsupported export format. Use 'csv' or 'xlsx'.")
