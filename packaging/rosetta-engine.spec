# PyInstaller spec: Rosetta engine as a single-file sidecar binary.
# Build: packaging/build-sidecar.sh (runs `pyinstaller packaging/rosetta-engine.spec`).
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

SPEC_DIR = SPECPATH  # noqa: F821 (provided by PyInstaller)

datas = collect_data_files("rosetta_engine", include_py_files=False)
binaries = []
hiddenimports = collect_submodules("rosetta_engine")  # commands/* are discovered via pkgutil

for pkg in ("pymupdf", "simplemma", "fsrs"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += collect_submodules("uvicorn") + collect_submodules("fastapi")
hiddenimports += ["anyio._backends._asyncio", "h11"]

a = Analysis(  # noqa: F821
    [f"{SPEC_DIR}/launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "mypy", "ruff", "IPython", "matplotlib", "numpy.testing"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="rosetta-engine",
    debug=False,
    strip=True,
    upx=False,
    console=True,
    runtime_tmpdir=None,
)
