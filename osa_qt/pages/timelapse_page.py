"""Time-lapse page: interval, count and folder; progress; the envelope and the peak trend;
one row per measurement."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton,
                               QSpinBox, QSplitter, QVBoxLayout, QWidget)
from PySide6.QtCore import Qt

from ando_osa.analysis import METRICS, format_value

from ..plot import TimeLapseCanvas, Toolbar
from ..widgets import Notice, Table, caption, section

COLUMNS = ["index", "time", "elapsed_s", "points", "Peak Wavelength", "Peak Level", "FWHM", "SNR", "SRS", "Total Power"]
TITLES = {"index": "#", "time": "Time", "elapsed_s": "Elapsed (s)", "points": "Points"}


def _hms(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


class TimeLapsePage(QWidget):
    startRequested = Signal()
    stopRequested = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        tl = store.get_pref("timelapse", {}) or {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(8)
        lay.addWidget(caption("Repeated sweeps of the active trace at a fixed interval. Every measurement is saved as "
                              "CSV + PNG (+ analysis) into a timestamped folder, with a summary.csv of all results."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Interval"))
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.0, 86400.0)
        self.interval.setDecimals(1)
        self.interval.setSuffix(" s")
        self.interval.setValue(float(tl.get("interval_s", 5.0)))
        self.interval.setToolTip("Pause between the end of one sweep and the start of the next")
        row.addWidget(self.interval)
        row.addWidget(QLabel("Measurements"))
        self.count = QSpinBox()
        self.count.setRange(1, 1000000)
        self.count.setValue(int(tl.get("count", 10)))
        row.addWidget(self.count)
        row.addWidget(QLabel("Folder"))
        self.directory = QLineEdit(str(tl.get("directory", "")))
        self.directory.setPlaceholderText("where the timelapse_<date> folder is created")
        row.addWidget(self.directory, 1)
        b_browse = QPushButton("Browse…")
        b_browse.clicked.connect(self._browse)
        row.addWidget(b_browse)
        self.b_start = QPushButton("▶ Start time-lapse")
        self.b_start.setProperty("primary", True)
        self.b_start.clicked.connect(self.startRequested)
        row.addWidget(self.b_start)
        self.b_stop = QPushButton("■ Stop")
        self.b_stop.setEnabled(False)
        self.b_stop.clicked.connect(self.stopRequested)
        row.addWidget(self.b_stop)
        lay.addLayout(row)

        self.notice = Notice("")
        lay.addWidget(self.notice)
        prow = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.bar.setTextVisible(True)
        self.bar.setFormat("%v / %m")
        prow.addWidget(self.bar, 1)
        self.status = caption("No time-lapse running.")
        prow.addWidget(self.status, 2)
        self.b_folder = QPushButton("Open folder")
        self.b_folder.setEnabled(False)
        self.b_folder.clicked.connect(self._open_folder)
        prow.addWidget(self.b_folder)
        lay.addLayout(prow)

        split = QSplitter(Qt.Vertical)
        plot_box = QWidget()
        pl = QVBoxLayout(plot_box)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        self.canvas = TimeLapseCanvas(plot_box)
        self.toolbar = Toolbar(self.canvas, plot_box)
        pl.addWidget(self.toolbar)
        pl.addWidget(self.canvas, 1)
        split.addWidget(plot_box)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(section("Measurements"))
        self.table = Table()
        self.table.export_name = "timelapse"
        bl.addWidget(self.table, 1)
        split.addWidget(bottom)
        split.setSizes([640, 200])
        lay.addWidget(split, 1)

        self.folder: Path | None = None
        self.rows: list[dict] = []
        self.runs: list[tuple[list, list]] = []
        self.total = 0

    # ---- settings ------------------------------------------------------------------------
    def settings(self) -> dict:
        directory = self.directory.text().strip()
        if not directory or not os.path.isdir(directory):
            raise ValueError("Choose an existing folder for the time-lapse first.")
        s = {"interval_s": float(self.interval.value()), "count": int(self.count.value()), "directory": directory}
        self.store.set_pref("timelapse", s)
        return s

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Time-lapse folder", self.directory.text() or str(Path.home()))
        if d:
            self.directory.setText(d)

    def _open_folder(self) -> None:
        if self.folder is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder)))

    # ---- run -----------------------------------------------------------------------------
    def begin(self, count: int, folder) -> None:
        self.folder = Path(folder)
        self.total = int(count)
        self.rows, self.runs = [], []
        self.bar.setRange(0, self.total)
        self.bar.setValue(0)
        self.status.setText(f"Started – saving to {self.folder}")
        self.notice.set("")
        self.b_folder.setEnabled(True)
        self.canvas.reset()
        self.table.set_rows([], COLUMNS, titles=TITLES)
        self.set_running(True)

    def set_running(self, running: bool) -> None:
        self.b_start.setEnabled(not running)
        self.b_stop.setEnabled(running)
        for w in (self.interval, self.count, self.directory):
            w.setEnabled(not running)

    def add_measurement(self, index: int, elapsed_s: float, wavelengths, levels, results: dict, interval_s: float) -> None:
        from datetime import datetime
        self.runs.append((wavelengths, levels))
        row = {"index": index + 1, "time": datetime.now().strftime("%H:%M:%S"), "elapsed_s": round(elapsed_s, 1),
               "points": len(wavelengths), **{k: results.get(k) for k in METRICS}}
        self.rows.append(row)
        fmt = {k: (lambda v, k=k: format_value(k, v)) for k in METRICS}
        fmt["elapsed_s"] = lambda v: f"{v:.1f}"
        self.table.set_rows(self.rows, COLUMNS, fmt=fmt, titles=TITLES)
        self.table.scrollToBottom()
        self.bar.setValue(index + 1)
        done = index + 1
        per = elapsed_s / done if done else 0.0
        remaining = (self.total - done) * max(per, interval_s)
        self.status.setText(f"{done} / {self.total} · elapsed {_hms(elapsed_s)} · about {_hms(remaining)} left · {self.folder}")
        t = [r["elapsed_s"] for r in self.rows]
        wl = [r.get("Peak Wavelength") for r in self.rows]
        lv = [r.get("Peak Level") for r in self.rows]
        have = all(v is not None for v in wl) and all(v is not None for v in lv)
        self.canvas.update_run(self.runs, t if have else [], wl if have else [], lv if have else [])

    def end(self, message: str = "") -> None:
        self.set_running(False)
        done = len(self.rows)
        self.status.setText(message or f"Finished: {done} of {self.total} measurement(s) in {self.folder}")
