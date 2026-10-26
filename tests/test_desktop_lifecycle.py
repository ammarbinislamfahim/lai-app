"""Tests for Section 1–6 click-to-open desktop launcher, watchdog auto-quit, browser app-mode, logs endpoint, and Linux installer."""

import io
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from fastapi.testclient import TestClient
import pytest

from app import config
from app.main import app, get_lifecycle_snapshot, reset_lifecycle_state

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = PROJECT_ROOT / "sample_images"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _launcher_env(extra: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{PROJECT_ROOT}{os.pathsep}{existing_pp}" if existing_pp else str(PROJECT_ROOT)
    env.update(extra)
    return env


def _wait_for_server(port_file: Path, timeout: float = 35.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_file.is_file():
            try:
                p = int(port_file.read_text(encoding="utf-8").strip())
                with urllib.request.urlopen(f"http://127.0.0.1:{p}/api/health", timeout=1.0) as resp:
                    if resp.status == 200:
                        return p
            except Exception:
                pass
        time.sleep(0.1)
    raise TimeoutError(f"Launcher did not become healthy and write {port_file} within {timeout}s")


def _post_empty(url: str, timeout: float = 5.0) -> dict:
    req = urllib.request.Request(url, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        assert resp.status == 200
        return json.loads(resp.read().decode("utf-8"))


def _multipart_post(url: str, file_bytes: bytes, filename: str, fields: dict[str, str], timeout: float = 30.0) -> dict:
    boundary = "----LeafAreaTestBoundary987654321"
    body = io.BytesIO()
    for k, v in fields.items():
        body.write(f"--{boundary}\r\n".encode("utf-8"))
        body.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"))
        body.write(f"{v}\r\n".encode("utf-8"))
    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'.encode("utf-8"))
    body.write(b"Content-Type: image/png\r\n\r\n")
    body.write(file_bytes)
    body.write(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    payload = body.getvalue()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(payload)),
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        assert resp.status == 200
        return json.loads(resp.read().decode("utf-8"))


def test_api_ping_bye_quit_logs_and_localhost_restriction(tmp_path: Path) -> None:
    """Verify /api/ping, /api/bye, /api/quit, /api/logs/latest (last 200 lines), and 127.0.0.1 enforcement."""
    reset_lifecycle_state()
    client = TestClient(app)

    # Create a 250-line app.log in a temporary user data dir
    os.environ["LEAFAREA_USER_DATA_DIR"] = str(tmp_path)
    try:
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "app.log"
        lines = [f"log-line-{i:03d}" for i in range(1, 251)]
        log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # 1. /api/logs/latest returns only the last 200 lines (051..250) as plain text
        r_logs = client.get("/api/logs/latest")
        assert r_logs.status_code == 200
        assert r_logs.headers["content-type"].startswith("text/plain")
        returned_lines = r_logs.text.strip().splitlines()
        assert len(returned_lines) == 200
        assert returned_lines[0] == "log-line-051"
        assert returned_lines[-1] == "log-line-250"

        # 2. /api/ping and /api/bye lifecycle state
        snap0 = get_lifecycle_snapshot()
        assert snap0["has_ever_connected"] is False
        assert snap0["active_client_count"] == 0

        r_ping = client.post("/api/ping?client_id=tab-1")
        assert r_ping.status_code == 200
        assert r_ping.json()["active_clients"] == 1
        snap1 = get_lifecycle_snapshot()
        assert snap1["has_ever_connected"] is True
        assert snap1["active_client_count"] == 1
        assert snap1["last_client_left_at"] is None

        r_bye = client.post("/api/bye?client_id=tab-1")
        assert r_bye.status_code == 200
        assert r_bye.json()["active_clients"] == 0
        snap2 = get_lifecycle_snapshot()
        assert snap2["has_ever_connected"] is True
        assert snap2["active_client_count"] == 0
        assert snap2["last_client_left_at"] is not None

        # 3. /api/quit sets quit_requested and returns "You can close this window"
        r_quit = client.post("/api/quit")
        assert r_quit.status_code == 200
        assert r_quit.json()["message"] == "You can close this window"
        assert get_lifecycle_snapshot()["quit_requested"] is True

        # 4. Non-localhost requests are rejected with 403 Forbidden
        for method, path in [
            ("POST", "/api/ping?client_id=ext"),
            ("POST", "/api/bye?client_id=ext"),
            ("POST", "/api/quit"),
            ("GET", "/api/logs/latest"),
        ]:
            resp = client.request(method, path, headers={"X-Forwarded-For": "192.168.1.50"})
            assert resp.status_code == 403, f"Expected 403 for {method} {path} from non-localhost"
    finally:
        os.environ.pop("LEAFAREA_USER_DATA_DIR", None)
        reset_lifecycle_state()


def test_1_and_2_ping_bye_refresh_within_8s_and_grace_exit(tmp_path: Path) -> None:
    """Section 6.1 & 6.2:
    - A bye followed by a ping within 8 seconds must NOT quit (simulates a page refresh).
    - After the final bye, the process exits cleanly after the grace time and port.txt is removed.
    """
    user_data = tmp_path / "userdata_refresh"
    port = _find_free_port()
    env = _launcher_env(
        {
            "LEAFAREA_USER_DATA_DIR": str(user_data),
            "LEAFAREA_PORT": str(port),
            "LEAFAREA_NO_BROWSER": "1",
            "LEAFAREA_NONINTERACTIVE": "1",
            "LEAFAREA_WATCHDOG_INTERVAL_SEC": "0.3",
            "LEAFAREA_GRACE_PERIOD_SEC": "8.0",
            "LEAFAREA_STARTUP_TIMEOUT_SEC": "60.0",
        }
    )

    proc = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "launcher.py")],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        port_file = user_data / "port.txt"
        active_port = _wait_for_server(port_file)
        base_url = f"http://127.0.0.1:{active_port}"

        # Simulate initial page load
        _post_empty(f"{base_url}/api/ping?client_id=page-1")
        # Simulate page unload (refresh starts)
        _post_empty(f"{base_url}/api/bye?client_id=page-1")

        # Wait 2.5 seconds (within the 8-second grace window) and send ping from reloaded page
        time.sleep(2.5)
        assert proc.poll() is None, "Launcher exited prematurely during grace period!"
        _post_empty(f"{base_url}/api/ping?client_id=page-2")

        # Wait another 6.5 seconds (total 9.0 seconds after the first bye, past the 8s window)
        time.sleep(6.5)
        assert proc.poll() is None, "Launcher quit despite a refresh ping within 8 seconds!"
        with urllib.request.urlopen(f"{base_url}/api/health", timeout=2.0) as r_h:
            assert r_h.status == 200

        # Now close the window for real (send bye and do not ping again)
        bye_time = time.monotonic()
        _post_empty(f"{base_url}/api/bye?client_id=page-2")

        # Must still be alive 4 seconds after bye (since grace period is 8s)
        time.sleep(4.0)
        assert proc.poll() is None, "Launcher exited before the 8s grace period elapsed!"

        # Wait for clean exit after the 8s grace period
        exit_code = proc.wait(timeout=8.0)
        elapsed = time.monotonic() - bye_time
        assert exit_code == 0
        assert elapsed >= 7.5, f"Expected exit after ~8s grace period, exited after {elapsed:.2f}s"
        assert not port_file.exists(), "port.txt must be deleted on clean shutdown"
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5.0)


def test_3_in_progress_analyze_prevents_exit_until_complete(tmp_path: Path) -> None:
    """Section 6.3: An in-progress /api/analyze request must prevent exit until it completes."""
    user_data = tmp_path / "userdata_analyze"
    port = _find_free_port()
    env = _launcher_env(
        {
            "LEAFAREA_USER_DATA_DIR": str(user_data),
            "LEAFAREA_PORT": str(port),
            "LEAFAREA_NO_BROWSER": "1",
            "LEAFAREA_NONINTERACTIVE": "1",
            "LEAFAREA_WATCHDOG_INTERVAL_SEC": "0.2",
            "LEAFAREA_GRACE_PERIOD_SEC": "1.0",
            "LEAFAREA_STARTUP_TIMEOUT_SEC": "60.0",
            "LEAFAREA_TEST_ANALYZE_DELAY_SEC": "2.5",
        }
    )

    proc = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "launcher.py")],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        port_file = user_data / "port.txt"
        active_port = _wait_for_server(port_file)
        base_url = f"http://127.0.0.1:{active_port}"

        _post_empty(f"{base_url}/api/ping?client_id=client-analyze")

        img_bytes = (SAMPLE_DIR / "01_clean_standard.png").read_bytes()
        analyze_result: dict = {}
        analyze_error: list[Exception] = []

        def _run_analyze() -> None:
            try:
                res = _multipart_post(
                    f"{base_url}/api/analyze",
                    img_bytes,
                    "01_clean_standard.png",
                    {"calibration_side_cm": "2.0", "calibration_color": "blue"},
                )
                analyze_result.update(res)
            except Exception as exc:
                analyze_error.append(exc)

        worker = threading.Thread(target=_run_analyze)
        worker.start()

        # Give /api/analyze 0.25s to enter the handler, then send bye
        time.sleep(0.25)
        _post_empty(f"{base_url}/api/bye?client_id=client-analyze")

        # Wait 1.6s (well past the 1.0s grace period, while /api/analyze is still sleeping 2.5s)
        time.sleep(1.6)
        assert proc.poll() is None, "Launcher exited while /api/analyze was still in progress!"

        worker.join(timeout=20.0)
        assert not analyze_error, f"/api/analyze failed: {analyze_error}"
        assert analyze_result["images"][0]["total_area_cm2"] == pytest.approx(48.0464, abs=1e-3)

        # Once /api/analyze finishes, watchdog exits cleanly
        exit_code = proc.wait(timeout=6.0)
        assert exit_code == 0
        assert not port_file.exists()
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5.0)


def test_4_no_client_connecting_exits_after_startup_timeout(tmp_path: Path) -> None:
    """Section 6.4: No client ever connecting must exit after the startup timeout."""
    user_data = tmp_path / "userdata_startup_timeout"
    port = _find_free_port()
    env = _launcher_env(
        {
            "LEAFAREA_USER_DATA_DIR": str(user_data),
            "LEAFAREA_PORT": str(port),
            "LEAFAREA_NO_BROWSER": "1",
            "LEAFAREA_NONINTERACTIVE": "1",
            "LEAFAREA_WATCHDOG_INTERVAL_SEC": "0.2",
            "LEAFAREA_STARTUP_TIMEOUT_SEC": "1.8",
        }
    )

    proc = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "launcher.py")],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        port_file = user_data / "port.txt"
        _wait_for_server(port_file)

        # Do NOT send any /api/ping; wait for startup timeout
        exit_code = proc.wait(timeout=6.0)
        assert exit_code == 0
        assert not port_file.exists()

        log_text = (user_data / "logs" / "app.log").read_text(encoding="utf-8")
        assert "No browser client connected within" in log_text
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5.0)


def test_5_second_launch_opens_browser_with_port_and_exits(tmp_path: Path) -> None:
    """Section 6.5 & Section 1:
    A second launch while the first is running must only open the browser (with port and isolated profile)
    and exit with code 0, starting no second server.
    """
    user_data = tmp_path / "userdata_single_instance"
    port = _find_free_port()

    # Create a mock browser executable to capture arguments passed by launcher.py
    browser_log = tmp_path / "browser_invocations.txt"
    if sys.platform == "win32":
        # A bash script cannot be executed by CreateProcess on Windows; use a .cmd batch file instead.
        mock_browser = tmp_path / "mock-chromium.cmd"
        mock_browser.write_text(
            f'@echo off\r\necho %* >> "{browser_log}"\r\n',
            encoding="utf-8",
        )
    else:
        mock_browser = tmp_path / "mock-chromium.sh"
        mock_browser.write_text(
            f"#!/usr/bin/env bash\necho \"$@\" >> \"{browser_log}\"\n",
            encoding="utf-8",
        )
        mock_browser.chmod(0o755)

    env1 = _launcher_env(
        {
            "LEAFAREA_USER_DATA_DIR": str(user_data),
            "LEAFAREA_PORT": str(port),
            "LEAFAREA_NO_BROWSER": "1",
            "LEAFAREA_NONINTERACTIVE": "1",
            "LEAFAREA_WATCHDOG_INTERVAL_SEC": "0.3",
            "LEAFAREA_GRACE_PERIOD_SEC": "1.0",
        }
    )

    proc1 = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "launcher.py")],
        cwd=str(PROJECT_ROOT),
        env=env1,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        port_file = user_data / "port.txt"
        active_port = _wait_for_server(port_file)
        base_url = f"http://127.0.0.1:{active_port}"
        _post_empty(f"{base_url}/api/ping?client_id=primary-client")

        # Launch second instance with LEAFAREA_BROWSER=mock_browser
        env2 = env1.copy()
        env2.pop("LEAFAREA_NO_BROWSER", None)
        env2["LEAFAREA_BROWSER"] = str(mock_browser)

        proc2 = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "launcher.py")],
            cwd=str(PROJECT_ROOT),
            env=env2,
            capture_output=True,
            text=True,
            timeout=20.0,
        )
        assert proc2.returncode == 0
        assert f"already running at http://127.0.0.1:{active_port}" in proc2.stdout
        assert int(port_file.read_text(encoding="utf-8").strip()) == active_port

        # Wait briefly for async Popen of mock_browser to flush browser_log
        for _ in range(100):
            if browser_log.is_file() and browser_log.read_text(encoding="utf-8").strip():
                break
            time.sleep(0.05)

        assert browser_log.is_file()
        logged_args = browser_log.read_text(encoding="utf-8").strip()
        assert f"--app=http://127.0.0.1:{active_port}" in logged_args
        assert f"--user-data-dir={user_data / 'browser-profile'}" in logged_args
        assert "--no-first-run" in logged_args

        # Shut down first server via /api/quit
        _post_empty(f"{base_url}/api/quit")
        assert proc1.wait(timeout=6.0) == 0
        assert not port_file.exists()
    finally:
        if proc1.poll() is None:
            proc1.terminate()
            proc1.wait(timeout=5.0)


def test_6_install_and_uninstall_linux_scripts(tmp_path: Path) -> None:
    """Section 6.6: install_linux.sh with temporary HOME creates .desktop file (validated if desktop-file-validate is available) and uninstall_linux.sh removes everything."""
    if not sys.platform.startswith("linux"):
        return

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir(parents=True)

    staging = tmp_path / "release_extract"
    bundle_dir = staging / "LeafAreaAnalyzer"
    (bundle_dir / "_internal" / "assets").mkdir(parents=True)

    # Create a lightweight executable and copy real icon.png into staging bundle
    exe_file = bundle_dir / "LeafAreaAnalyzer"
    exe_file.write_text("#!/usr/bin/env bash\necho 'LeafAreaAnalyzer mock'\n", encoding="utf-8")
    exe_file.chmod(0o755)
    shutil.copy2(PROJECT_ROOT / "assets" / "icon.png", bundle_dir / "_internal" / "assets" / "icon.png")
    shutil.copy2(PROJECT_ROOT / "install_linux.sh", staging / "install_linux.sh")
    shutil.copy2(PROJECT_ROOT / "uninstall_linux.sh", staging / "uninstall_linux.sh")
    (staging / "install_linux.sh").chmod(0o755)
    (staging / "uninstall_linux.sh").chmod(0o755)

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["ALLOW_ROOT_INSTALL"] = "1"

    # Run install_linux.sh answering "y" to Desktop shortcut prompt
    res_install = subprocess.run(
        [str(staging / "install_linux.sh")],
        cwd=str(staging),
        env=env,
        input="y\n",
        capture_output=True,
        text=True,
        timeout=15.0,
        check=True,
    )
    assert "Leaf Area & LAI Analyzer installed!" in res_install.stdout

    installed_app = fake_home / ".local" / "opt" / "LeafAreaAnalyzer"
    installed_exe = installed_app / "LeafAreaAnalyzer"
    installed_icon = installed_app / "icon.png"
    desktop_entry = fake_home / ".local" / "share" / "applications" / "leaf-area-analyzer.desktop"
    desktop_shortcut = fake_home / "Desktop" / "leaf-area-analyzer.desktop"

    assert installed_exe.is_file() and os.access(installed_exe, os.X_OK)
    assert installed_icon.is_file()
    assert desktop_entry.is_file()
    assert desktop_shortcut.is_file()
    assert bool(desktop_shortcut.stat().st_mode & stat.S_IXUSR)

    desktop_content = desktop_entry.read_text(encoding="utf-8")
    assert "Name=Leaf Area & LAI Analyzer" in desktop_content
    assert f'Exec="{installed_exe}"' in desktop_content
    assert f"Icon={installed_icon}" in desktop_content
    assert "Terminal=false" in desktop_content
    assert "Categories=Science;Education;" in desktop_content
    assert "StartupWMClass=LeafAreaAnalyzer" in desktop_content

    if shutil.which("desktop-file-validate"):
        val_res = subprocess.run(
            ["desktop-file-validate", str(desktop_entry)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert val_res.returncode == 0, f"desktop-file-validate failed: {val_res.stdout} {val_res.stderr}"

    # Create simulated user data directory
    user_data_dir_path = fake_home / ".local" / "share" / "LeafAreaAnalyzer"
    (user_data_dir_path / "logs").mkdir(parents=True)
    (user_data_dir_path / "logs" / "app.log").write_text("sample log\n", encoding="utf-8")

    # 1. Run uninstall_linux.sh answering "n" to keep user data
    subprocess.run(
        [str(staging / "uninstall_linux.sh")],
        cwd=str(staging),
        env=env,
        input="n\n",
        capture_output=True,
        text=True,
        timeout=15.0,
        check=True,
    )
    assert not installed_app.exists()
    assert not desktop_entry.exists()
    assert not desktop_shortcut.exists()
    assert user_data_dir_path.is_dir(), "User data dir should be preserved when user answers 'n'"

    # 2. Run uninstall_linux.sh answering "y" to remove user data directory
    res_uninst_purge = subprocess.run(
        [str(staging / "uninstall_linux.sh")],
        cwd=str(staging),
        env=env,
        input="y\n",
        capture_output=True,
        text=True,
        timeout=15.0,
        check=True,
    )
    assert "Removed user data directory" in res_uninst_purge.stdout
    assert not user_data_dir_path.exists()
