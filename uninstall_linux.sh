#!/usr/bin/env bash
# ==============================================================================
# uninstall_linux.sh — Per-User Uninstaller for LeafArea & LAI Analyzer
#
# Removes:
#   - ~/.local/opt/LeafAreaAnalyzer
#   - ~/.local/share/applications/leaf-area-analyzer.desktop
#   - ~/Desktop/leaf-area-analyzer.desktop (if present)
# And removes the user data directory (~/.local/share/LeafAreaAnalyzer) ONLY
# if the user confirms. Never uses sudo and never writes outside $HOME.
# ==============================================================================
set -euo pipefail

if [ -z "${HOME:-}" ]; then
  echo "ERROR: HOME environment variable is not set." >&2
  exit 1
fi

INSTALL_DIR="${HOME}/.local/opt/LeafAreaAnalyzer"
APPS_DIR="${HOME}/.local/share/applications"
DESKTOP_FILE="${APPS_DIR}/leaf-area-analyzer.desktop"
DESKTOP_SHORTCUT="${HOME}/Desktop/leaf-area-analyzer.desktop"
USER_DATA_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/LeafAreaAnalyzer"

echo "Uninstalling Leaf Area & LAI Analyzer from ${HOME}..."

if [ -d "${INSTALL_DIR}" ]; then
  rm -rf "${INSTALL_DIR}"
  echo "Removed application folder: ${INSTALL_DIR}"
fi

# Clean up ~/.local/opt if it is now empty
if [ -d "${HOME}/.local/opt" ] && [ -z "$(ls -A "${HOME}/.local/opt")" ]; then
  rmdir "${HOME}/.local/opt" 2>/dev/null || true
fi

if [ -f "${DESKTOP_FILE}" ]; then
  rm -f "${DESKTOP_FILE}"
  echo "Removed desktop entry: ${DESKTOP_FILE}"
fi

if [ -f "${DESKTOP_SHORTCUT}" ]; then
  rm -f "${DESKTOP_SHORTCUT}"
  echo "Removed Desktop shortcut: ${DESKTOP_SHORTCUT}"
fi

if command -v update-desktop-database >/dev/null 2>&1 && [ -d "${APPS_DIR}" ]; then
  update-desktop-database "${APPS_DIR}" >/dev/null 2>&1 || true
fi

if [ -d "${USER_DATA_DIR}" ]; then
  REMOVE_DATA="n"
  if [ "${1:-}" = "--yes" ] || [ "${1:-}" = "-y" ] || [ "${1:-}" = "--remove-data" ]; then
    REMOVE_DATA="y"
  elif [ "${1:-}" = "--keep-data" ]; then
    REMOVE_DATA="n"
  else
    printf "Also remove user data and logs in %s? [y/N]: " "${USER_DATA_DIR}"
    if ! read -r REMOVE_DATA; then
      REMOVE_DATA="n"
    fi
  fi

  case "${REMOVE_DATA}" in
    [yY]|[yY][eE][sS])
      rm -rf "${USER_DATA_DIR}"
      echo "Removed user data directory: ${USER_DATA_DIR}"
      ;;
    *)
      echo "Kept user data directory: ${USER_DATA_DIR}"
      ;;
  esac
fi

echo "Uninstall complete."
