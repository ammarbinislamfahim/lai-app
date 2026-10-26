#!/usr/bin/env bash
# ==============================================================================
# build_linux.sh — Automated Linux x86_64 Desktop Package Builder
# Builds and verifies the standalone one-folder Linux distribution of
# LeafArea & LAI Analyzer on Kali Linux / Debian / Ubuntu.
#
# Required apt packages on Kali Linux:
#   sudo apt update && sudo apt install -y git python3 python3-venv python3-pip \
#     python3-dev build-essential binutils libgl1 libglib2.0-0 tar
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# Extract single-source SOFTWARE_VERSION from app/config.py
VERSION="$(python3 -c '
import re
from pathlib import Path
text = Path("app/config.py").read_text(encoding="utf-8")
m = re.search(r"SOFTWARE_VERSION:\s*Final\[str\]\s*=\s*\"([^\"]+)\"", text)
assert m, "Could not parse SOFTWARE_VERSION from app/config.py"
print(m.group(1))
')"

echo "=================================================================="
echo " Building LeafArea & LAI Analyzer v${VERSION} (Linux x86_64)"
echo "=================================================================="

# 1. Create a fresh isolated virtual environment and install pinned lock files.
#    No --system-site-packages or offline fallbacks: if pip install fails, exit immediately.
echo "[1/6] Creating isolated virtual environment (.venv) and installing pinned lock files..."
VENV_DIR="${SCRIPT_DIR}/.venv"
rm -rf "${VENV_DIR}"
python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r requirements-lock.txt -r requirements-build.txt

# 2. Run the full verification & accuracy test suite
echo "[2/6] Running pytest verification suite..."
"${VENV_DIR}/bin/pytest" --ignore=tests/test_packaged.py -v

# 3. Run PyInstaller with leafarea.spec (one-folder mode)
echo "[3/6] Building standalone one-folder bundle with PyInstaller..."
"${VENV_DIR}/bin/pyinstaller" --clean --noconfirm leafarea.spec

# 4. Verify standalone bundle size, shared libraries, and bundled scientific packages
echo "[4/6] Verifying standalone bundle structure and shared libraries..."
du -sh "${SCRIPT_DIR}/dist/LeafAreaAnalyzer"
if ldd "${SCRIPT_DIR}/dist/LeafAreaAnalyzer/LeafAreaAnalyzer" | grep "not found"; then
  echo "ERROR: Missing shared libraries detected by ldd!" >&2
  exit 1
fi
ls -ld "${SCRIPT_DIR}/dist/LeafAreaAnalyzer/_internal/cv2" \
       "${SCRIPT_DIR}/dist/LeafAreaAnalyzer/_internal/numpy" \
       "${SCRIPT_DIR}/dist/LeafAreaAnalyzer/_internal/scipy"

# 5. Run end-to-end packaged executable verification under clean environment
echo "[5/6] Running packaged executable verification (tests/test_packaged.py)..."
env -i PATH=/usr/bin:/bin "${VENV_DIR}/bin/pytest" tests/test_packaged.py -v -s

# 6. Copy install_linux.sh and uninstall_linux.sh next to LeafAreaAnalyzer in dist/ and create tar.gz
ARCHIVE_NAME="LeafAreaAnalyzer-v${VERSION}-linux-x86_64.tar.gz"
ARCHIVE_PATH="${SCRIPT_DIR}/dist/${ARCHIVE_NAME}"
SHA_PATH="${ARCHIVE_PATH}.sha256"

echo "[6/6] Creating release archive ${ARCHIVE_NAME} (with install_linux.sh & uninstall_linux.sh) and SHA-256 checksum..."
cp -f "${SCRIPT_DIR}/install_linux.sh" "${SCRIPT_DIR}/dist/install_linux.sh"
cp -f "${SCRIPT_DIR}/uninstall_linux.sh" "${SCRIPT_DIR}/dist/uninstall_linux.sh"
chmod +x "${SCRIPT_DIR}/dist/install_linux.sh" "${SCRIPT_DIR}/dist/uninstall_linux.sh"

tar -C "${SCRIPT_DIR}/dist" -czf "${ARCHIVE_PATH}" LeafAreaAnalyzer install_linux.sh uninstall_linux.sh
(
  cd "${SCRIPT_DIR}/dist"
  sha256sum "${ARCHIVE_NAME}" > "${ARCHIVE_NAME}.sha256"
)

echo "=================================================================="
echo " Linux build complete!"
echo " Output Archive : ${ARCHIVE_PATH}"
echo " Archive Size   : $(du -h "${ARCHIVE_PATH}" | cut -f1)"
echo " Bundle Size    : $(du -sh "${SCRIPT_DIR}/dist/LeafAreaAnalyzer" | cut -f1)"
echo " SHA-256        : $(cat "${SHA_PATH}")"
echo "=================================================================="
