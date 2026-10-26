"""Phase 8, 9, 10, Items A–E, Desktop Packaging Phase 2, and UI Redesign v1.5.1 API & static tests."""

import io
import json
import os
from pathlib import Path
import re
import sys

import numpy as np
import openpyxl
from PIL import Image
import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.paths import resource_path, user_data_dir
from tests.make_synthetic import PAPER_WHITE_BGR, generate_all_synthetic_images

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_images"
STATIC_DIR = Path(__file__).resolve().parent.parent / "app" / "static"
client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def ensure_synthetic_images() -> None:
    if not (SAMPLE_DIR / "10_extra_calib_square.json").exists():
        generate_all_synthetic_images(SAMPLE_DIR, include_large_suite_on_disk=True)


def test_static_files_have_no_external_urls() -> None:
    """Hard Rule 1: Fail if any file in app/static contains http:// or https:// other than
    127.0.0.1, localhost, standard W3C SVG namespace (http://www.w3.org/2000/svg), or help links.
    """
    url_pattern = re.compile(r"https?://[^\s\"'<>)\]]+")
    allowed_prefixes = (
        "http://127.0.0.1",
        "https://127.0.0.1",
        "http://localhost",
        "https://localhost",
        "http://www.w3.org/2000/svg",
        "https://www.w3.org/2000/svg",
    )

    text_extensions = {".html", ".css", ".js", ".svg", ".json", ".txt"}
    violations: list[str] = []

    for path in sorted(STATIC_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in text_extensions:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for match in url_pattern.finditer(content):
            url = match.group(0)
            if not any(url.startswith(prefix) for prefix in allowed_prefixes):
                violations.append(f"{path.relative_to(STATIC_DIR)}: {url}")

    assert not violations, f"External URLs found in app/static: {violations}"


def test_health_and_root_index_and_item_a_pdfs() -> None:
    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "OK"
    assert r_health.json()["version"] == config.SOFTWARE_VERSION

    r_root = client.get("/")
    assert r_root.status_code == 200
    assert "LeafArea &amp; LAI Analyzer" in r_root.text
    assert "Leaf Area &amp; LAI Analyzer" in r_root.text
    assert "Measure leaf area and LAI from a photo in seconds." in r_root.text
    assert "Drop your leaf photos here" in r_root.text
    assert "How to photograph" in r_root.text
    assert "Try a sample photo" in r_root.text
    assert 'name="theme-color"' in r_root.text
    assert "/static/favicon.svg" in r_root.text
    assert f"v{config.SOFTWARE_VERSION}" in r_root.text
    assert "calibration_sheet_a4.pdf" in r_root.text
    assert "calibration_sheet_a4_red.pdf" in r_root.text
    assert "Use only one calibration square per photo, and keep the other sheet's square out of the frame." in r_root.text

    # Favicon and built-in sample are served properly
    r_fav = client.get("/static/favicon.svg")
    assert r_fav.status_code == 200
    assert "<svg" in r_fav.text

    r_sample = client.get("/static/samples/01_clean_standard.png")
    assert r_sample.status_code == 200
    assert r_sample.content.startswith(b"\x89PNG")

    # Item A: Blue PDF contains ONLY the blue square, instruction text, and 10.00 cm bar
    r_pdf_blue = client.get("/static/calibration_sheet_a4.pdf")
    assert r_pdf_blue.status_code == 200
    assert r_pdf_blue.content.startswith(b"%PDF-1.4")
    assert b"0.060 0.240 0.820 rg" in r_pdf_blue.content
    assert b"0.840 0.100 0.100 rg" not in r_pdf_blue.content
    assert b"10.00 cm Verification Scale Bar" in r_pdf_blue.content

    # Item A: Red PDF contains ONLY the red square, instruction text, and 10.00 cm bar
    r_pdf_red = client.get("/static/calibration_sheet_a4_red.pdf")
    assert r_pdf_red.status_code == 200
    assert r_pdf_red.content.startswith(b"%PDF-1.4")
    assert b"0.840 0.100 0.100 rg" in r_pdf_red.content
    assert b"0.060 0.240 0.820 rg" not in r_pdf_red.content
    assert b"10.00 cm Verification Scale Bar" in r_pdf_red.content


def test_api_analyze_and_exports_csv_xlsx() -> None:
    img_path = SAMPLE_DIR / "01_clean_standard.png"
    meta = json.loads((SAMPLE_DIR / "01_clean_standard.json").read_text(encoding="utf-8"))

    with img_path.open("rb") as f:
        resp = client.post(
            "/api/analyze",
            files=[("files", ("01_clean_standard.png", f, "image/png"))],
            data={
                "calibration_side_cm": "2.0",
                "calibration_color": "blue",
                "lai_mode": "mode_1",
                "ground_area_m2": "0.02",
            },
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["needs_manual_scale"] is False
    assert len(data["images"]) == 1

    img_out = data["images"][0]
    assert img_out["width_px"] == 3000
    assert img_out["height_px"] == 2000
    assert img_out["calibration_method"] == "calibration_square"
    assert abs(img_out["px_per_cm"] - 100.0) <= 0.5
    assert img_out["area_px_per_cm"] is not None
    assert img_out["edge_px_per_cm"] is not None
    assert img_out["otsu_threshold"] is not None
    assert img_out["edge_threshold"] is not None
    assert abs(img_out["total_area_cm2"] - meta["true_area_cm2"]) / meta["true_area_cm2"] <= 0.005
    assert img_out["overlay_image_b64"].startswith("data:image/jpeg;base64,")

    expected_lai = (img_out["total_area_cm2"] / 10000.0) / 0.02
    assert data["batch_summary"]["lai"] == pytest.approx(expected_lai, rel=1e-4)

    session_id = data["session_id"]

    # Test CSV export (must include Edge_Threshold, dual scale columns, and TOTAL row)
    r_csv = client.get(f"/api/export/{session_id}?format=csv")
    assert r_csv.status_code == 200
    csv_text = r_csv.content.decode("utf-8")
    assert "01_clean_standard.png" in csv_text
    assert "calibration_square" in csv_text
    assert "Edge_Threshold" in csv_text
    assert "Scale_Area_px_per_cm" in csv_text
    assert "Scale_Edge_px_per_cm" in csv_text
    assert "TOTAL" in csv_text
    assert f"v{config.SOFTWARE_VERSION}" in csv_text

    # Test XLSX export (Item D: one row per detected leaf + final TOTAL row)
    r_xlsx = client.get(f"/api/export/{session_id}?format=xlsx")
    assert r_xlsx.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r_xlsx.content))
    assert "Sample_Summary" in wb.sheetnames
    assert "Per_Leaf_Data" in wb.sheetnames
    ws_leaves = wb["Per_Leaf_Data"]
    headers = [cell.value for cell in ws_leaves[1]]
    assert "Edge_Threshold" in headers
    assert "Scale_Area_px_per_cm" in headers
    assert "Scale_Edge_px_per_cm" in headers
    # 1 header row + 4 leaf rows + 1 TOTAL row = 6 rows
    assert ws_leaves.max_row == 6
    leaf_num_col = headers.index("Leaf_Number") + 1
    area_col = headers.index("Area_cm2") + 1
    assert ws_leaves.cell(row=6, column=leaf_num_col).value == "TOTAL"
    assert float(ws_leaves.cell(row=6, column=area_col).value) == pytest.approx(img_out["total_area_cm2"], abs=1e-3)


def test_api_failure_cases_and_manual_scale_flow() -> None:
    arr = np.full((1000, 1000, 3), PAPER_WHITE_BGR, dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    raw_no_calib = buf.getvalue()

    resp_missing = client.post(
        "/api/analyze",
        files=[("files", ("no_calib.png", io.BytesIO(raw_no_calib), "image/png"))],
        data={"calibration_side_cm": "2.0", "calibration_color": "blue"},
    )
    assert resp_missing.status_code == 200
    d_missing = resp_missing.json()
    assert d_missing["needs_manual_scale"] is True
    assert d_missing["images"][0]["px_per_cm"] is None

    resp_manual = client.post(
        "/api/analyze",
        files=[("files", ("no_calib.png", io.BytesIO(raw_no_calib), "image/png"))],
        data={
            "calibration_side_cm": "2.0",
            "calibration_color": "blue",
            "manual_px_per_cm": "100.0",
        },
    )
    assert resp_manual.status_code == 200
    d_manual = resp_manual.json()
    assert d_manual["needs_manual_scale"] is False
    assert d_manual["images"][0]["calibration_method"] == "manual"
    assert d_manual["images"][0]["confidence"] == "LOW"

    resp_bad = client.post(
        "/api/analyze",
        files=[("files", ("bad.png", io.BytesIO(b"not an image"), "image/png"))],
    )
    assert resp_bad.status_code == 400

    arr_tiny = np.full((400, 400, 3), 255, dtype=np.uint8)
    buf_tiny = io.BytesIO()
    Image.fromarray(arr_tiny).save(buf_tiny, format="PNG")
    resp_tiny = client.post(
        "/api/analyze",
        files=[("files", ("tiny.png", io.BytesIO(buf_tiny.getvalue()), "image/png"))],
    )
    assert resp_tiny.status_code == 400
    assert "too small" in resp_tiny.json()["detail"]


def test_phase2_paths_and_upload_size_limit_413(tmp_path: Path) -> None:
    """Phase 2: Verify resource_path (normal and frozen _MEIPASS), user_data_dir, and HTTP 413 upload limit."""
    static_pdf = resource_path("app/static/calibration_sheet_a4.pdf")
    assert static_pdf.is_file()
    sample_png = resource_path("sample_images/01_clean_standard.png")
    assert sample_png.is_file()

    # Frozen PyInstaller _MEIPASS simulation
    fake_meipass = tmp_path / "_internal"
    (fake_meipass / "app" / "static").mkdir(parents=True)
    fake_file = fake_meipass / "app" / "static" / "test.txt"
    fake_file.write_text("frozen_ok", encoding="utf-8")
    try:
        setattr(sys, "frozen", True)
        setattr(sys, "_MEIPASS", str(fake_meipass))
        assert resource_path("app/static/test.txt").read_text(encoding="utf-8") == "frozen_ok"
    finally:
        if hasattr(sys, "frozen"):
            delattr(sys, "frozen")
        if hasattr(sys, "_MEIPASS"):
            delattr(sys, "_MEIPASS")

    # user_data_dir creation and override
    custom_data_dir = tmp_path / "user_data"
    try:
        os.environ["LEAFAREA_USER_DATA_DIR"] = str(custom_data_dir)
        resolved_dir = user_data_dir()
        assert resolved_dir == custom_data_dir.resolve()
        assert resolved_dir.is_dir()
    finally:
        os.environ.pop("LEAFAREA_USER_DATA_DIR", None)

    # HTTP 413 when upload exceeds configured limit
    try:
        os.environ["LEAFAREA_MAX_UPLOAD_MB"] = "0.001"  # ~1 KB limit for test
        big_payload = b"x" * 8192
        resp_413 = client.post(
            "/api/analyze",
            files=[("files", ("oversized.png", io.BytesIO(big_payload), "image/png"))],
            data={"calibration_side_cm": "2.0", "calibration_color": "blue"},
        )
        assert resp_413.status_code == 413, f"Expected 413, got {resp_413.status_code}: {resp_413.text}"
        assert "exceeds the maximum allowed limit" in resp_413.json()["detail"]
    finally:
        os.environ.pop("LEAFAREA_MAX_UPLOAD_MB", None)
