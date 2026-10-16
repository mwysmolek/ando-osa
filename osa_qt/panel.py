"""The left dock: brand, the instrument connection, the sweep settings and the analysis
switches. Every setting is remembered in the data folder's settings.json."""
from __future__ import annotations

import webbrowser
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from ando_osa import APP_NAME, __version__
from ando_osa.analysis import FLAGS, normalize_options
from ando_osa.instrument import (PEAK_HOLD_MAX_MS, PEAK_HOLD_MIN_MS, RESOLUTIONS_NM, SENSITIVITY_MODES, TRACES,
                                 WAVELENGTH_MAX_NM, WAVELENGTH_MIN_NM, validate_sweep_range)

from . import theme as T
from .widgets import caption, heading, set_pill
from .workers import SweepParams

FLAG_LABELS = {"Peak Search": "Peak", "FWHM": "FWHM", "SNR": "SNR", "SRS": "SRS (anti-Stokes)", "Total Power": "Total power"}
FLAG_TIPS = {"Peak Search": "Wavelength and level of the global maximum",
             "FWHM": "Width between the outermost −3 dB crossings (interpolated) and its centre wavelength",
             "SNR": "Peak level minus the highest level outside ±10 nm around the peak",
             "SRS": "Peak level minus the maximum within ±5 nm of the anti-Stokes wavelength (13.2 THz Raman shift)",
             "Total Power": "10·log10 of the sum of the linear powers of all samples"}
SWEEP_DEFAULTS = {"start_nm": 1000.0, "stop_nm": 1500.0, "resolution": "0.1", "sensitivity": "SMID", "mode": "CW",
                  "peak_hold_ms": 100, "active_trace": "A", "continuous": False}


class InstrumentPanel(QWidget):
    connectRequested = Signal(str)          # resource name, or "" to scan and take the first Ando
    disconnectRequested = Signal()
    simulatorRequested = Signal()
    scanRequested = Signal()
    sweepRequested = Signal()
    stopRequested = Signal()
    settingsChanged = Signal()              # start / stop / resolution / sensitivity / continuous
    activeTraceChanged = Signal(str)
    measurementModeChanged = Signal()       # CW / pulsed / peak hold
    analysisChanged = Signal()              # flags, auto-analyse, overlays
    powerRangesRequested = Signal()
    installUpdate = Signal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._loading = True
        sweep = dict(SWEEP_DEFAULTS)
        sweep.update(store.get_pref("sweep", {}) or {})
        self._analysis = normalize_options(store.get_pref("analysis", {}) or {})
        self.resources: list[tuple[str, str]] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)
        brand_row = QHBoxLayout()
        logo = QLabel()
        pm = QPixmap(str(T.ASSETS / "logo.png"))
        if not pm.isNull():
            logo.setPixmap(pm.scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            brand_row.addWidget(logo)
        brand = QLabel(f'<span style="color:{T.ACCENT}; letter-spacing:2px; font-weight:700">kayEi</span>'
                       '<br><span style="font-size:20px; font-weight:800">SpectrumStudio</span>')
        brand_row.addWidget(brand, 1)
        lay.addLayout(brand_row)
        lay.addWidget(caption("Ando AQ63xx optical spectrum analyzer control"))

        # ---- instrument -------------------------------------------------------------------
        lay.addWidget(heading("Instrument"))
        self.conn = QLabel()
        self.conn.setProperty("pill", True)
        self.conn.setWordWrap(True)
        lay.addWidget(self.conn)
        self.idn = caption("")
        lay.addWidget(self.idn)
        row = QHBoxLayout()
        self.b_connect = QPushButton("Connect")
        self.b_connect.setProperty("primary", True)
        self.b_connect.setToolTip("Scan the VISA bus and connect to the first Ando OSA that answers *IDN?")
        self.b_connect.clicked.connect(self._connect_clicked)
        self.b_disconnect = QPushButton("Disconnect")
        self.b_disconnect.clicked.connect(self.disconnectRequested)
        row.addWidget(self.b_connect)
        row.addWidget(self.b_disconnect)
        lay.addLayout(row)
        self.resource = QComboBox()
        self.resource.setToolTip("Everything the scan found – pick one and press Connect when the automatic choice is wrong")
        self.resource.addItem("Automatic (first Ando found)", "")
        lay.addWidget(self.resource)
        row = QHBoxLayout()
        self.b_scan = QPushButton("Scan bus")
        self.b_scan.setToolTip("List the VISA resources without connecting")
        self.b_scan.clicked.connect(self.scanRequested)
        self.b_sim = QPushButton("Simulator")
        self.b_sim.setToolTip("No instrument at hand? A simulated OSA with a 1064 nm fibre laser spectrum")
        self.b_sim.clicked.connect(self.simulatorRequested)
        row.addWidget(self.b_scan)
        row.addWidget(self.b_sim)
        lay.addLayout(row)

        # ---- sweep ------------------------------------------------------------------------
        lay.addWidget(heading("Sweep"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)
        self.start = QDoubleSpinBox()
        self.stop = QDoubleSpinBox()
        for sp, v in ((self.start, sweep["start_nm"]), (self.stop, sweep["stop_nm"])):
            sp.setRange(WAVELENGTH_MIN_NM, WAVELENGTH_MAX_NM)
            sp.setDecimals(2)
            sp.setSuffix(" nm")
            sp.setSingleStep(10.0)
            sp.setKeyboardTracking(False)
            sp.setValue(float(v))
        grid.addWidget(QLabel("Start"), 0, 0)
        grid.addWidget(self.start, 0, 1)
        grid.addWidget(QLabel("Stop"), 1, 0)
        grid.addWidget(self.stop, 1, 1)
        self.res = QComboBox()
        self.res.addItems(RESOLUTIONS_NM)
        self.res.setCurrentText(str(sweep["resolution"]))
        grid.addWidget(QLabel("Resolution"), 2, 0)
        grid.addWidget(self.res, 2, 1)
        self.sens = QComboBox()
        for label, cmd in SENSITIVITY_MODES:
            self.sens.addItem(label, cmd)
        self.sens.setCurrentIndex(max(0, self.sens.findData(sweep["sensitivity"])))
        grid.addWidget(QLabel("Sensitivity"), 3, 0)
        grid.addWidget(self.sens, 3, 1)
        self.mode = QComboBox()
        self.mode.addItems(["CW", "Pulsed"])
        self.mode.setCurrentText("Pulsed" if sweep["mode"] == "Pulsed" else "CW")
        grid.addWidget(QLabel("Light"), 4, 0)
        grid.addWidget(self.mode, 4, 1)
        self.peak_hold_lab = QLabel("Peak hold")
        self.peak_hold = QSpinBox()
        self.peak_hold.setRange(PEAK_HOLD_MIN_MS, PEAK_HOLD_MAX_MS)
        self.peak_hold.setSuffix(" ms")
        self.peak_hold.setValue(int(sweep["peak_hold_ms"]))
        self.peak_hold.setKeyboardTracking(False)
        grid.addWidget(self.peak_hold_lab, 5, 0)
        grid.addWidget(self.peak_hold, 5, 1)
        self.active = QComboBox()
        for t in TRACES:
            self.active.addItem(f"Trace {t}", t)
        self.active.setCurrentIndex(max(0, self.active.findData(sweep["active_trace"])))
        self.active.setToolTip("The trace the sweep writes to and the analysis, Save and Quick save use")
        grid.addWidget(QLabel("Active trace"), 6, 0)
        grid.addWidget(self.active, 6, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        self.continuous = QCheckBox("Continuous (sweep until stopped)")
        self.continuous.setChecked(bool(sweep["continuous"]))
        lay.addWidget(self.continuous)
        row = QHBoxLayout()
        self.b_sweep = QPushButton("▶ Sweep")
        self.b_sweep.setProperty("primary", True)
        self.b_sweep.setToolTip("Start the sweep (F5)")
        self.b_sweep.clicked.connect(self.sweepRequested)
        self.b_stop = QPushButton("■ Stop")
        self.b_stop.setToolTip("Stop the sweep or time-lapse (Esc)")
        self.b_stop.setEnabled(False)
        self.b_stop.clicked.connect(self.stopRequested)
        row.addWidget(self.b_sweep, 1)
        row.addWidget(self.b_stop)
        lay.addLayout(row)

        # ---- analysis ---------------------------------------------------------------------
        lay.addWidget(heading("Analysis"))
        self.flags: dict[str, QCheckBox] = {}
        fgrid = QGridLayout()
        fgrid.setVerticalSpacing(3)
        for i, name in enumerate(FLAGS):
            cb = QCheckBox(FLAG_LABELS[name])
            cb.setToolTip(FLAG_TIPS[name])
            cb.setChecked(bool(self._analysis.get(name)))
            cb.toggled.connect(lambda _on, n=name: self._flag(n))
            self.flags[name] = cb
            fgrid.addWidget(cb, i // 2, i % 2)
        lay.addLayout(fgrid)
        self.b_ranges = QPushButton("Power content ranges…")
        self.b_ranges.clicked.connect(self.powerRangesRequested)
        lay.addWidget(self.b_ranges)
        self.auto = QCheckBox("Analyse after every sweep")
        self.auto.setChecked(bool(store.get_pref("auto_analyse", True)))
        lay.addWidget(self.auto)
        self.overlays = QCheckBox("Show markers on the plot")
        self.overlays.setChecked(bool(store.get_pref("show_overlays", True)))
        lay.addWidget(self.overlays)

        lay.addStretch(1)
        self.update_lab = QLabel()
        self.update_lab.setOpenExternalLinks(False)
        self.update_lab.linkActivated.connect(self._update_link)
        self.update_lab.setWordWrap(True)
        self.update_lab.hide()
        lay.addWidget(self.update_lab)
        lay.addWidget(caption(f"{APP_NAME} {__version__}"))

        for w in (self.start, self.stop):
            w.valueChanged.connect(lambda _v: self._sweep_changed())
        self.res.currentIndexChanged.connect(lambda _i: self._sweep_changed())
        self.sens.currentIndexChanged.connect(lambda _i: self._sweep_changed())
        self.continuous.toggled.connect(lambda _on: self._sweep_changed())
        self.mode.currentIndexChanged.connect(lambda _i: self._mode_changed())
        self.peak_hold.valueChanged.connect(lambda _v: self._mode_changed())
        self.active.currentIndexChanged.connect(lambda _i: self._active_changed())
        self.auto.toggled.connect(lambda _on: self._analysis_changed())
        self.overlays.toggled.connect(lambda _on: self._analysis_changed())
        self._mode_visibility()
        self.set_connection("none")
        self._loading = False

    # ---- state -------------------------------------------------------------------------
    def sweep_params(self) -> SweepParams:
        """The validated sweep settings (ValueError with the reason otherwise)."""
        start, stop = float(self.start.value()), float(self.stop.value())
        validate_sweep_range(start, stop)
        return SweepParams(start, stop, self.res.currentText(), self.sens.currentData())

    def sweep_prefs(self) -> dict:
        return {"start_nm": float(self.start.value()), "stop_nm": float(self.stop.value()),
                "resolution": self.res.currentText(), "sensitivity": self.sens.currentData(),
                "mode": self.mode.currentText(), "peak_hold_ms": int(self.peak_hold.value()),
                "active_trace": self.active.currentData(), "continuous": self.continuous.isChecked()}

    @property
    def active_trace(self) -> str:
        return self.active.currentData() or "A"

    @property
    def is_continuous(self) -> bool:
        return self.continuous.isChecked()

    def measurement_mode(self) -> tuple[str, int]:
        return self.mode.currentText(), int(self.peak_hold.value())

    def analysis_options(self) -> dict:
        opts = dict(self._analysis)
        for name, cb in self.flags.items():
            opts[name] = cb.isChecked()
        return normalize_options(opts)

    def set_power_ranges(self, ranges: list[dict]) -> None:
        self._analysis["Power Content"] = list(ranges)
        self.b_ranges.setText(f"Power content ranges… ({len(ranges)})" if ranges else "Power content ranges…")
        self._analysis_changed()

    @property
    def power_ranges(self) -> list[dict]:
        return list(self._analysis.get("Power Content") or [])

    @property
    def auto_analyse(self) -> bool:
        return self.auto.isChecked()

    @property
    def show_overlays(self) -> bool:
        return self.overlays.isChecked()

    def set_connection(self, state: str, idn: str = "") -> None:
        """state: none | scanning | connected | simulator | novisa"""
        color = {"connected": T.GOOD, "simulator": T.ACCENT, "scanning": T.WARN}.get(state, T.MUTED)
        text = {"none": "● Not connected", "scanning": "● Searching…", "connected": "● Connected",
                "simulator": "● Simulator", "novisa": "● No VISA backend"}.get(state, state)
        set_pill(self.conn, text, color)
        self.idn.setText(idn)
        self.idn.setVisible(bool(idn))
        live = state in ("connected", "simulator")
        self.b_disconnect.setEnabled(live)
        self.b_connect.setEnabled(state not in ("scanning", "connected"))
        self.b_sweep.setEnabled(live)

    def set_resources(self, found: list[tuple[str, str]]) -> None:
        self.resources = list(found)
        current = self.resource.currentData()
        self._loading = True
        self.resource.clear()
        self.resource.addItem("Automatic (first Ando found)", "")
        for name, idn in found:
            self.resource.addItem(f"{name} — {idn or 'no *IDN? answer'}", name)
        idx = self.resource.findData(current)
        self.resource.setCurrentIndex(max(0, idx))
        self._loading = False

    def set_busy(self, mode: Optional[str], live: bool) -> None:
        """mode: None | 'connect' | 'sweep' | 'timelapse'; ``live`` = an instrument is connected."""
        busy = mode is not None
        self.b_sweep.setEnabled(live and not busy)
        self.b_stop.setEnabled(mode in ("sweep", "timelapse"))
        self.b_connect.setEnabled(not busy and not live)
        self.b_disconnect.setEnabled(live and not busy)
        self.b_scan.setEnabled(not busy)
        self.b_sim.setEnabled(not busy)
        self.active.setEnabled(mode != "timelapse")
        self.mode.setEnabled(not busy)
        self.peak_hold.setEnabled(not busy)

    # ---- slots -------------------------------------------------------------------------
    def _connect_clicked(self) -> None:
        self.connectRequested.emit(self.resource.currentData() or "")

    def _sweep_changed(self) -> None:
        if self._loading:
            return
        self.store.set_pref("sweep", self.sweep_prefs())
        self.settingsChanged.emit()

    def _mode_visibility(self) -> None:
        pulsed = self.mode.currentText() == "Pulsed"
        self.peak_hold_lab.setVisible(pulsed)
        self.peak_hold.setVisible(pulsed)

    def _mode_changed(self) -> None:
        self._mode_visibility()
        if self._loading:
            return
        self.store.set_pref("sweep", self.sweep_prefs())
        self.measurementModeChanged.emit()

    def _active_changed(self) -> None:
        if self._loading:
            return
        self.store.set_pref("sweep", self.sweep_prefs())
        self.activeTraceChanged.emit(self.active_trace)

    def _flag(self, _name: str) -> None:
        self._analysis_changed()

    def _analysis_changed(self) -> None:
        if self._loading:
            return
        self.store.update_prefs({"analysis": self.analysis_options(), "auto_analyse": self.auto.isChecked(),
                                 "show_overlays": self.overlays.isChecked()})
        self.analysisChanged.emit()

    def _update_link(self, href: str) -> None:
        if href == "#install":
            self.installUpdate.emit()
        else:
            webbrowser.open(href)
