"""Grab the app's pages offscreen into docs/img/*.png, using the simulator.

    QT_QPA_PLATFORM=offscreen python docs/make_screenshots.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "img"


def wait(pred, seconds=60.0):
    from PySide6.QtCore import QCoreApplication
    t0 = time.time()
    while time.time() - t0 < seconds:
        QCoreApplication.processEvents()
        if pred():
            return True
        time.sleep(0.02)
    return False


def settle(seconds=1.0):
    wait(lambda: False, seconds)


def main() -> int:
    home = tempfile.mkdtemp(prefix="kayei_osa_shots_")
    os.environ["KAYEI_OSA_HOME"] = home
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from ando_osa.simulator import SimulatedOSA
    from ando_osa.storage import Store
    from osa_qt import theme
    from osa_qt.mainwindow import MainWindow
    app = QApplication.instance() or QApplication(["shots"])
    theme.apply_theme(app)
    OUT.mkdir(parents=True, exist_ok=True)
    store = Store(home)
    store.update_prefs({"update_check": False, "auto_connect": False})
    QSettings("kayEi", "SpectrumStudio").clear()
    win = MainWindow(store)
    win.resize(1500, 950)
    win.show()
    win.start()
    win._adopt(SimulatedOSA(seed=7, sweep_seconds=0.3))
    win.panel.start.setValue(1000)
    win.panel.stop.setValue(1200)
    for name in ("SNR", "SRS"):
        win.panel.flags[name].setChecked(True)
    win.panel.set_power_ranges([{"start": 1060.0, "stop": 1070.0}])
    win.page_log.level.setCurrentIndex(1)

    def shot(name: str, widget=None):
        settle(0.8)
        (widget or win).grab().save(str(OUT / f"{name}.png"))
        print("→", OUT / f"{name}.png")

    win.start_sweep()
    assert wait(lambda: "A" in win.traces and win.busy_mode is None), "no sweep"
    win.show_page("spectrum")
    shot("01_spectrum")
    page = win.page_timelapse
    page.interval.setValue(0.0)
    page.count.setValue(8)
    page.directory.setText(home)
    win.start_timelapse()
    assert wait(lambda: win.busy_mode is None and len(page.rows) == 8, 120), "time-lapse"
    shot("02_timelapse")
    win.show_page("log")
    shot("03_log")
    win.show_page("method")
    shot("04_method")
    win.show_page("spectrum")
    shot("00_window")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
