"""Leaf Area Index (LAI) calculation (Phase 6) supporting single and batch samples in Mode 1 and Mode 2."""

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from app import config


@dataclass(frozen=True)
class LAIResult:
    """Result of Leaf Area Index calculation."""

    total_leaf_area_cm2: float
    total_leaf_area_m2: float
    ground_area_m2: Optional[float]
    ground_area_cm2: Optional[float]
    lai: Optional[float]
    lai_uncertainty: Optional[float]
    mode_used: str  # "mode_1", "mode_2", or "none"


def calculate_lai(
    leaf_areas_cm2: float | Sequence[float],
    ground_area_m2: Optional[float] = None,
    num_plants: Optional[float] = None,
    area_per_plant_m2: Optional[float] = None,
    uncertainty_cm2: float = 0.0,
) -> LAIResult:
    """Calculate Leaf Area Index (LAI = total_leaf_area_m2 / ground_area_m2).

    Supports two ground-area input modes:
    - Mode 1: Direct `ground_area_m2` (m^2).
    - Mode 2: `num_plants` * `area_per_plant_m2` (m^2).
    Also supports batch summation when `leaf_areas_cm2` is a sequence of per-image totals.
    """
    if isinstance(leaf_areas_cm2, (int, float, np.floating)):
        total_cm2 = float(np.float64(leaf_areas_cm2))
    else:
        total_cm2 = float(np.sum(np.asarray(list(leaf_areas_cm2), dtype=np.float64)))

    if total_cm2 < 0:
        raise ValueError(f"Total leaf area cannot be negative, got {total_cm2} cm².")

    total_m2 = float(np.float64(total_cm2) / np.float64(config.CM2_PER_M2))

    # Determine ground area mode
    resolved_ground_m2: Optional[float] = None
    mode_used = "none"

    if ground_area_m2 is not None:
        if ground_area_m2 <= 0:
            raise ValueError(f"Ground area must be a positive number, got {ground_area_m2} m².")
        resolved_ground_m2 = float(np.float64(ground_area_m2))
        mode_used = "mode_1"
    elif num_plants is not None or area_per_plant_m2 is not None:
        if num_plants is None or area_per_plant_m2 is None:
            raise ValueError(
                "Mode 2 requires both 'num_plants' and 'area_per_plant_m2' to be provided."
            )
        if num_plants <= 0 or area_per_plant_m2 <= 0:
            raise ValueError(
                f"Both 'num_plants' ({num_plants}) and 'area_per_plant_m2' ({area_per_plant_m2}) must be positive."
            )
        resolved_ground_m2 = float(np.float64(num_plants) * np.float64(area_per_plant_m2))
        mode_used = "mode_2"

    if resolved_ground_m2 is None:
        return LAIResult(
            total_leaf_area_cm2=total_cm2,
            total_leaf_area_m2=total_m2,
            ground_area_m2=None,
            ground_area_cm2=None,
            lai=None,
            lai_uncertainty=None,
            mode_used="none",
        )

    resolved_ground_cm2 = float(np.float64(resolved_ground_m2) * np.float64(config.CM2_PER_M2))
    lai_val = float(np.float64(total_m2) / np.float64(resolved_ground_m2))
    lai_unc = (
        float((np.float64(uncertainty_cm2) / np.float64(config.CM2_PER_M2)) / np.float64(resolved_ground_m2))
        if uncertainty_cm2 >= 0
        else 0.0
    )

    return LAIResult(
        total_leaf_area_cm2=total_cm2,
        total_leaf_area_m2=total_m2,
        ground_area_m2=resolved_ground_m2,
        ground_area_cm2=resolved_ground_cm2,
        lai=lai_val,
        lai_uncertainty=lai_unc,
        mode_used=mode_used,
    )
