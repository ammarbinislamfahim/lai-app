"""Click-to-open desktop launcher for LeafArea & LAI Analyzer.

Starts the FastAPI application via Uvicorn bound strictly to 127.0.0.1 (localhost only),
configures file logging to `user_data_dir()/logs/app.log` with `log_config=None` so
frozen PyInstaller builds never crash on Uvicorn formatter setup, detects already-running
instances via `user_data_dir()/port.txt`, opens a Chromium-family browser in `--app=` mode
with an isolated profile (`user_data_dir()/browser-profile`), runs a background watchdog
that cleanly exits when all browser windows close, and displays GUI error dialogs when
no console is attached.
"""

import atexit
import json
import logging
from logging.handlers import RotatingFileHandler
import multiprocessing
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from typing import Any
import urllib.error
import urllib.request
import webbrowser

from app import config
from app.paths import user_data_dir

HOST = "127.0.0.1"
DEFAULT_PORT = 8000

LINUX_CHROMIUM_CANDIDATES: tuple[str, ...] = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "microsoft-edge",
)


def _safe_print(text: str, *, err: bool = False) -> None:
    """Write to stdout/stderr safely even when `console=False` sets streams to None."""
    stream = sys.stderr if err else sys.stdout
    if stream is not None:
        try:
            print(text, file=stream, flush=True)
        except Exception:
            pass


def configure_file_logging(data_dir: Path) -> Path:
    """Configure rotating file logging in `user_data_dir()/logs/app.log`."""
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "launcher"):
        lg = logging.getLogger(logger_name)
        lg.handlers = [file_handler]
        lg.propagate = False
        lg.setLevel(logging.INFO)

    return log_file


def show_visible_message(
    message: str,
    *,
    title: str | None = None,
    log_file: Path | None = None,
    is_error: bool = True,
) -> None:
    """Show a visible GUI dialog on Windows or Linux when console is hidden or browser fails."""
    dialog_title = title or (
        f"{config.SOFTWARE_NAME} v{config.SOFTWARE_VERSION} — Error"
        if is_error
        else f"{config.SOFTWARE_NAME} v{config.SOFTWARE_VERSION}"
    )
    full_message = message
    if log_file is not None and str(log_file) not in full_message:
        full_message = f"{message}\n\nLog file:\n{log_file}"

    logger = logging.getLogger("launcher")
    if is_error:
        logger.error("Visible error message: %s", full_message.replace("\n", " | "))
    else:
        logger.info("Visible info message: %s", full_message.replace("\n", " | "))

    if os.environ.get("LEAFAREA_NONINTERACTIVE", "").strip().lower() in {"1", "true", "yes"}:
        return

    if sys.platform == "win32":
        try:
            import ctypes

            mb_flag = 0x10 if is_error else 0x40  # MB_ICONERROR or MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(0, full_message, dialog_title, mb_flag)
            return
        except Exception as exc:
            logger.warning("ctypes MessageBoxW failed: %s", exc)
            return

    if sys.platform.startswith("linux") and (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        zenity_bin = shutil.which("zenity")
        if zenity_bin:
            mode_flag = "--error" if is_error else "--info"
            try:
                subprocess.run(
                    [zenity_bin, mode_flag, f"--title={dialog_title}", f"--text={full_message}", "--no-wrap"],
                    check=False,
                    timeout=30,
                )
                return
            except Exception:
                pass

        kdialog_bin = shutil.which("kdialog")
        if kdialog_bin:
            mode_flag = "--error" if is_error else "--msgbox"
            try:
                subprocess.run(
                    [kdialog_bin, mode_flag, full_message, "--title", dialog_title],
                    check=False,
                    timeout=30,
                )
                return
            except Exception:
                pass

        notify_bin = shutil.which("notify-send")
        if notify_bin:
            urgency = "critical" if is_error else "normal"
            try:
                subprocess.run(
                    [notify_bin, "-u", urgency, dialog_title, full_message],
                    check=False,
                    timeout=10,
                )
                return
            except Exception:
                pass


def check_health(port: int, timeout: float = 0.8) -> bool:
    """Return True if `http://127.0.0.1:<port>/api/health` responds with status OK."""
    url = f"http://{HOST}:{port}/api/health"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                payload = json.loads(resp.read().decode("utf-8"))
                return payload.get("status") == "OK"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False
    return False


def is_port_free(port: int) -> bool:
    """Return True if TCP port on 127.0.0.1 can be bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((HOST, port))
            return True
        except OSError:
            return False


def find_free_port(preferred: int = DEFAULT_PORT) -> int:
    """Try `preferred` port (8000) first; otherwise allocate an ephemeral free port on 127.0.0.1."""
    env_port = os.environ.get("LEAFAREA_PORT")
    if env_port:
        try:
            p = int(env_port)
            if is_port_free(p):
                return p
        except ValueError:
            pass

    if is_port_free(preferred):
        return preferred

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _find_windows_chromium_browsers() -> list[str]:
    """Return existing Chrome or Edge executable paths in standard Windows locations."""
    candidates: list[str] = []
    env_roots = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    rel_paths = [
        r"Google\Chrome\Application\chrome.exe",
        r"Microsoft\Edge\Application\msedge.exe",
    ]
    for root in env_roots:
        if not root:
            continue
        for rel in rel_paths:
            full = Path(root) / rel
            if full.is_file():
                candidates.append(str(full))
    for cmd in ("chrome", "msedge", "google-chrome", "chromium"):
        found = shutil.which(cmd)
        if found and found not in candidates:
            candidates.append(found)
    return candidates


def _find_macos_chromium_browsers() -> list[str]:
    """Return existing Chrome, Edge, Chromium, or Brave executable paths on macOS."""
    candidates: list[str] = []
    app_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    ]
    for p in app_paths:
        full = Path(p)
        if full.is_file():
            candidates.append(str(full))
    return candidates


def _resolve_browser_command(url: str, data_dir: Path) -> list[str] | None:
    """Resolve the preferred Chromium-family `--app=` command or `LEAFAREA_BROWSER` override."""
    profile_dir = data_dir / "browser-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    app_args = [
        f"--app={url}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
    ]

    env_browser = os.environ.get("LEAFAREA_BROWSER", "").strip()
    if env_browser:
        resolved = shutil.which(env_browser)
        if not resolved and Path(env_browser).is_file():
            resolved = str(Path(env_browser).resolve())
        if resolved:
            exe_name = Path(resolved).name.lower()
            if "firefox" in exe_name:
                return [resolved, url]
            return [resolved, *app_args]
        return None

    if sys.platform == "win32":
        win_browsers = _find_windows_chromium_browsers()
        if win_browsers:
            return [win_browsers[0], *app_args]
        return None

    if sys.platform == "darwin":
        mac_browsers = _find_macos_chromium_browsers()
        if mac_browsers:
            return [mac_browsers[0], *app_args]
        return None

    if sys.platform.startswith("linux"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return None
        for name in LINUX_CHROMIUM_CANDIDATES:
            found = shutil.which(name)
            if found:
                return [found, *app_args]
    return None


def open_browser_safely(url: str, data_dir: Path | None = None) -> bool:
    """Open the app in a Chromium `--app=` window first, then `webbrowser.open`, then visible message."""
    logger = logging.getLogger("launcher")
    if os.environ.get("LEAFAREA_NO_BROWSER", "").strip().lower() in {"1", "true", "yes"}:
        logger.info("LEAFAREA_NO_BROWSER is set; skipping browser launch for %s", url)
        return True

    active_data_dir = data_dir if data_dir is not None else user_data_dir()
    log_file = active_data_dir / "logs" / "app.log"

    cmd = _resolve_browser_command(url, active_data_dir)
    if cmd is not None:
        try:
            logger.info("Opening browser in app mode: %s", " ".join(cmd))
            popen_kwargs: dict[str, Any] = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform != "win32":
                popen_kwargs["start_new_session"] = True
            subprocess.Popen(cmd, **popen_kwargs)
            return True
        except Exception as exc:
            logger.warning("Failed to launch Chromium browser (%s): %s", cmd[0], exc)

    has_display = (
        sys.platform == "win32"
        or sys.platform == "darwin"
        or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    )
    if has_display:
        try:
            opened = webbrowser.open(url, new=1, autoraise=True)
            if opened:
                logger.info("Opened URL via webbrowser.open: %s", url)
                return True
        except Exception as exc:
            logger.warning("webbrowser.open failed for %s: %s", url, exc)

    fallback_msg = (
        f"Leaf Area & LAI Analyzer v{config.SOFTWARE_VERSION} is running.\n\n"
        f"Could not open a browser automatically. Please open this URL in your browser:\n{url}"
    )
    _safe_print(f"Could not open browser automatically. Please open: {url}")
    show_visible_message(fallback_msg, log_file=log_file, is_error=False)
    return False


def _wait_and_announce(
    port: int,
    port_file: Path,
    data_dir: Path,
    ready_event: threading.Event,
) -> None:
    """Poll `/api/health` until ready, write `port.txt`, log banner, and open the browser."""
    url = f"http://{HOST}:{port}"
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if check_health(port, timeout=0.5):
            try:
                port_file.write_text(str(port), encoding="utf-8")
            except OSError:
                pass
            banner = (
                f"Leaf Area & LAI Analyzer v{config.SOFTWARE_VERSION} is running at "
                f"{url}. Close this window to stop."
            )
            _safe_print(banner)
            logging.getLogger("launcher").info(banner)
            ready_event.set()
            open_browser_safely(url, data_dir=data_dir)
            return
        time.sleep(0.1)


def _watchdog_loop(
    server: Any,
    port_file: Path,
    ready_event: threading.Event,
    cleanup_fn: Any,
) -> None:
    """Check client activity every 2s (configurable for tests) and trigger clean shutdown when idle."""
    from app.main import get_lifecycle_snapshot

    logger = logging.getLogger("launcher")
    check_interval = float(os.environ.get("LEAFAREA_WATCHDOG_INTERVAL_SEC", "2.0"))
    silence_timeout = float(os.environ.get("LEAFAREA_CLIENT_SILENCE_SEC", "120.0"))
    grace_period = float(os.environ.get("LEAFAREA_GRACE_PERIOD_SEC", "8.0"))
    startup_timeout = float(os.environ.get("LEAFAREA_STARTUP_TIMEOUT_SEC", "120.0"))

    if not ready_event.wait(timeout=35.0):
        return

    server_ready_at = time.monotonic()

    while not getattr(server, "should_exit", False):
        time.sleep(check_interval)
        if getattr(server, "should_exit", False):
            break

        snap = get_lifecycle_snapshot(silence_timeout_sec=silence_timeout)
        now = snap["now"]

        # Do not exit while an /api/analyze request is actively running
        if snap["active_analyze_count"] > 0:
            continue

        # Explicit Quit button clicked in header
        if snap["quit_requested"]:
            logger.info("Shutdown requested via /api/quit; stopping server cleanly.")
            cleanup_fn()
            server.should_exit = True
            break

        if snap["has_ever_connected"]:
            if (
                snap["active_client_count"] == 0
                and snap["last_client_left_at"] is not None
                and (now - snap["last_client_left_at"]) >= grace_period
            ):
                logger.info(
                    "All browser clients disconnected and %.1fs grace period elapsed; shutting down.",
                    grace_period,
                )
                cleanup_fn()
                server.should_exit = True
                break
        else:
            if (now - server_ready_at) >= startup_timeout:
                logger.info(
                    "No browser client connected within %.1fs after startup; shutting down.",
                    startup_timeout,
                )
                cleanup_fn()
                server.should_exit = True
                break


def main() -> int:
    """Run the LeafArea & LAI Analyzer desktop launcher."""
    log_file: Path | None = None
    try:
        data_dir = user_data_dir()
        log_file = configure_file_logging(data_dir)
        logger = logging.getLogger("launcher")
        logger.info("Starting %s v%s", config.SOFTWARE_NAME, config.SOFTWARE_VERSION)

        if os.environ.get("LEAFAREA_FORCE_STARTUP_ERROR", "").strip() == "1":
            raise RuntimeError("Simulated startup error via LEAFAREA_FORCE_STARTUP_ERROR=1")

        port_file = data_dir / "port.txt"
        if port_file.is_file():
            try:
                existing_port = int(port_file.read_text(encoding="utf-8").strip())
                if 1 <= existing_port <= 65535 and check_health(existing_port):
                    existing_url = f"http://{HOST}:{existing_port}"
                    _safe_print(
                        f"Leaf Area & LAI Analyzer v{config.SOFTWARE_VERSION} is already running at "
                        f"{existing_url}. Opening browser..."
                    )
                    logger.info("Detected running instance on port %d; opening browser.", existing_port)
                    open_browser_safely(existing_url, data_dir=data_dir)
                    return 0
            except (ValueError, OSError):
                pass

        import uvicorn
        from app.main import app as fastapi_app, reset_lifecycle_state, set_shutdown_callback

        reset_lifecycle_state()
        port = find_free_port(DEFAULT_PORT)

        def _cleanup_port_file() -> None:
            try:
                if port_file.is_file() and port_file.read_text(encoding="utf-8").strip() == str(port):
                    port_file.unlink(missing_ok=True)
            except OSError:
                pass

        atexit.register(_cleanup_port_file)

        uvi_config = uvicorn.Config(
            app=fastapi_app,
            host=HOST,
            port=port,
            workers=1,
            reload=False,
            log_config=None,
            access_log=False,
        )
        server = uvicorn.Server(uvi_config)

        def _trigger_quit() -> None:
            def _delayed_stop() -> None:
                time.sleep(0.15)
                _cleanup_port_file()
                server.should_exit = True

            threading.Thread(target=_delayed_stop, daemon=True).start()

        set_shutdown_callback(_trigger_quit)

        ready_event = threading.Event()
        ready_thread = threading.Thread(
            target=_wait_and_announce,
            args=(port, port_file, data_dir, ready_event),
            daemon=True,
        )
        ready_thread.start()

        watchdog_thread = threading.Thread(
            target=_watchdog_loop,
            args=(server, port_file, ready_event, _cleanup_port_file),
            daemon=True,
        )
        watchdog_thread.start()

        try:
            server.run()
        finally:
            _cleanup_port_file()
        return 0

    except KeyboardInterrupt:
        _safe_print("\nShutting down Leaf Area & LAI Analyzer.")
        return 0
    except Exception as exc:
        try:
            if log_file is None:
                log_file = configure_file_logging(user_data_dir())
            logging.getLogger("launcher").exception("Fatal startup error: %s", exc)
        except Exception:
            pass

        tb_str = traceback.format_exc()
        _safe_print("\n============================================================", err=True)
        _safe_print(
            f"ERROR: Leaf Area & LAI Analyzer v{config.SOFTWARE_VERSION} failed to start.",
            err=True,
        )
        _safe_print(f"Details: {exc}", err=True)
        if log_file is not None:
            _safe_print(f"Log file: {log_file}", err=True)
        _safe_print(tb_str, err=True)
        _safe_print("============================================================", err=True)

        show_visible_message(
            f"Leaf Area & LAI Analyzer v{config.SOFTWARE_VERSION} failed to start:\n\n{exc}",
            log_file=log_file,
            is_error=True,
        )
        return 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
