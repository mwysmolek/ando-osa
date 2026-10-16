"""Entry point of the packaged desktop app (PyInstaller): kayei_spectrumstudio.exe.

    kayei_spectrumstudio [trace.csv …] [--simulate] [--smoke] [--new-instance]
    kayei_spectrumstudio sweep --start 1000 --stop 1500 --out trace.csv      (headless)
    kayei_spectrumstudio scan | analyze trace.csv | version

A windowed exe has no console, so output goes to the log file in the data folder; the
headless commands therefore work best with their file outputs (--out, --png, --json).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _log_to_file() -> None:
    if sys.stdout is not None and sys.stderr is not None:
        return
    home = Path(os.environ.get("KAYEI_OSA_HOME") or Path.home() / ".kayei_spectrumstudio")
    home.mkdir(parents=True, exist_ok=True)
    f = open(home / "kayei_spectrumstudio.log", "a", buffering=1, encoding="utf-8")  # noqa: SIM115
    sys.stdout = sys.stderr = f


def main() -> int:
    import multiprocessing
    multiprocessing.freeze_support()
    _log_to_file()
    try:
        import faulthandler
        faulthandler.enable(file=sys.stderr)   # a native crash leaves its stack in the log
    except Exception:  # noqa: BLE001 - a stream without a file descriptor
        pass
    try:
        from ando_osa.cli import COMMANDS, main as cli_main
        if len(sys.argv) > 1 and sys.argv[1] in COMMANDS and sys.argv[1] != "app":
            return cli_main(sys.argv[1:])      # relative paths are the caller's, not the bundle's
        if getattr(sys, "frozen", False):
            os.chdir(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        from osa_qt.app import main as app_main
        return app_main(sys.argv)
    except Exception:  # noqa: BLE001 - say what went wrong and stop, never hang
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
