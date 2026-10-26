"""Compare ImageJ manual measurements against LeafArea & LAI Analyzer automated measurements."""

import csv
from pathlib import Path
import sys

import numpy as np


def compare_validation_csv(csv_path: Path) -> dict[str, float]:
    """Read validation CSV and compute mean difference, standard deviation, and max difference."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Validation CSV not found: {csv_path}")

    rows = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = (row.get("sample_id") or "").strip()
            if not sid:
                continue
            ij_str = (row.get("imagej_total_area_cm2") or "").strip()
            app_str = (row.get("app_total_area_cm2") or "").strip()
            if not ij_str or not app_str:
                continue
            ij_val = float(ij_str)
            app_val = float(app_str)
            diff_cm2 = app_val - ij_val
            diff_pct = (diff_cm2 / ij_val * 100.0) if ij_val != 0 else 0.0
            rows.append({
                "sample_id": sid,
                "imagej_cm2": ij_val,
                "app_cm2": app_val,
                "diff_cm2": diff_cm2,
                "diff_pct": diff_pct,
                "notes": (row.get("notes") or "").strip(),
            })

    if not rows:
        print("No valid measurement rows found in CSV.")
        return {"count": 0, "mean_diff_cm2": 0.0, "std_diff_cm2": 0.0, "max_abs_diff_cm2": 0.0}

    diffs_cm2 = np.array([r["diff_cm2"] for r in rows], dtype=np.float64)
    diffs_pct = np.array([r["diff_pct"] for r in rows], dtype=np.float64)

    mean_cm2 = float(np.mean(diffs_cm2))
    std_cm2 = float(np.std(diffs_cm2, ddof=0))
    max_abs_cm2 = float(np.max(np.abs(diffs_cm2)))

    mean_pct = float(np.mean(diffs_pct))
    std_pct = float(np.std(diffs_pct, ddof=0))
    max_abs_pct = float(np.max(np.abs(diffs_pct)))

    print(f"{'Sample ID':<22} | {'ImageJ (cm²)':>12} | {'App (cm²)':>12} | {'Diff (cm²)':>11} | {'Diff (%)':>9}")
    print("-" * 76)
    for r in rows:
        print(
            f"{r['sample_id']:<22} | {r['imagej_cm2']:12.4f} | {r['app_cm2']:12.4f} | "
            f"{r['diff_cm2']:+11.4f} | {r['diff_pct']:+8.3f}%"
        )
    print("-" * 76)
    print(f"Samples compared       : {len(rows)}")
    print(f"Mean difference        : {mean_cm2:+.4f} cm² ({mean_pct:+.3f}%)")
    print(f"Standard deviation     : {std_cm2:.4f} cm² ({std_pct:.3f}%)")
    print(f"Max absolute difference: {max_abs_cm2:.4f} cm² ({max_abs_pct:.3f}%)")

    return {
        "count": float(len(rows)),
        "mean_diff_cm2": mean_cm2,
        "std_diff_cm2": std_cm2,
        "max_abs_diff_cm2": max_abs_cm2,
        "mean_diff_pct": mean_pct,
        "std_diff_pct": std_pct,
        "max_abs_diff_pct": max_abs_pct,
    }


if __name__ == "__main__":
    default_csv = Path(__file__).resolve().parent / "validation_template.csv"
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else default_csv
    compare_validation_csv(target)
