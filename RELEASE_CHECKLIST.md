# Release Checklist — LeafArea & LAI Analyzer

Follow every step below in order before publishing a new release tag (`vX.Y.Z`):

- [ ] **1. Single-Source Version Bump**
  - [ ] Bump `SOFTWARE_VERSION` in `app/config.py` (for example, `"1.4.0"`).
  - [ ] Update `version` and `date-released` in `CITATION.cff` to match `app/config.py`.
  - [ ] Verify no hardcoded old version strings remain in `README_USER.md` or `README.md`.

- [ ] **2. Dependency & Lock File Audit**
  - [ ] Confirm `.python-version` matches the target Python minor release (`3.11`).
  - [ ] Confirm all runtime dependencies in `requirements-lock.txt` and `requirements-build.txt` use exact `==` pins.

- [ ] **3. Local Accuracy, Memory & Packaging Verification (Kali Linux)**
  - [ ] Run `./build_linux.sh` and confirm:
    - [ ] All unit, calibration, segmentation, API, and 12 MP memory tests (`< 1 GB` peak) pass with 0 failures.
    - [ ] Mean clean synthetic bias is `< 0.05%` and all 76 synthetic scenes pass their error bounds.
    - [ ] `dist/LeafAreaAnalyzer-vX.Y.Z-linux-x86_64.tar.gz` and `.sha256` are generated.
  - [ ] Run `.venv/bin/pytest tests/test_packaged.py -v -s` and confirm:
    - [ ] Packaged binary reports `version == config.SOFTWARE_VERSION` on `/api/health`.
    - [ ] Packaged binary binds strictly to `127.0.0.1` (never `0.0.0.0`).
    - [ ] Total leaf area, scale, and per-leaf areas match direct Python execution within `<= 0.0001 cm²`.
    - [ ] Packaged binary runs cleanly from a path containing spaces and non-ASCII characters (`Test User/Désk top/`) and writes zero files to its installation folder.

- [ ] **4. Git Tag & GitHub Actions CI Build**
  - [ ] Commit all changes: `git add -A && git commit -m "Release vX.Y.Z"`
  - [ ] Push branch and tag: `git push origin main && git tag vX.Y.Z && git push origin vX.Y.Z`
  - [ ] Confirm `.github/workflows/build.yml` succeeds on `windows-latest` and `ubuntu-22.04`.

- [ ] **5. Post-Release Artifact Audit**
  - [ ] Confirm the GitHub Release page includes:
    - [ ] `LeafAreaAnalyzer-Setup-vX.Y.Z.exe` (Windows per-user installer)
    - [ ] `LeafAreaAnalyzer-vX.Y.Z-portable.zip` (Windows portable zip)
    - [ ] `LeafAreaAnalyzer-vX.Y.Z-linux-x86_64.tar.gz` (Linux archive)
    - [ ] `SHA256SUMS.txt` (combined SHA-256 checksums)
    - [ ] `packaged_test_windows.log` and `packaged_test_linux.log`
