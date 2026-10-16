"""Build the kayEi SpectrumStudio desktop app with PyInstaller.

    pip install -r requirements-desktop.txt -r packaging/requirements-build.txt
    python packaging/build_exe.py               # -> dist/kayei_spectrumstudio/  (Windows: zip it = the portable build)
    python packaging/build_exe.py --bundle      # Linux: + dist/kayEi-SpectrumStudio-<ver>-linux-<arch>.tar.gz
Options: --onefile (single exe, slower start), --console (debug build with a console),
--sign-only (sign an existing dist/kayei_spectrumstudio/<exe> with $KAYEI_SIGN_CMD, "$f" = the file),
--bundle-only (pack an existing dist folder).

Must run on the target OS (PyInstaller does not cross-compile): the GitHub workflow
.github/workflows/build-windows.yml builds, self-tests, (optionally) signs and zips it on
Windows – there is no installer, the app runs from any folder.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packaging"
BUILD = ROOT / "build"
SEP = os.pathsep  # PyInstaller --add-data separator: ";" on Windows, ":" elsewhere
NAME = "kayei_spectrumstudio"
TITLE = "kayEi SpectrumStudio"
FILE_PREFIX = "kayEi-SpectrumStudio"


def version() -> str:
    text = (ROOT / "ando_osa" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def arch() -> str:
    import platform
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64"


def make_icon() -> Path:
    from PIL import Image
    img = Image.open(ROOT / "assets" / "logo.png").convert("RGBA")
    ico = PKG / "kayei.ico"
    img.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return ico


def version_file(ver: str) -> Path:
    """Windows 'Details' tab of the exe: product name, version, publisher."""
    nums = tuple((list(map(int, re.findall(r"\d+", ver))) + [0, 0, 0, 0])[:4])
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
          StringStruct('CompanyName', 'kayEi'),
          StringStruct('FileDescription', '{TITLE}'),
          StringStruct('FileVersion', '{ver}'),
          StringStruct('InternalName', '{NAME}'),
          StringStruct('OriginalFilename', '{NAME}.exe'),
          StringStruct('ProductName', '{TITLE}'),
          StringStruct('ProductVersion', '{ver}')])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"""
    BUILD.mkdir(exist_ok=True)
    path = BUILD / "version_info.txt"
    path.write_text(text, encoding="utf-8")
    return path


# not needed at runtime – keeps the app small (no WebEngine, no Qt modules the app never loads)
EXCLUDES = ("tkinter", "_tkinter", "PyQt5", "PyQt6", "pytest", "IPython", "PyInstaller", "notebook", "jupyter_client",
            "scipy", "pandas", "PIL.ImageQt", "matplotlib.tests", "numpy.tests",
            "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
            "PySide6.QtWebSockets", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
            "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
            "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
            "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtSensors",
            "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
            "PySide6.QtNfc", "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSql", "PySide6.QtStateMachine",
            "PySide6.QtTextToSpeech", "PySide6.QtUiTools", "PySide6.QtGraphs", "PySide6.QtHttpServer",
            "PySide6.QtSpatialAudio", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSvgWidgets",
            "PySide6.QtPrintSupport", "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtDBus", "PySide6.QtAsyncio")


def check_environment() -> None:
    """Fail early with the fix instead of a windowed exe that dies on its first import."""
    problems = []
    try:
        import PIL  # noqa: F401
    except ImportError:
        problems.append("Pillow is missing: pip install pillow")
    try:
        import PySide6
        import PySide6.QtWidgets  # noqa: F401
        if tuple(int(x) for x in PySide6.__version__.split(".")[:2]) >= (6, 12):
            problems.append(f"PySide6 {PySide6.__version__} crashes at exit (see requirements-build.txt): "
                            "pip install 'PySide6<6.12'")
    except ImportError as ex:
        problems.append(f"PySide6 is not importable ({ex}): pip install -r requirements-desktop.txt")
    for mod in ("matplotlib", "pyvisa", "pyvisa_py", "numpy"):
        try:
            __import__(mod)
        except ImportError:
            problems.append(f"{mod} is missing: pip install -r requirements-desktop.txt")
    if problems:
        raise SystemExit("cannot build:\n- " + "\n- ".join(problems))


def build_app(onefile: bool, console: bool) -> None:
    check_environment()
    import PyInstaller.__main__
    args = [
        str(PKG / "osa_desktop.py"),
        "--name", NAME,
        "--onefile" if onefile else "--onedir",
        "--noconfirm", "--clean",
        "--icon", str(make_icon()),
        *(["--version-file", str(version_file(version()))] if sys.platform == "win32" else []),
        "--paths", str(ROOT),
        "--add-data", f"{ROOT / 'assets'}{SEP}assets",
        "--add-data", f"{ROOT / 'CHANGELOG.md'}{SEP}.",
        "--hidden-import", "PySide6.QtNetwork",
        "--hidden-import", "matplotlib.backends.backend_qtagg", "--hidden-import", "matplotlib.backends.backend_agg",
        "--hidden-import", "pyvisa_py", "--collect-submodules", "pyvisa_py",     # pyvisa loads the @py backend by name
        "--collect-submodules", "ando_osa", "--collect-submodules", "osa_qt",
        "--copy-metadata", "pyvisa", "--copy-metadata", "pyvisa-py", "--copy-metadata", "numpy",
        "--copy-metadata", "matplotlib",
        *[x for m in EXCLUDES for x in ("--exclude-module", m)],
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(BUILD),
        "--specpath", str(BUILD),
        "--console" if console else "--windowed",
    ]
    PyInstaller.__main__.run(args)
    prune_extras(ROOT / "dist" / NAME)


def prune_extras(folder: Path) -> None:
    """Drop what the matplotlib hook bundles that the app never loads (sample data, tests)."""
    for rel in ("_internal/matplotlib/mpl-data/sample_data", "matplotlib/mpl-data/sample_data"):
        p = folder / rel
        try:
            if p.is_dir():
                shutil.rmtree(p)
        except OSError:
            pass


def sign_app(sign_cmd: str | None) -> Path:
    """Sign the app exe in place (before it is zipped) with a command such as CI's
    ``signtool sign /f cert.pfx … $f`` – ``$f`` is replaced by the quoted path. Without a
    command the build stays unsigned (SmartScreen warns once)."""
    exe = ROOT / "dist" / NAME / f"{NAME}.exe"
    if not sign_cmd:
        print("no signing command: the app stays unsigned")
        return exe
    if not exe.exists():
        sys.exit(f"nothing to sign: {exe} does not exist (build first)")
    subprocess.run(sign_cmd.replace("$f", f'"{exe}"'), shell=True, check=True)
    print(f"signed: {exe}")
    return exe


def build_bundle() -> Path:
    """The downloadable package off Windows: a .tar.gz with a .desktop file (Linux; macOS
    gets the same archive of its app folder – not a supported target)."""
    ver, dist = version(), ROOT / "dist"
    folder = dist / NAME
    if sys.platform != "darwin":
        (folder / "kayei-spectrumstudio.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=kayEi SpectrumStudio\n"
            "Comment=Ando AQ63xx optical spectrum analyzer control\n"
            f"Exec=%k/../{NAME} %f\nIcon=kayei\nTerminal=false\nCategories=Science;Engineering;\n", encoding="utf-8")
        shutil.copy(ROOT / "assets" / "logo.png", folder / "kayei.png")
        (folder / "README.txt").write_text(
            "kayEi SpectrumStudio – portable Linux build.\n\nRun ./kayei_spectrumstudio (needs a desktop session; "
            "libxcb-cursor0, libegl1 and libxkbcommon0 on Debian/Ubuntu). GPIB needs a VISA backend: NI-VISA, or "
            "pyvisa-py with linux-gpib (bundled pyvisa-py handles TCPIP/USB/serial).\n"
            "Headless: ./kayei_spectrumstudio sweep --start 1000 --stop 1500 --out trace.csv\n"
            "Try it without hardware: ./kayei_spectrumstudio --simulate\n", encoding="utf-8")
    label = "macOS" if sys.platform == "darwin" else "linux"
    out = dist / f"{FILE_PREFIX}-{ver}-{label}-{arch()}.tar.gz"
    out.unlink(missing_ok=True)
    subprocess.run(["tar", "-C", str(dist), "-czf", str(out), NAME if sys.platform != "darwin" else f"{NAME}.app"],
                   check=True)
    print(f"bundle: {out}")
    return out


def main() -> None:
    argv = sys.argv[1:]
    if not {"--sign-only", "--bundle-only"} & set(argv):   # (CI tests the app before signing / packing it)
        build_app(onefile="--onefile" in argv, console="--console" in argv)
    if "--sign-only" in argv:
        sign_app(os.environ.get("KAYEI_SIGN_CMD"))
    if {"--bundle", "--bundle-only"} & set(argv):
        build_bundle()


if __name__ == "__main__":
    main()
