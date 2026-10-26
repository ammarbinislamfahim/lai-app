# Step-by-Step ImageJ Validation Guide

This guide explains how to measure the exact same detached leaf images in **ImageJ / Fiji** and compare the results against the **LeafArea & LAI Analyzer** web app using `validation_template.csv` and `compare.py`.

---

## 1. Measure the Image in ImageJ / Fiji

1. **Open the Full-Resolution Image:**
   - Launch ImageJ or Fiji and select **`File -> Open...`** to load the original, unresized leaf image (`.png`, `.tif`, or `.jpg`).
2. **Set the Physical Scale from the Calibration Square:**
   - Select the **Straight Line** tool from the ImageJ toolbar.
   - Zoom in on the **blue (or red) calibration square** and draw a line along one of its four edges from corner to corner.
   - Open **`Analyze -> Set Scale...`**:
     - **Distance in pixels:** (pre-filled automatically from your line)
     - **Known distance:** `2.00` (or your configured square side length)
     - **Unit of length:** `cm`
     - Leave **Global** unchecked (unless all images in your batch were scanned at the exact same flatbed DPI). Click **OK**.
3. **Exclude the Calibration Square:**
   - Select the **Rectangle** or **Polygon** selection tool, outline the calibration square, and press **`Delete` / `Backspace`** (making sure the background fill color is white: `Edit -> Options -> Colors...`, Background = `White`) so the calibration square is not counted as a leaf.
4. **Segment Leaves from the White Background:**
   - **Option A — Color Threshold (recommended for green + yellow/brown leaves):**
     - Open **`Image -> Adjust -> Color Threshold...`**.
     - Set **Thresholding method** to `Otsu` and **Color space** to `Lab` (or `HSB`).
     - Adjust the `L*` (brightness) pass/stop slider so the white paper background is excluded and all leaves are highlighted in red. Click **Select**, then **`Edit -> Clear Outside`** and **`Image -> Type -> 8-bit`**, followed by **`Image -> Adjust -> Threshold... -> Apply`** to create a binary mask.
   - **Option B — 8-bit Otsu Threshold (for high-contrast green leaves):**
     - Select **`Image -> Type -> 8-bit`**.
     - Open **`Image -> Adjust -> Threshold...`**, choose **`Otsu`** from the dropdown, check **Dark background** only if leaves appear bright, and click **Apply**.
5. **Measure Leaf Area with Analyze Particles:**
   - First configure measurements: **`Analyze -> Set Measurements...`** and check **Area**, **Perimeter**, and **Bounding rectangle**.
   - Open **`Analyze -> Analyze Particles...`**:
     - **Size (cm^2):** `0.05-Infinity` (matches `MIN_SPECK_AREA_CM2 = 0.05` in `app/config.py` so dust specks under $0.05\text{ cm}^2$ are ignored).
     - **Circularity:** `0.00-1.00`.
     - **Show:** `Outlines` (to visually verify leaf numbering and edges).
     - Check **Display results**, **Summarize**, and **Exclude on edges** (matches the app's border-clipping exclusion rule).
     - Do **not** check **Include holes** if your leaves have real insect-feeding holes that must be excluded from leaf tissue area.
   - Click **OK**. Read the **`Total Area`** column in the **Summary** window (in $\text{cm}^2$).

---

## 2. Record and Compare Results (`validation_template.csv` & `compare.py`)

1. Open `validation/validation_template.csv` in a spreadsheet editor or text editor.
2. For each image, enter:
   - `sample_id`: Image filename or sample identifier.
   - `imagej_total_area_cm2`: The `Total Area` ($\text{cm}^2$) reported by ImageJ's Summary table.
   - `app_total_area_cm2`: The `Total Leaf Area (cm²)` reported by the LeafArea & LAI Analyzer web app.
   - (`difference_cm2` and `difference_percent` can be left blank or pre-filled; `compare.py` computes them automatically from `app_total_area_cm2 - imagej_total_area_cm2`).
3. Run the comparison script from the `lai-app/` directory:
   ```bash
   python3 validation/compare.py validation/validation_template.csv
   ```
4. The script prints a per-sample comparison table along with the **mean difference** ($\text{cm}^2$ and $\%$), **standard deviation**, and **maximum absolute difference**.
