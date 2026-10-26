# LeafArea & LAI Analyzer (v1.5.6) — User Guide for Researchers

Welcome to **LeafArea & LAI Analyzer v1.5.6**. This click-to-open desktop program measures one-sided leaf surface area ($\text{cm}^2$) and calculates the **Leaf Area Index ($\text{LAI}$)** automatically from photos or flatbed scans—with no terminal window, no manual clicking, no thresholding, and no ImageJ scale calibration required.

All processing runs **100% offline on your own computer** (`127.0.0.1`). No Python installation is required, no internet connection is needed, and your research images never leave your machine.

---

## 1. How to Verify Your Download (SHA-256 Checksum)

Before installing, you can verify that your downloaded file is intact and unaltered by comparing its SHA-256 hash with `SHA256SUMS.txt` on the release page:

- **Windows (PowerShell):**
  ```powershell
  Get-FileHash .\LeafAreaAnalyzer-Setup-v1.5.6.exe -Algorithm SHA256
  ```
  *(Or in Command Prompt: `CertUtil -hashfile LeafAreaAnalyzer-Setup-v1.5.6.exe SHA256`)*

- **Linux (Terminal):**
  ```bash
  sha256sum -c LeafAreaAnalyzer-v1.5.6-linux-x86_64.tar.gz.sha256
  ```

---

## 2. How to Install and Open the Program

### Windows (Option A: Standard Installer — Recommended)
1. Double-click **`LeafAreaAnalyzer-Setup-v1.5.6.exe`**.
2. **Note on the "Windows protected your PC" message:**
   Because this is free scientific research software distributed without a paid commercial code-signing certificate, Windows Defender SmartScreen may display a blue dialog saying *"Windows protected your PC"*.
   - Click **"More info"** (underneath the text).
   - Click the **"Run anyway"** button that appears at the bottom.
3. The installer installs the program into your user account folder (`%LOCALAPPDATA%\Programs\LeafAreaAnalyzer`)—**no Administrator password is required**.
4. Leave **"Open Leaf Area Analyzer when setup finishes"** checked (or double-click the **LeafArea & LAI Analyzer** shortcut on your Desktop or in your Start Menu). The app opens directly in a clean standalone window with no console box.

### Windows (Option B: Portable ZIP — No Installation Needed)
1. Right-click **`LeafAreaAnalyzer-v1.5.6-portable.zip`** and select **Extract All...**.
2. Open the extracted `LeafAreaAnalyzer` folder and double-click **`LeafAreaAnalyzer.exe`**.

### Linux (`x86_64` — Desktop Installer)
1. Extract the release archive and run the per-user installer (never requires `sudo`):
   ```bash
   tar -xzf LeafAreaAnalyzer-v1.5.6-linux-x86_64.tar.gz
   ./install_linux.sh
   ```
2. `install_linux.sh` copies the application to `~/.local/opt/LeafAreaAnalyzer`, adds **Leaf Area & LAI Analyzer** to your desktop application menu (`~/.local/share/applications/leaf-area-analyzer.desktop`), and optionally places a clickable launcher on your `~/Desktop`.
3. Click **Leaf Area & LAI Analyzer** in your application menu or on your Desktop. It opens automatically in a dedicated Chromium/Chrome app window (with its own isolated browser profile so proxy settings or extensions in Firefox/other browsers never interfere).
4. To uninstall at any time, run `./uninstall_linux.sh` (or `~/.local/opt/LeafAreaAnalyzer/uninstall_linux.sh`).

---

## 3. Printing & Checking the A4 Calibration Sheet

Accurate leaf area measurement depends on an accurate physical scale ($\text{pixels per cm}$):

1. Click **Download Blue A4 Calibration Sheet (PDF)** (or **Download Red A4 Calibration Sheet (PDF)** if you are measuring blue/dark-purple objects) in the top header of the app.
2. In your PDF viewer's Print dialog, set **Page Sizing & Handling** to **100% / Actual Size** (`Scale = None`). **Do NOT select "Fit to Page" or "Shrink Oversized Pages"**, as that shrinks the square by 3–6%.
3. **Mandatory Ruler Check:** After printing, take a millimeter ruler and measure:
   - The **10.00 cm Verification Scale Bar** at the bottom of the sheet—it must measure exactly **10.0 cm (100.0 mm)**.
   - The solid **Calibration Square**—it must measure exactly **2.00 cm × 2.00 cm (20.0 mm × 20.0 mm)**.
   If your printer scaled the sheet slightly (for example, the square measures `1.96 cm`), simply enter `1.96` in the **Known Side Length (cm)** box in the app.
4. **One Square Per Photo:** Use **only one** calibration square per photo, and keep the other sheet's square out of the camera frame.

---

## 4. How to Photograph or Scan Leaves

1. **Plain White Background:** Place detached leaves flat on the white A4 calibration sheet or on a flatbed scanner bed.
2. **Keep Leaves Separated & Flat:** Leaves must not touch or overlap each other, and must not touch the calibration square or the outer edge of the photo. If leaves are curled, press them flat under a sheet of clear glass or non-reflective acrylic.
3. **Camera Straight Above & Even Light:** Hold or mount the camera directly above the sheet (parallel to the paper) under even, diffuse lighting with no harsh cast shadows. A flatbed scanner at 300 DPI gives the highest precision.
4. **Full Native Resolution:** Always transfer and upload original, full-resolution `.jpg`, `.png`, or `.tif` files (at least $800 \times 800\text{ px}$). Never upload compressed messaging-app photos or screenshots.

---

## 5. Running an Analysis & Reading the Results

1. Drag and drop one or more leaf photos into the upload box (you can upload a batch of images from the same plot/sample together).
2. Confirm your **Calibration Square Settings** (default `2.00 cm`, `Blue Square`).
3. *(Optional)* To calculate **Leaf Area Index (LAI)**, choose:
   - **Mode 1:** Enter the total ground area ($\text{m}^2$) represented by the harvested leaves, or
   - **Mode 2:** Enter the **Number of Plants Sampled** and the **Ground Area per Plant ($\text{m}^2$)**.
4. Click **Analyze Leaf Area & LAI**.

### Reading the CSV and Excel (`.xlsx`) Exports
Click **Download CSV** or **Download XLSX** to save a permanent spreadsheet record containing:
- **One row per detected leaf** (`Leaf_Number = 1, 2, ...`) with its exact `Leaf_Area_cm2`, `Pixel_Count`, `Length_cm`, `Width_cm`, `Perimeter_cm`, `Solidity`, `Centroid_X_px`, `Centroid_Y_px`, and `Possible_Touching_Leaves` (`Yes`/`No`), plus
- **A final `TOTAL` row** summarizing the total leaf area, pixel count, and sample LAI,
- Full audit metadata on every row: `Scale_px_per_cm`, `Scale_Area_px_per_cm`, `Scale_Edge_px_per_cm`, `Calibration_Method`, `Otsu_Threshold`, `Edge_Threshold`, `Confidence`, `Warnings`, `Software_Version` (`LeafArea & LAI Analyzer v1.5.6`), and `Date_Time_UTC`.

---

## 6. Closing the App & Viewing Logs

- **Automatic Shutdown:** Simply close the application window (or click the red **Quit** button in the top-right header). The background server stops automatically a few seconds after the window is closed.
- **Viewing Diagnostic Logs:** Click **View Application Logs (`/api/logs/latest`)** in the page footer to view the latest 200 lines of `app.log` directly in your browser. Log files are stored in:
  - **Windows:** `%LOCALAPPDATA%\LeafAreaAnalyzer\logs\app.log`
  - **Linux:** `~/.local/share/LeafAreaAnalyzer/logs/app.log`
  - **macOS:** `~/Library/Application Support/LeafAreaAnalyzer/logs/app.log`
