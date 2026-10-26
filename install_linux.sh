#!/usr/bin/env bash
# ==============================================================================
# install_linux.sh — Per-User Desktop Installer for LeafArea & LAI Analyzer
#
# Installs LeafArea & LAI Analyzer into the current user's home directory:
#   - Application folder : ~/.local/opt/LeafAreaAnalyzer
#   - Desktop entry      : ~/.local/share/applications/leaf-area-analyzer.desktop
#   - Optional shortcut  : ~/Desktop/leaf-area-analyzer.desktop
#
# Never uses sudo and never writes outside $HOME.
# ==============================================================================
set -euo pipefail

if [ "$(id -u)" -eq 0 ] && [ "${ALLOW_ROOT_INSTALL:-0}" != "1" ]; then
  echo "ERROR: Do not run install_linux.sh as root or with sudo. It installs into your user home directory (~/.local)." >&2
  exit 1
fi

if [ -z "${HOME:-}" ]; then
  echo "ERROR: HOME environment variable is not set." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Locate the unpacked LeafAreaAnalyzer folder next to this script (or in dist/ LeafAreaAnalyzer)
if [ -d "${SCRIPT_DIR}/LeafAreaAnalyzer" ]; then
  SRC_APP_DIR="${SCRIPT_DIR}/LeafAreaAnalyzer"
elif [ -d "${SCRIPT_DIR}/dist/LeafAreaAnalyzer" ]; then
  SRC_APP_DIR="${SCRIPT_DIR}/dist/LeafAreaAnalyzer"
else
  echo "ERROR: Could not find 'LeafAreaAnalyzer' folder next to install_linux.sh (checked ${SCRIPT_DIR}/LeafAreaAnalyzer)." >&2
  exit 1
fi

INSTALL_DIR="${HOME}/.local/opt/LeafAreaAnalyzer"
APPS_DIR="${HOME}/.local/share/applications"
DESKTOP_FILE="${APPS_DIR}/leaf-area-analyzer.desktop"
DESKTOP_SHORTCUT="${HOME}/Desktop/leaf-area-analyzer.desktop"

echo "Installing Leaf Area & LAI Analyzer into ${INSTALL_DIR}..."
mkdir -p "${HOME}/.local/opt" "${APPS_DIR}"
rm -rf "${INSTALL_DIR}"
cp -a "${SRC_APP_DIR}" "${INSTALL_DIR}"
chmod +x "${INSTALL_DIR}/LeafAreaAnalyzer"

# Ensure icon.png is available at ${INSTALL_DIR}/icon.png
if [ -f "${INSTALL_DIR}/_internal/assets/icon.png" ]; then
  cp -f "${INSTALL_DIR}/_internal/assets/icon.png" "${INSTALL_DIR}/icon.png"
elif [ -f "${INSTALL_DIR}/assets/icon.png" ]; then
  cp -f "${INSTALL_DIR}/assets/icon.png" "${INSTALL_DIR}/icon.png"
elif [ -f "${SCRIPT_DIR}/assets/icon.png" ]; then
  cp -f "${SCRIPT_DIR}/assets/icon.png" "${INSTALL_DIR}/icon.png"
fi

# Copy uninstall_linux.sh into the installed folder for easy access
if [ -f "${SCRIPT_DIR}/uninstall_linux.sh" ]; then
  cp -f "${SCRIPT_DIR}/uninstall_linux.sh" "${INSTALL_DIR}/uninstall_linux.sh"
  chmod +x "${INSTALL_DIR}/uninstall_linux.sh"
fi

EXEC_PATH="${INSTALL_DIR}/LeafAreaAnalyzer"
ICON_PATH="${INSTALL_DIR}/icon.png"

cat > "${DESKTOP_FILE}" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Leaf Area & LAI Analyzer
Comment=Fully Automatic Leaf Area and Leaf Area Index (LAI) Analyzer
Exec="${EXEC_PATH}"
Icon=${ICON_PATH}
Terminal=false
Categories=Science;Education;
StartupWMClass=LeafAreaAnalyzer
StartupNotify=true
EOF

chmod 644 "${DESKTOP_FILE}"

# Optional Desktop shortcut prompt
CREATE_DESKTOP_SHORTCUT="n"
if [ "${1:-}" = "--yes" ] || [ "${1:-}" = "-y" ]; then
  CREATE_DESKTOP_SHORTCUT="y"
elif [ "${1:-}" = "--no-desktop" ]; then
  CREATE_DESKTOP_SHORTCUT="n"
else
  printf "Copy launcher shortcut to %s/Desktop? [y/N]: " "${HOME}"
  if ! read -r CREATE_DESKTOP_SHORTCUT; then
    CREATE_DESKTOP_SHORTCUT="n"
  fi
fi

INSTALLED_DESKTOP_SHORTCUT="no"
case "${CREATE_DESKTOP_SHORTCUT}" in
  [yY]|[yY][eE][sS])
    mkdir -p "${HOME}/Desktop"
    cp -f "${DESKTOP_FILE}" "${DESKTOP_SHORTCUT}"
    chmod +x "${DESKTOP_SHORTCUT}"
    if command -v gio >/dev/null 2>&1; then
      gio set "${DESKTOP_SHORTCUT}" metadata::trusted true >/dev/null 2>&1 || true
    fi
    INSTALLED_DESKTOP_SHORTCUT="yes"
    ;;
  *)
    ;;
esac

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${APPS_DIR}" >/dev/null 2>&1 || true
fi

if command -v desktop-file-validate >/dev/null 2>&1; then
  desktop-file-validate "${DESKTOP_FILE}"
fi

echo "=================================================================="
echo " Leaf Area & LAI Analyzer installed!"
echo " Installed App Folder : ${INSTALL_DIR}"
echo " Application Menu     : ${DESKTOP_FILE}"
if [ "${INSTALLED_DESKTOP_SHORTCUT}" = "yes" ]; then
  echo " Desktop Shortcut     : ${DESKTOP_SHORTCUT}"
fi
echo ""
echo " To uninstall at any time, run:"
echo "   ${INSTALL_DIR}/uninstall_linux.sh"
echo "   (or ./uninstall_linux.sh from this folder)"
echo "=================================================================="
