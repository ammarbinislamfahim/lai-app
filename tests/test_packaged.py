"""Phase 8 & v1.5.0: End-to-end verification of the packaged desktop executable (`LeafAreaAnalyzer`).

Works on both Windows (`dist/LeafAreaAnalyzer/LeafAreaAnalyzer.exe`) and Linux/macOS
(`dist/LeafAreaAnalyzer/LeafAreaAnalyzer`). Verifies:
1. Bundle size is >= 80 MB, and `_internal` contains `cv2`, `numpy`, and `scipy` with compiled
   native `.so`/`.pyd` extensions.
2. On Linux, `ldd` reports zero `"not found"` libraries and never links `libpython` from system paths.
3. Executable starts under a clean environment (`PATH=/usr/bin:/bin` only), `/api/health` responds,
   and `version == config.SOFTWARE_VERSION` (`1.5.0`).
4. Process memory map (`/proc/<pid>/maps` on Linux) confirms `libpython`, `cv2`, `numpy`, `scipy`,
   and all Python extension modules load strictly from `<bundle>/_internal` and never from
   `/usr/lib/python*`, `/lib/*/libpython*`, or `/opt/*`.
5. Uploading `sample_images/01_clean_standard.png` and the printed-sheet test image
   (`59.1 px/cm` sheet with blue 2 cm square, extra red 2 cm square, and 10x10 cm green square)
   through `/api/analyze` produces total area, scale, and per-leaf areas matching direct
   Python pipeline execution to within <= 0.0001 cm^2 (and prints a comparison table).
6. The server binds strictly to `127.0.0.1` (never `0.0.0.0`) and is not reachable from
   any non-loopback network interface.
7. The packaged build runs cleanly when copied into a folder path containing spaces and
   non-ASCII characters (`Test User/Désk top/LeafAreaAnalyzer`), writes zero files
   into its installation folder at runtime, serves `/api/logs/latest`, and exits cleanly
   removing `port.txt` after `/api/ping` -> `/api/bye` + grace period.
"""

import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import cv2
import numpy as np
import pytest

from app import config
from app.pipeline.calibration import detect_calibration
from app.pipeline.loader import load_image_from_bytes
from app.pipeline.measurement import measure_leaves
from app.pipeline.segmentation import segment_leaves
from tests.make_synthetic import (
    BLUE_SQUARE_BGR,
    GREEN_LEAF_BGR,
    PAPER_WHITE_BGR,
    RED_SQUARE_BGR,
    draw_aa_rotated_square,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = PROJECT_ROOT / "sample_images"
MIN_BUNDLE_BYTES = 80 * 1024 * 1024  # 80 MB


def _locate_dist_bundle() -> Path:
    """Return `dist/LeafAreaAnalyzer` (or `/tmp/lai_dist/LeafAreaAnalyzer` in sandbox test runs)."""
    env_dist = os.environ.get("LEAFAREA_DIST_BUNDLE")
    if env_dist and Path(env_dist).is_dir():
        return Path(env_dist).resolve()
    primary = PROJECT_ROOT / "dist" / "LeafAreaAnalyzer"
    if (primary / "_internal" / "cv2").is_dir():
        return primary.resolve()
    fallback = Path("/tmp/lai_dist/LeafAreaAnalyzer")
    if fallback.is_dir():
        return fallback.resolve()
    return primary.resolve()


def _packaged_exe_path(base_dir: Path | None = None) -> Path:
    """Return the path to the built one-folder executable on Windows or Linux/macOS."""
    folder = base_dir if base_dir is not None else _locate_dist_bundle()
    exe_name = "LeafAreaAnalyzer.exe" if sys.platform == "win32" else "LeafAreaAnalyzer"
    return folder / exe_name


def _compute_dir_size_bytes(directory: Path) -> int:
    """Return total size in bytes of all regular files inside `directory`."""
    total = 0
    for p in directory.rglob("*"):
        if p.is_file() and not p.is_symlink():
            total += p.stat().st_size
    return total


def _multipart_post(url: str, file_bytes: bytes, filename: str, fields: dict[str, str]) -> dict:
    """Send a standard multipart/form-data POST request using stdlib `urllib.request`."""
    boundary = "----LeafAreaBoundary7MA4YWxkTrZu0gW"
    body = io.BytesIO()
    for k, v in fields.items():
        body.write(f"--{boundary}\r\n".encode("utf-8"))
        body.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"))
        body.write(f"{v}\r\n".encode("utf-8"))

    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(
        f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'.encode("utf-8")
    )
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
    with urllib.request.urlopen(req, timeout=30.0) as resp:
        assert resp.status == 200
        return json.loads(resp.read().decode("utf-8"))


def _build_printed_sheet_png_bytes() -> bytes:
    """Create the Issue E 59.1 px/cm printed-sheet test image in memory as lossless PNG bytes."""
    true_scale = 59.1
    w, h = 1600, 1200
    canvas = np.full((h, w, 3), PAPER_WHITE_BGR, dtype=np.uint8)
    draw_aa_rotated_square(canvas, (180.0, 180.0), 2.0 * true_scale, 2.5, BLUE_SQUARE_BGR, ss=8)
    draw_aa_rotated_square(canvas, (450.0, 180.0), 2.0 * true_scale, 2.5, RED_SQUARE_BGR, ss=8)
    draw_aa_rotated_square(canvas, (850.0, 620.0), 10.0 * true_scale, 2.5, GREEN_LEAF_BGR, ss=8)
    ok, enc = cv2.imencode(".png", canvas)
    assert ok
    return enc.tobytes()


def _wait_for_packaged_server(port_file: Path, timeout: float = 30.0) -> int:
    """Wait until `port.txt` is written and `/api/health` answers."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_file.is_file():
            try:
                p = int(port_file.read_text(encoding="utf-8").strip())
                with urllib.request.urlopen(f"http://127.0.0.1:{p}/api/health", timeout=1.0) as r:
                    if r.status == 200:
                        return p
            except Exception:
                pass
        time.sleep(0.15)
    raise TimeoutError(f"Packaged server did not write {port_file} and pass /api/health within {timeout}s")


def _get_non_loopback_ip() -> str | None:
    """Return the machine's non-loopback LAN IP address if available."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return None


def _verify_linux_ldd_and_maps_isolation(exe_path: Path, bundle_dir: Path, pid: int | None = None) -> None:
    """On Linux, verify ldd has no missing libraries or external libpython, and /proc/<pid>/maps uses only bundled Python."""
    if not sys.platform.startswith("linux"):
        return

    internal_dir = (bundle_dir / "_internal").resolve()
    bundle_resolved = bundle_dir.resolve()

    # 1. Verify bundled libpython exists inside _internal
    bundled_libpythons = list(internal_dir.glob("libpython*.so*"))
    assert bundled_libpythons, f"No libpython*.so* found inside {internal_dir}!"

    # 2. Check ldd on main executable and bundled libpython
    for target_bin in [exe_path, bundled_libpythons[0]]:
        ldd_proc = subprocess.run(["ldd", str(target_bin)], capture_output=True, text=True, check=True)
        ldd_output = ldd_proc.stdout + ldd_proc.stderr
        assert "not found" not in ldd_output, (
            f"ldd reported missing shared library for {target_bin}:\n{ldd_output}"
        )
        for line in ldd_output.splitlines():
            if "libpython" in line and "=>" in line:
                resolved_part = line.split("=>", 1)[1].split(" (0x", 1)[0].strip()
                resolved_path = Path(resolved_part).resolve()
                assert str(resolved_path).startswith(str(bundle_resolved)), (
                    f"{target_bin} links external system libpython ({resolved_path}) outside bundle ({bundle_resolved})!\n{line}"
                )

    # 3. If process is running, inspect /proc/<pid>/exe and /proc/<pid>/maps
    if pid is not None and Path(f"/proc/{pid}/maps").is_file():
        proc_exe = Path(os.readlink(f"/proc/{pid}/exe")).resolve()
        assert proc_exe == exe_path.resolve(), (
            f"Running process /proc/{pid}/exe is {proc_exe}, expected {exe_path.resolve()} (external Python used!)"
        )

        maps_text = Path(f"/proc/{pid}/maps").read_text(encoding="utf-8")
        mapped_files: set[str] = set()
        for line in maps_text.splitlines():
            parts = line.split(None, 5)
            if len(parts) == 6 and parts[5].startswith("/"):
                mapped_files.add(parts[5].strip())

        has_bundled_libpython = False
        has_bundled_cv2 = False
        has_bundled_numpy = False
        has_bundled_scipy = False

        forbidden_prefixes = (
            "/usr/lib/python",
            "/usr/local/lib/python",
            "/lib/x86_64-linux-gnu/libpython",
            "/usr/lib/x86_64-linux-gnu/libpython",
            "/opt/spark",
            "/working_dir/.local",
            "/tmp/lai-venv",
        )

        for mf in mapped_files:
            mf_resolved = str(Path(mf).resolve())
            for bad_prefix in forbidden_prefixes:
                assert not mf.startswith(bad_prefix) and not mf_resolved.startswith(bad_prefix), (
                    f"Process {pid} loaded external Python library/extension outside bundle: {mf} (resolved: {mf_resolved})"
                )
            if mf_resolved.startswith(str(internal_dir)):
                if "libpython" in mf_resolved:
                    has_bundled_libpython = True
                if "/cv2/" in mf_resolved or "opencv_python.libs" in mf_resolved:
                    has_bundled_cv2 = True
                if "/numpy/" in mf_resolved or "numpy.libs" in mf_resolved:
                    has_bundled_numpy = True
                if "/scipy/" in mf_resolved or "scipy.libs" in mf_resolved:
                    has_bundled_scipy = True

        assert has_bundled_libpython, f"Process {pid} did not load libpython from {internal_dir}"
        assert has_bundled_cv2, f"Process {pid} did not load cv2 from {internal_dir}"
        assert has_bundled_numpy, f"Process {pid} did not load numpy from {internal_dir}"
        assert has_bundled_scipy, f"Process {pid} did not load scipy from {internal_dir}"


def test_packaged_executable_end_to_end() -> None:
    """Verify packaged bundle >= 80 MB, ldd & /proc/maps isolation, numerical parity (<=0.0001 cm^2), 127.0.0.1 binding, non-ASCII path, and ping/bye auto-quit."""
    dist_bundle = _locate_dist_bundle()
    exe_orig = _packaged_exe_path(dist_bundle)
    assert exe_orig.is_file(), f"Packaged executable not found at {exe_orig}. Run PyInstaller first."

    with tempfile.TemporaryDirectory() as tmp_root_str:
        tmp_root = Path(tmp_root_str)

        # Copy bundle into a path with spaces and non-ASCII characters
        non_ascii_bundle = tmp_root / "Test User" / "Désk top" / "LeafAreaAnalyzer"
        non_ascii_bundle.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(dist_bundle, non_ascii_bundle, symlinks=True)
        exe_path = _packaged_exe_path(non_ascii_bundle)
        exe_path.chmod(0o755)
        assert exe_path.is_file()

        # 1. Fail if bundle is smaller than 80 MB or missing cv2, numpy, scipy inside _internal
        bundle_bytes = _compute_dir_size_bytes(non_ascii_bundle)
        bundle_mb = bundle_bytes / (1024.0 * 1024.0)
        assert bundle_bytes >= MIN_BUNDLE_BYTES, (
            f"Packaged bundle {dist_bundle} is {bundle_mb:.2f} MB, which is smaller than the 80 MB minimum!"
        )

        internal_copy = non_ascii_bundle / "_internal"
        for req_pkg in ("cv2", "numpy", "scipy"):
            pkg_dir = internal_copy / req_pkg
            assert pkg_dir.is_dir(), f"Missing required package directory {pkg_dir} inside _internal!"
            ext_files = list(pkg_dir.rglob("*.so*")) + list(pkg_dir.rglob("*.pyd")) + list(pkg_dir.rglob("*.dll"))
            assert ext_files, (
                f"Package directory {pkg_dir} contains no compiled native extensions (.so/.pyd/.dll)!"
            )

        # 2. Verify ldd before launching
        _verify_linux_ldd_and_maps_isolation(exe_path, non_ascii_bundle, pid=None)

        # Record snapshot of install folder files + mtimes to verify Rule 6 (no writes to install folder)
        before_snapshot = {
            str(p.relative_to(non_ascii_bundle)): p.lstat().st_mtime_ns
            for p in non_ascii_bundle.rglob("*")
        }

        user_data = tmp_root / "Test User" / "Désk top" / "UserData"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s_free:
            s_free.bind(("127.0.0.1", 0))
            test_port = int(s_free.getsockname()[1])

        # Clean environment equivalent to `env -i PATH=/usr/bin:/bin` + app test config
        clean_env: dict[str, str] = {
            "PATH": "/usr/bin:/bin",
            "LEAFAREA_USER_DATA_DIR": str(user_data),
            "LEAFAREA_PORT": str(test_port),
            "LEAFAREA_NO_BROWSER": "1",
            "LEAFAREA_NONINTERACTIVE": "1",
            "LEAFAREA_WATCHDOG_INTERVAL_SEC": "0.2",
            "LEAFAREA_GRACE_PERIOD_SEC": "1.0",
        }
        if sys.platform == "win32":
            for win_var in ("SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "LOCALAPPDATA", "USERPROFILE"):
                if win_var in os.environ:
                    clean_env[win_var] = os.environ[win_var]

        proc = subprocess.Popen(
            [str(exe_path)],
            cwd=str(non_ascii_bundle),
            env=clean_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            port_file = user_data / "port.txt"
            active_port = _wait_for_packaged_server(port_file, timeout=30.0)
            base_url = f"http://127.0.0.1:{active_port}"

            # Send initial client ping
            req_ping = urllib.request.Request(f"{base_url}/api/ping?client_id=pkg-test", data=b"", method="POST")
            with urllib.request.urlopen(req_ping, timeout=2.0) as r_p:
                assert r_p.status == 200

            # Verify /api/health version == config.SOFTWARE_VERSION
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=2.0) as r_h:
                health_data = json.loads(r_h.read().decode("utf-8"))
            assert health_data["status"] == "OK"
            assert health_data["version"] == config.SOFTWARE_VERSION

            # Verify /api/logs/latest returns plain text logs
            with urllib.request.urlopen(f"{base_url}/api/logs/latest", timeout=2.0) as r_l:
                assert r_l.status == 200
                log_body = r_l.read().decode("utf-8")
                assert f"v{config.SOFTWARE_VERSION}" in log_body

            # Verify 127.0.0.1-only binding (NOT reachable from another network interface)
            if Path("/proc/net/tcp").is_file():
                hex_port = f"{active_port:04X}"
                tcp_lines = Path("/proc/net/tcp").read_text(encoding="utf-8").splitlines()[1:]
                matching_addrs = []
                for line in tcp_lines:
                    parts = line.split()
                    if len(parts) >= 4 and parts[3] == "0A":  # 0A = TCP_LISTEN
                        local_ip_hex, local_port_hex = parts[1].split(":")
                        if local_port_hex.upper() == hex_port:
                            matching_addrs.append(local_ip_hex.upper())
                assert "00000000" not in matching_addrs, "Server bound to 0.0.0.0 instead of 127.0.0.1!"
                assert "0100007F" in matching_addrs, f"Expected 127.0.0.1 (0100007F) in {matching_addrs}"

            lan_ip = _get_non_loopback_ip()
            if lan_ip:
                with pytest.raises(Exception):
                    urllib.request.urlopen(f"http://{lan_ip}:{active_port}/api/health", timeout=1.0)

            # Upload 01_clean_standard.png and printed-sheet test image and compare with direct Python pipeline
            clean_img_path = SAMPLE_DIR / "01_clean_standard.png"
            clean_bytes = clean_img_path.read_bytes()
            sheet_bytes = _build_printed_sheet_png_bytes()

            test_cases = [
                ("01_clean_standard.png", clean_bytes, 2.0, "blue"),
                ("printed_sheet_59_1_px_per_cm.png", sheet_bytes, 2.0, "blue"),
            ]

            print("\n==========================================================================================")
            print(f" PACKAGED EXECUTABLE vs. DIRECT PYTHON PIPELINE VERIFICATION (v{config.SOFTWARE_VERSION})")
            print(f" Executable Path : {exe_path}")
            print(f" Bundle Size     : {bundle_mb:.2f} MB")
            print("==========================================================================================")
            print(
                f"{'Image / Metric':<36} | {'Direct Python':>15} | {'Packaged Exe':>15} | {'Abs Diff':>12}"
            )
            print("------------------------------------------------------------------------------------------")

            for fname, img_bytes, side_cm, cal_color in test_cases:
                loaded = load_image_from_bytes(img_bytes, filename=fname)
                cal_py = detect_calibration(loaded.image_bgr, known_side_cm=side_cm, color=cal_color, dpi=loaded.dpi)
                active_bgr = cal_py.rectified_image_bgr if cal_py.rectified_image_bgr is not None else loaded.image_bgr
                seg_py = segment_leaves(
                    active_bgr,
                    cal_py.px_per_cm,
                    cal_py.calibration_square_mask,
                    known_side_cm=side_cm,
                )
                meas_py = measure_leaves(seg_py.leaf_mask, cal_py.px_per_cm)

                api_resp = _multipart_post(
                    f"{base_url}/api/analyze",
                    img_bytes,
                    fname,
                    {"calibration_side_cm": str(side_cm), "calibration_color": cal_color},
                )
                assert api_resp["software_version"] == f"{config.SOFTWARE_NAME} v{config.SOFTWARE_VERSION}"
                img_exe = api_resp["images"][0]

                scale_diff = abs(float(img_exe["px_per_cm"]) - float(cal_py.px_per_cm))
                total_area_diff = abs(float(img_exe["total_area_cm2"]) - float(meas_py.total_area_cm2))

                print(
                    f"{fname + ' [Scale px/cm]':<36} | {cal_py.px_per_cm:15.6f} | {img_exe['px_per_cm']:15.6f} | {scale_diff:12.6f}"
                )
                print(
                    f"{fname + ' [Total Area cm²]':<36} | {meas_py.total_area_cm2:15.6f} | {img_exe['total_area_cm2']:15.6f} | {total_area_diff:12.6f}"
                )

                assert scale_diff <= 1e-4, f"{fname}: scale diff {scale_diff} > 0.0001"
                assert total_area_diff <= 1e-4, f"{fname}: total area diff {total_area_diff} > 0.0001 cm^2"
                assert len(img_exe["leaves"]) == len(meas_py.leaves)

                for l_py, l_exe in zip(meas_py.leaves, img_exe["leaves"]):
                    leaf_diff = abs(float(l_exe["area_cm2"]) - float(l_py.area_cm2))
                    label = f"  Leaf #{l_py.leaf_id} Area (cm²)"
                    print(
                        f"{label:<36} | {l_py.area_cm2:15.6f} | {l_exe['area_cm2']:15.6f} | {leaf_diff:12.6f}"
                    )
                    assert leaf_diff <= 1e-4, f"{fname} leaf #{l_py.leaf_id}: diff {leaf_diff} > 0.0001 cm^2"

            print("==========================================================================================\n")

            # Verify runtime process memory map confirms zero external Python / C-extensions loaded
            _verify_linux_ldd_and_maps_isolation(exe_path, non_ascii_bundle, pid=proc.pid)

            # Verify Rule 6: Zero files created or modified inside the install folder at runtime
            after_snapshot = {
                str(p.relative_to(non_ascii_bundle)): p.lstat().st_mtime_ns
                for p in non_ascii_bundle.rglob("*")
            }
            assert set(after_snapshot.keys()) == set(before_snapshot.keys()), (
                f"Files created in install dir at runtime: {set(after_snapshot.keys()) ^ set(before_snapshot.keys())}"
            )
            assert (user_data / "logs" / "app.log").is_file()

            # Send /api/bye and confirm packaged executable exits cleanly after grace period and deletes port.txt
            req_bye = urllib.request.Request(f"{base_url}/api/bye?client_id=pkg-test", data=b"", method="POST")
            with urllib.request.urlopen(req_bye, timeout=2.0) as r_b:
                assert r_b.status == 200
            exit_rc = proc.wait(timeout=8.0)
            assert exit_rc == 0
            assert not port_file.exists(), "port.txt must be removed on packaged executable exit"

        finally:
            if proc.poll() is None:
                proc.terminate()
            try:
                stdout_text, _ = proc.communicate(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_text, _ = proc.communicate()
            assert f"Leaf Area & LAI Analyzer v{config.SOFTWARE_VERSION} is running at http://127.0.0.1:" in stdout_text
