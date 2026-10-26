# -*- mode: python ; coding: utf-8 -*-
"""Cross-platform PyInstaller one-folder specification for LeafArea & LAI Analyzer."""

from pathlib import Path
import re
import sys

SPEC_DIR = Path(SPECPATH).resolve()

# Read single-source version from app/config.py
config_text = (SPEC_DIR / "app" / "config.py").read_text(encoding="utf-8")
ver_match = re.search(r'SOFTWARE_VERSION:\s*Final\[str\]\s*=\s*"([^"]+)"', config_text)
SOFTWARE_VERSION = ver_match.group(1) if ver_match else "1.5.0"
ver_parts = [int(x) for x in (SOFTWARE_VERSION.split(".") + ["0", "0", "0"])[:4]]
ver_tuple = tuple(ver_parts)

# Generate Windows VSVersionInfo resource file dynamically from SOFTWARE_VERSION
build_dir = SPEC_DIR / "build"
build_dir.mkdir(parents=True, exist_ok=True)
version_info_path = build_dir / "version_info.txt"
version_info_path.write_text(
    f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={ver_tuple},
    prodvers={ver_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'Scientific Leaf Area Research Project'),
        StringStruct('FileDescription', 'LeafArea & LAI Analyzer v{SOFTWARE_VERSION}'),
        StringStruct('FileVersion', '{SOFTWARE_VERSION}'),
        StringStruct('InternalName', 'LeafAreaAnalyzer'),
        StringStruct('LegalCopyright', 'MIT License'),
        StringStruct('OriginalFilename', 'LeafAreaAnalyzer.exe'),
        StringStruct('ProductName', 'LeafArea & LAI Analyzer'),
        StringStruct('ProductVersion', '{SOFTWARE_VERSION}')])
      ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
    encoding="utf-8",
)

datas = [
    (str(SPEC_DIR / "app" / "static"), "app/static"),
    (str(SPEC_DIR / "sample_images" / "01_clean_standard.png"), "sample_images"),
    (str(SPEC_DIR / "sample_images" / "01_clean_standard.json"), "sample_images"),
    (str(SPEC_DIR / "sample_images" / "02_leaf_with_hole.png"), "sample_images"),
    (str(SPEC_DIR / "sample_images" / "02_leaf_with_hole.json"), "sample_images"),
    (str(SPEC_DIR / "validation"), "validation"),
    (str(SPEC_DIR / "assets"), "assets"),
]
if (SPEC_DIR / "README_USER.md").exists():
    datas.append((str(SPEC_DIR / "README_USER.md"), "."))

hiddenimports = [
    "app",
    "app.main",
    "app.config",
    "app.paths",
    "app.export",
    "app.pipeline",
    "app.pipeline.loader",
    "app.pipeline.calibration",
    "app.pipeline.segmentation",
    "app.pipeline.measurement",
    "app.pipeline.lai",
    "app.pipeline.quality",
    "uvicorn",
    "uvicorn.config",
    "uvicorn.main",
    "uvicorn.server",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "anyio",
    "anyio._backends",
    "anyio._backends._asyncio",
    "sniffio",
    "h11",
    "click",
    "starlette",
    "starlette.applications",
    "starlette.routing",
    "starlette.responses",
    "starlette.staticfiles",
    "starlette.middleware",
    "starlette.middleware.base",
    "starlette.formparsers",
    "starlette.datastructures",
    "fastapi",
    "fastapi.staticfiles",
    "fastapi.responses",
    "pydantic",
    "pydantic.json",
    "pydantic.typing",
    "pydantic.validators",
    "multipart",
    "multipart.multipart",
    "cv2",
    "numpy",
    "scipy",
    "scipy._lib.messagestream",
    "scipy.special",
    "scipy.special._ufuncs_cxx",
    "scipy.linalg",
    "scipy.ndimage",
    "skimage",
    "skimage.filters",
    "skimage.filters.thresholding",
    "skimage.morphology",
    "skimage.measure",
    "pandas",
    "pandas._libs.tslibs.timedeltas",
    "pandas._libs.tslibs.nattype",
    "pandas._libs.tslibs.np_datetime",
    "openpyxl",
    "openpyxl.cell._writer",
    "et_xmlfile",
    "PIL",
    "PIL.Image",
    "PIL.ImageOps",
    "PIL.ExifTags",
]

excludes = [
    "tkinter",
    "_tkinter",
    "matplotlib",
    "IPython",
    "pytest",
    "_pytest",
    "jedi",
    "sphinx",
    "docutils",
    "pygments",
    "notebook",
    "jupyter",
    "wx",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "cupy",
    "torch",
    "tensorflow",
    "onnxruntime",
    "ortools",
    "geopandas",
    "pyarrow",
    "fastparquet",
    "weasyprint",
    "reportlab",
    "selenium",
    "moviepy",
    "av",
    "aiortc",
    "seaborn",
]

is_windows = sys.platform == "win32"
icon_file = str(SPEC_DIR / "assets" / ("icon.ico" if is_windows else "icon.png"))
win_version_file = str(version_info_path) if is_windows else None

block_cipher = None

a = Analysis(
    [str(SPEC_DIR / "launcher.py")],
    pathex=[str(SPEC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Section 4.1: console=False on Windows (no console window), console=True on Linux
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LeafAreaAnalyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=not is_windows,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=win_version_file,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LeafAreaAnalyzer",
)
