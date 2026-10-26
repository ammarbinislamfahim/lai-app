# Fully Automatic Leaf Area & LAI Measurement App (v1.5.6)

A deterministic, zero-click scientific desktop and web application that measures one-sided leaf surface area ($\text{cm}^2$) from full-resolution photos or flatbed scans and calculates the **Leaf Area Index ($\text{LAI}$)**. Built to replace manual ImageJ workflows (`Set Scale` $\rightarrow$ `Color Threshold` $\rightarrow$ `Analyze Particles`) with a reproducible, auditable pipeline that flags measurement uncertainty and quality warnings rather than silently guessing.

---

## 1. Privacy, Offline Operation & Localhost Security

- **Localhost Only (`127.0.0.1`):** The application server binds strictly to **`127.0.0.1`** (never `0.0.0.0`) so it is never exposed to your local network or the internet. Lifecycle and log endpoints (`/api/ping`, `/api/bye`, `/api/quit`, `/api/logs/latest`) enforce `127.0.0.1`-only access.
- **Zero Outgoing Network Calls & Zero Telemetry:** The application makes **no outgoing network requests**, phones home to no external servers, and collects **no telemetry or analytics**. All image processing runs 100% offline on your local CPU.
- **Click-to-Open & Automatic Shutdown:** `launcher.py` (or the `leafarea-analyzer` CLI command) automatically opens a Chromium-family browser in `--app=http://127.0.0.1:<port>` mode with an isolated profile (`<user_data_dir>/browser-profile`) so proxy settings or extensions in other browsers never interfere, and automatically shuts down the server 8 seconds after the last browser window closes (once any in-progress `/api/analyze` call finishes).
- **Read-Only Installation Folder:** When running as a packaged desktop app, the installation folder is never modified at runtime. Logs (`logs/app.log`), browser profile (`browser-profile/`), and runtime state (`port.txt`) are stored exclusively in the per-user data directory (`%LOCALAPPDATA%\LeafAreaAnalyzer` on Windows, `~/.local/share/LeafAreaAnalyzer` on Linux, and `~/Library/Application Support/LeafAreaAnalyzer` on macOS).

---

## 2. Install & Run from GitHub on Any Platform (Command Line / Terminal)

### Option A: One-Command Install from GitHub via `pipx` (Linux, Windows, macOS)

If you have Python 3.10+ and [`pipx`](https://pipx.pypa.io/) installed, you can install the app directly from GitHub into an isolated environment on **any operating system** and launch it from anywhere with a single command:

```bash
# Install directly from GitHub (works in Linux bash/zsh, macOS Terminal, and Windows PowerShell/CMD)
pipx install git+https://github.com/ammarbinislamfahim/lai-app.git

# Launch the desktop app (opens automatically in an app-mode window)
leafarea-analyzer
```

To upgrade later when a new version is pushed to GitHub:
```bash
pipx upgrade leafarea-analyzer
```

To uninstall:
```bash
pipx uninstall leafarea-analyzer
```

---

### Option B: Clone & Run from Terminal (`git clone` + Virtual Environment)

Use these exact copy-paste terminal commands for your operating system.

#### 1. Linux (Kali Linux / Ubuntu / Debian / Mint)

> **Note for Kali / Debian / Ubuntu (PEP 668):** System Python is externally managed. Always create a virtual environment (`.venv`) as shown below—never use `--break-system-packages`.

```bash
# 1. Install system dependencies (Git, Python venv, and OpenCV runtime libraries)
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip libgl1 libglib2.0-0 desktop-file-utils

# 2. Clone the repository from GitHub
git clone https://github.com/ammarbinislamfahim/lai-app.git
cd lai-app

# 3. Create and activate an isolated virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 4. Install pinned dependencies (and register the CLI launcher)
pip install --upgrade pip
pip install -r requirements-lock.txt
pip install --no-build-isolation --no-deps -e .

# 5. Launch the app (opens a clean app-mode window and quits when closed)
python3 launcher.py
# Or run via the installed CLI entry point:
leafarea-analyzer
```

*For **Fedora / RHEL** (`dnf`):*
```bash
sudo dnf install -y git python3 python3-pip mesa-libGL glib2 desktop-file-utils
```
*For **Arch / Manjaro** (`pacman`):*
```bash
sudo pacman -S --needed git python python-pip mesa glib2 desktop-file-utils
```
*(Then run steps 2–5 above.)*

---

#### 2. Windows 10 / 11 (PowerShell)

Open **PowerShell** (ensure [Git](https://git-scm.com/) and [Python 3.11+](https://www.python.org/downloads/) are installed with *"Add Python to PATH"* checked):

```powershell
# 1. Clone the repository from GitHub
git clone https://github.com/ammarbinislamfahim/lai-app.git
cd lai-app

# 2. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
python -m pip install --upgrade pip
pip install -r requirements-lock.txt
pip install --no-build-isolation --no-deps -e .

# 4. Launch the desktop app (opens Chrome or Edge in app mode)
python launcher.py
# Or run via the CLI entry point:
leafarea-analyzer
```

*If using **Windows Command Prompt (`cmd.exe`)** instead of PowerShell, replace step 2 with:*
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

---

#### 3. macOS (Intel & Apple Silicon M1/M2/M3/M4 — Terminal)

Open **Terminal** (`zsh` / `bash`):

```bash
# 1. Install Python 3.11+ and Git (via Xcode Command Line Tools or Homebrew)
# If Homebrew is installed: brew install git python@3.11

# 2. Clone the repository from GitHub
git clone https://github.com/ammarbinislamfahim/lai-app.git
cd lai-app

# 3. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 4. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install --no-build-isolation --no-deps -e .

# 5. Launch the desktop app
python3 launcher.py
# Or run via the CLI entry point:
leafarea-analyzer
```

---

### Option C: Install Pre-Built Standalone Releases from GitHub (No Python Required)

Every tagged release (`v*`) built by `.github/workflows/build.yml` publishes ready-to-run standalone archives to **GitHub Releases** so end users do not need Python or Git installed.

#### 1. Linux (`x86_64`) — Terminal Install from GitHub Releases
```bash
# Download the latest Linux release tarball from GitHub Releases
curl -fLO https://github.com/ammarbinislamfahim/lai-app/releases/latest/download/LeafAreaAnalyzer-v1.5.6-linux-x86_64.tar.gz

# Extract and run the per-user desktop installer (no sudo required)
tar -xzf LeafAreaAnalyzer-v1.5.6-linux-x86_64.tar.gz
./install_linux.sh

# Launch from your desktop application menu or from terminal:
~/.local/bin/leafarea-analyzer
```
To uninstall on Linux at any time:
```bash
./uninstall_linux.sh
```

#### 2. Windows (`x64`) — PowerShell Install from GitHub Releases
```powershell
# Download the standalone Windows Setup installer and run it
Invoke-WebRequest -Uri "https://github.com/ammarbinislamfahim/lai-app/releases/latest/download/LeafAreaAnalyzer-Setup-v1.5.6.exe" -OutFile "LeafAreaAnalyzer-Setup.exe"
.\LeafAreaAnalyzer-Setup.exe
```

#### 3. macOS — Terminal Install from GitHub Releases
```bash
# Download and extract the standalone macOS archive
curl -fLO https://github.com/ammarbinislamfahim/lai-app/releases/latest/download/LeafAreaAnalyzer-v1.5.6-macos.zip
unzip LeafAreaAnalyzer-v1.5.6-macos.zip
./LeafAreaAnalyzer/LeafAreaAnalyzer
```

---

## 3. Running Tests & Building Desktop Packages

### Run the Automated Verification Suite (All Platforms)
With your `.venv` activated inside the project root (`pytest.ini` and `pyproject.toml` configure `pythonpath = .` automatically):
```bash
pytest -v
```

### Build the Standalone Linux Desktop Package Locally (Kali / Ubuntu / Debian)
```bash
./build_linux.sh
```
This script:
1. Creates a fresh `.venv` and installs `requirements-lock.txt` and `requirements-build.txt` (`pyinstaller==6.11.1`).
2. Runs the full `pytest` accuracy, API, and desktop lifecycle test suite.
3. Builds the one-folder executable in `dist/LeafAreaAnalyzer/` using `leafarea.spec`.
4. Verifies bundle size ($\ge 80\text{ MB}$), `ldd` shared libraries, and `tests/test_packaged.py` under `env -i PATH=/usr/bin:/bin`.
5. Packages `dist/LeafAreaAnalyzer-v1.5.6-linux-x86_64.tar.gz` (containing `LeafAreaAnalyzer/`, `install_linux.sh`, and `uninstall_linux.sh`) and writes `dist/LeafAreaAnalyzer-v1.5.6-linux-x86_64.tar.gz.sha256`.

### Publish a Multi-Platform GitHub Release (Windows + Linux + macOS via GitHub Actions)

#### Option 1: One-Command Automated GitHub Publish (`publish_to_github.sh`)
Run the included `publish_to_github.sh` script from the project folder. It automatically replaces `ammarbinislamfahim/lai-app` in `README.md`, initializes Git, commits all files, creates/pushes the repository (via `gh repo create` if GitHub CLI is authenticated, or `git push`), and pushes the `v1.5.6` tag to trigger `.github/workflows/build.yml`:
```bash
chmod +x publish_to_github.sh
./publish_to_github.sh ammarbinislamfahim lai-app
```

#### Option 2: Manual Git & Release Steps
1. **Bump the single-source version:** Edit `SOFTWARE_VERSION` in `app/config.py` (currently `"1.5.6"`). Also update `version` in `pyproject.toml` and `CITATION.cff`.
2. **Verify locally:**
   ```bash
   ./build_linux.sh
   ```
3. **Commit and push a version tag to trigger `.github/workflows/build.yml`:**
   ```bash
   git add -A
   git commit -m "Release v1.5.6"
   git push origin main
   git tag v1.5.6
   git push origin v1.5.6
   ```

---

## 4. Synthetic Ground-Truth Accuracy Report (v1.5.6)

| Test Case / Scene | True Scale (px/cm) | Measured Scale (Area) | Measured Scale (Edge) | True Area ($\text{cm}^2$) | Measured Area ($\text{cm}^2$) | Rel. Error (%) | Leaf Count (True / Meas) | Extra Calib Squares Excluded |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: |
| `01_clean_standard` | 100.000 | 100.000 | 100.000 | 48.0464 | 48.0464 | **+0.000%** | 4 / 4 | 0 |
| `02_leaf_with_hole` | 100.000 | 100.000 | 100.000 | 21.2305 | 21.2305 | **+0.000%** | 1 / 1 | 0 |
| `03_mild_gaussian_noise` | 100.000 | 100.000 | 100.000 | 48.0464 | 48.0460 | **-0.001%** | 4 / 4 | 0 |
| `04_soft_gray_shadow` | 100.000 | 100.000 | 100.000 | 24.4648 | 24.4653 | **+0.002%** | 2 / 2 | 0 |
| `05_brightness_gradient` | 100.000 | 100.000 | 100.000 | 48.0464 | 48.0465 | **+0.000%** | 4 / 4 | 0 |
| `06_rotated_image` | 100.000 | 100.002 | 100.008 | 48.0483 | 48.0479 | **-0.001%** | 4 / 4 | 0 |
| `07_dust_specks` | 100.000 | 100.000 | 100.000 | 48.0464 | 48.0464 | **+0.000%** | 4 / 4 | 0 |
| `08_yellow_brown_leaves` | 100.000 | 100.000 | 100.000 | 34.6931 | 34.6631 | **-0.086%** | 3 / 3 | 0 |
| `09_border_and_red_calib` | 100.000 | 100.000 | 100.000 | 14.3931 | 14.4181 | **+0.174%** | 1 / 1 | 0 |
| `10_extra_calib_square` (Item C.1) | 100.000 | 100.000 | 100.000 | 100.0000 | 100.0000 | **+0.000%** | 1 / 1 | 1 |
| `11_red_elliptical_leaf` (Item C.2) | 100.000 | 100.000 | 100.000 | 3.5657 | 3.5692 | **+0.098%** | 1 / 1 | 0 |
| `Sheet_59_1_px_per_cm` (Issue E) | 59.100 | 59.100 | 59.051 | 100.0000 | 100.0025 | **+0.003%** | 1 / 1 | 1 |
| `large_A` (`8×5 cm` ellipse, 100 px/cm) | 100.000 | 100.000 | 100.002 | 31.4159 | 31.4258 | **+0.031%** | 1 / 1 | 0 |
| `large_B` (`3, 5, 7 cm` leaves, 100 px/cm) | 100.000 | 100.000 | 100.002 | 66.2007 | 66.2196 | **+0.029%** | 3 / 3 | 0 |
| `large_C` (`12 cm` wide leaf, 100 px/cm) | 100.000 | 100.000 | 100.002 | 115.6540 | 115.6873 | **+0.029%** | 1 / 1 | 0 |
| `large_D` (`large_B` + shadow/gradient) | 100.000 | 100.000 | 100.002 | 66.2007 | 66.2351 | **+0.052%** | 3 / 3 | 0 |
