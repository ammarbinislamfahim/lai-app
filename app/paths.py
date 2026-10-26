"""Resource path resolution and OS-specific user data directory management for desktop packaging.

Ensures the application works identically in standard Python runs and when frozen by
PyInstaller (`sys.frozen` / `sys._MEIPASS`), while keeping the installation directory
strictly read-only at runtime.
"""

import os
from pathlib import Path
import sys

APP_DIR_NAME = "LeafAreaAnalyzer"


def project_root() -> Path:
    """Return the base directory containing bundled resources (`_MEIPASS` when frozen)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return Path(__file__).resolve().parent.parent


def resource_path(relative: str | Path) -> Path:
    """Return the absolute path to a bundled resource in both normal and PyInstaller-frozen runs."""
    rel_path = Path(relative)
    return project_root() / rel_path


def user_data_dir() -> Path:
    """Return the OS-appropriate per-user data directory, creating it if missing.

    - Windows: `%LOCALAPPDATA%\\LeafAreaAnalyzer`
    - macOS:   `~/Library/Application Support/LeafAreaAnalyzer`
    - Linux:   `~/.local/share/LeafAreaAnalyzer` (or `$XDG_DATA_HOME/LeafAreaAnalyzer`)

    Can be overridden via `LEAFAREA_USER_DATA_DIR` for isolated testing.
    """
    override = os.environ.get("LEAFAREA_USER_DATA_DIR")
    if override:
        base = Path(override).expanduser().resolve()
        base.mkdir(parents=True, exist_ok=True)
        return base

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            base = Path(local_app_data) / APP_DIR_NAME
        else:
            base = Path.home() / "AppData" / "Local" / APP_DIR_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            base = Path(xdg_data).expanduser() / APP_DIR_NAME
        else:
            base = Path.home() / ".local" / "share" / APP_DIR_NAME

    base.mkdir(parents=True, exist_ok=True)
    return base
