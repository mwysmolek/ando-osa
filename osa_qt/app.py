"""kayEi SpectrumStudio desktop application (PySide6).

    python -m osa_qt.app [trace.csv …] [--simulate] [--smoke] [--new-instance]

One running copy per user: starting it again (or opening a CSV with it) hands the file to
the running window – two copies would fight over the GPIB bus.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from ando_osa import APP_NAME, APP_SLUG, ORG_NAME

from . import theme
from .mainwindow import MainWindow

SERVER = f"{APP_SLUG}-" + (os.environ.get("USERNAME") or os.environ.get("USER") or "user")
SMOKE_TIMEOUT_MS = 60000


def _hand_over(paths: list[str]) -> bool:
    """Give the files to an already running copy. True if one took them."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER)
    if not sock.waitForConnected(300):
        return False
    sock.write("\n".join(paths).encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


def _install_hooks(win: MainWindow) -> None:
    """Unexpected exceptions in slots and threads: logged (the log file when frozen) and
    shown in the window – never swallowed."""
    import threading
    import traceback

    def excepthook(tp, val, tb):
        text = "".join(traceback.format_exception(tp, val, tb))
        logging.getLogger("osa_qt").error("unhandled exception:\n%s", text)
        try:
            QTimer.singleShot(0, lambda: win.report_exception(text))
        except RuntimeError:
            pass

    def thread_hook(args):
        if args.exc_type is not SystemExit:
            excepthook(args.exc_type, args.exc_value, args.exc_traceback)
    sys.excepthook = excepthook
    threading.excepthook = thread_hook


def _hard_exit(code: int) -> None:
    """End the process right now with an exact exit code, skipping the Python / Qt
    teardown (threads still polling the bus, PySide's own exit crash)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001
            pass
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.TerminateProcess(ctypes.c_void_p(-1), ctypes.c_uint(code))
        except Exception:  # noqa: BLE001
            pass
    os._exit(code)


def main(argv: list[str] | None = None, hard_exit: bool = True) -> int:
    argv = list(sys.argv if argv is None else argv)
    flags = {a for a in argv[1:] if a.startswith("--")}
    files = [str(Path(a).resolve()) for a in argv[1:] if not a.startswith("--")]
    smoke = "--smoke" in flags
    simulate = smoke or "--simulate" in flags
    if not smoke and "--new-instance" not in flags and _hand_over(files):
        return 0

    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    theme.apply_theme(app)
    win = MainWindow()
    if smoke:                              # no network, no dialogs in the self-test
        win.store.set_pref("update_check", False)
    _install_hooks(win)

    server = QLocalServer()
    QLocalServer.removeServer(SERVER)
    if server.listen(SERVER):
        def on_conn():
            sock = server.nextPendingConnection()
            if sock is None:
                return
            sock.waitForReadyRead(500)
            data = bytes(sock.readAll()).decode("utf-8", "replace").strip()
            win.showNormal()
            win.raise_()
            win.activateWindow()
            for p in data.splitlines():
                if p.strip():
                    win.import_csv(p.strip())
        server.newConnection.connect(on_conn)

    win.show()
    win.start(files, simulate=simulate)
    if smoke:                              # CI: the window must come up and a sweep must deliver a trace + results
        def check():
            t = win.panel.active_trace
            ok = t in win.traces and bool(win.results.get(t))
            print("SMOKE-QT OK" if ok else "SMOKE-QT FAIL: no sweep result", flush=True)
            _hard_exit(0 if ok else 3)
        QTimer.singleShot(SMOKE_TIMEOUT_MS, check)
        win.resultsChanged.connect(lambda: QTimer.singleShot(800, check))
        QTimer.singleShot(500, win.start_sweep)
    code = app.exec()
    try:
        server.close()
        QLocalServer.removeServer(SERVER)
    except Exception:  # noqa: BLE001
        pass
    if hard_exit:
        _hard_exit(code)
    return code


if __name__ == "__main__":
    sys.exit(main())
