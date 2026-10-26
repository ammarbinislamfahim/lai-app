"""CSV and XLSX export module (Phase 8, Item 3, Item D, Issue E) with per-leaf rows, TOTAL row, and dual scale reporting."""

from datetime import datetime, timezone
import io
from typing import Any

import pandas as pd

from app import config


def _build_export_rows(session_data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build summary rows (per image + batch sample total) and per-leaf detail rows (with a final TOTAL row)."""
    timestamp_iso = session_data.get("timestamp_utc") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    software_version = f"{config.SOFTWARE_NAME} v{config.SOFTWARE_VERSION}"
    batch_summary = session_data.get("batch_summary", {})
    batch_lai = batch_summary.get("lai")
    batch_ground_m2 = batch_summary.get("ground_area_m2")
    batch_mode = batch_summary.get("lai_mode", "none")

    summary_rows: list[dict[str, Any]] = []
    leaf_rows: list[dict[str, Any]] = []

    total_leaf_area_cm2 = 0.0
    total_leaf_area_px = 0
    total_leaf_perimeter_cm = 0.0
    total_leaf_count = 0

    for img_res in session_data.get("images", []):
        fname = img_res.get("filename", "")
        px_per_cm = img_res.get("px_per_cm")
        area_px_per_cm = img_res.get("area_px_per_cm", px_per_cm)
        edge_px_per_cm = img_res.get("edge_px_per_cm")
        method = img_res.get("calibration_method", "")
        otsu_thr = img_res.get("otsu_threshold")
        edge_thr = img_res.get("edge_threshold")
        conf = img_res.get("confidence", "")
        warnings_str = "; ".join(img_res.get("warnings", [])) or "None"

        summary_rows.append({
            "Record_Type": "Image_Summary",
            "Filename": fname,
            "Software_Version": software_version,
            "Date_Time_UTC": timestamp_iso,
            "Width_px": img_res.get("width_px"),
            "Height_px": img_res.get("height_px"),
            "Scale_px_per_cm": round(px_per_cm, 4) if px_per_cm is not None else None,
            "Scale_Area_px_per_cm": round(area_px_per_cm, 4) if area_px_per_cm is not None else None,
            "Scale_Edge_px_per_cm": round(edge_px_per_cm, 4) if edge_px_per_cm is not None else None,
            "Calibration_Method": method,
            "Otsu_Threshold": round(otsu_thr, 4) if otsu_thr is not None else None,
            "Edge_Threshold": round(edge_thr, 4) if edge_thr is not None else None,
            "Leaf_Count": img_res.get("leaf_count", 0),
            "Total_Leaf_Area_cm2": round(img_res.get("total_area_cm2", 0.0), 4),
            "Uncertainty_pm_cm2": round(img_res.get("uncertainty_cm2", 0.0), 4),
            "Mean_Leaf_Area_cm2": round(img_res.get("mean_area_cm2", 0.0), 4),
            "Std_Leaf_Area_cm2": round(img_res.get("std_area_cm2", 0.0), 4),
            "Ground_Area_m2": batch_ground_m2,
            "LAI_Mode": batch_mode,
            "Sample_LAI": round(batch_lai, 5) if batch_lai is not None else None,
            "Confidence": conf,
            "Warnings": warnings_str,
        })

        for leaf in img_res.get("leaves", []):
            l_area_cm2 = float(leaf.get("area_cm2", 0.0))
            l_area_px = int(leaf.get("area_px", 0))
            l_peri_cm = float(leaf.get("perimeter_cm", 0.0))
            total_leaf_area_cm2 += l_area_cm2
            total_leaf_area_px += l_area_px
            total_leaf_perimeter_cm += l_peri_cm
            total_leaf_count += 1

            leaf_rows.append({
                "Filename": fname,
                "Leaf_Number": leaf.get("leaf_id"),
                "Area_cm2": round(l_area_cm2, 4),
                "Area_px": l_area_px,
                "Length_cm": round(float(leaf.get("length_cm", 0.0)), 4),
                "Width_cm": round(float(leaf.get("width_cm", 0.0)), 4),
                "Perimeter_cm": round(l_peri_cm, 4),
                "Solidity": round(float(leaf.get("solidity", 0.0)), 4),
                "Possible_Touching": bool(leaf.get("is_possible_touching", False)),
                "Scale_px_per_cm": round(px_per_cm, 4) if px_per_cm is not None else None,
                "Scale_Area_px_per_cm": round(area_px_per_cm, 4) if area_px_per_cm is not None else None,
                "Scale_Edge_px_per_cm": round(edge_px_per_cm, 4) if edge_px_per_cm is not None else None,
                "Calibration_Method": method,
                "Otsu_Threshold": round(otsu_thr, 4) if otsu_thr is not None else None,
                "Edge_Threshold": round(edge_thr, 4) if edge_thr is not None else None,
                "Sample_LAI": round(batch_lai, 5) if batch_lai is not None else None,
                "Confidence": conf,
                "Warnings": warnings_str,
                "Software_Version": software_version,
                "Date_Time_UTC": timestamp_iso,
            })

    # Item D: Append a final TOTAL row to leaf_rows so the per-leaf table always ends with a TOTAL summary row
    images_list = session_data.get("images", [])
    single_img = images_list[0] if len(images_list) == 1 else None
    leaf_rows.append({
        "Filename": single_img.get("filename", "TOTAL") if single_img else "ALL_IMAGES_TOTAL",
        "Leaf_Number": "TOTAL",
        "Area_cm2": round(float(batch_summary.get("total_leaf_area_cm2", total_leaf_area_cm2)), 4),
        "Area_px": total_leaf_area_px,
        "Length_cm": None,
        "Width_cm": None,
        "Perimeter_cm": round(total_leaf_perimeter_cm, 4),
        "Solidity": None,
        "Possible_Touching": False,
        "Scale_px_per_cm": (
            round(single_img["px_per_cm"], 4)
            if single_img and single_img.get("px_per_cm") is not None
            else None
        ),
        "Scale_Area_px_per_cm": (
            round(single_img.get("area_px_per_cm") or single_img["px_per_cm"], 4)
            if single_img and single_img.get("px_per_cm") is not None
            else None
        ),
        "Scale_Edge_px_per_cm": (
            round(single_img["edge_px_per_cm"], 4)
            if single_img and single_img.get("edge_px_per_cm") is not None
            else None
        ),
        "Calibration_Method": single_img.get("calibration_method", "batch_aggregate") if single_img else "batch_aggregate",
        "Otsu_Threshold": (
            round(single_img["otsu_threshold"], 4)
            if single_img and single_img.get("otsu_threshold") is not None
            else None
        ),
        "Edge_Threshold": (
            round(single_img["edge_threshold"], 4)
            if single_img and single_img.get("edge_threshold") is not None
            else None
        ),
        "Sample_LAI": round(batch_lai, 5) if batch_lai is not None else None,
        "Confidence": batch_summary.get("overall_confidence", ""),
        "Warnings": "; ".join(batch_summary.get("all_warnings", [])) or "None",
        "Software_Version": software_version,
        "Date_Time_UTC": timestamp_iso,
    })

    summary_rows.append({
        "Record_Type": "Batch_Sample_Total",
        "Filename": "ALL_IMAGES_COMBINED",
        "Software_Version": software_version,
        "Date_Time_UTC": timestamp_iso,
        "Width_px": None,
        "Height_px": None,
        "Scale_px_per_cm": None,
        "Scale_Area_px_per_cm": None,
        "Scale_Edge_px_per_cm": None,
        "Calibration_Method": "batch_aggregate",
        "Otsu_Threshold": None,
        "Edge_Threshold": None,
        "Leaf_Count": batch_summary.get("total_leaf_count", total_leaf_count),
        "Total_Leaf_Area_cm2": round(batch_summary.get("total_leaf_area_cm2", total_leaf_area_cm2), 4),
        "Uncertainty_pm_cm2": round(batch_summary.get("total_uncertainty_cm2", 0.0), 4),
        "Mean_Leaf_Area_cm2": round(batch_summary.get("mean_leaf_area_cm2", 0.0), 4),
        "Std_Leaf_Area_cm2": None,
        "Ground_Area_m2": batch_ground_m2,
        "LAI_Mode": batch_mode,
        "Sample_LAI": round(batch_lai, 5) if batch_lai is not None else None,
        "Confidence": batch_summary.get("overall_confidence", ""),
        "Warnings": "; ".join(batch_summary.get("all_warnings", [])) or "None",
    })

    return summary_rows, leaf_rows


def export_session_to_csv(session_data: dict[str, Any]) -> bytes:
    """Export session summary and per-leaf data to a single comprehensive UTF-8 CSV byte stream."""
    summary_rows, leaf_rows = _build_export_rows(session_data)
    buf = io.StringIO()
    buf.write("# SECTION 1: IMAGE & SAMPLE SUMMARY\n")
    df_sum = pd.DataFrame(summary_rows)
    df_sum.to_csv(buf, index=False)
    buf.write("\n# SECTION 2: PER-LEAF MEASUREMENTS\n")
    df_leaves = pd.DataFrame(leaf_rows)
    df_leaves.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def export_session_to_xlsx(session_data: dict[str, Any]) -> bytes:
    """Export per-leaf measurements (with TOTAL row) and session summary to an XLSX workbook."""
    summary_rows, leaf_rows = _build_export_rows(session_data)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_leaves = pd.DataFrame(leaf_rows)
        # Put Per_Leaf_Data as the first sheet so opening the workbook immediately shows one row per leaf + TOTAL row
        df_leaves.to_excel(writer, sheet_name="Per_Leaf_Data", index=False)

        df_sum = pd.DataFrame(summary_rows)
        df_sum.to_excel(writer, sheet_name="Sample_Summary", index=False)

        for sheet_name, ws in writer.sheets.items():
            ws.views.sheetView[0].showGridLines = True
            for col in ws.columns:
                max_len = max((len(str(cell.value or "")) for cell in col), default=12)
                col_letter = col[0].column_letter
                ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 55)

    return buf.getvalue()
