"""The application window: menus, the instrument panel, the pages, the status bar and the
workers that talk to the instrument."""
from __future__ import annotations

import logging
import sys
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QPixmap
from PySide6.QtWidgets import (QDialog, QDockWidget, QFileDialog, QLabel, QMainWindow, QMessageBox, QProgressBar,
                               QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ando_osa import APP_NAME, REPO, __version__, storage, updates
from ando_osa.analysis import METRICS, analyze
from ando_osa.instrument import TRACES
from ando_osa.plots import render_png
from ando_osa.storage import QuickSaver, Store

from . import theme as T
from .dialogs import CommandConsole, PowerRangesDialog, PreferencesDialog, pref
from .pages.log_page import LogPage
from .pages.method_page import MethodPage
from .pages.spectrum_page import SpectrumPage
from .pages.timelapse_page import TimeLapsePage
from .panel import InstrumentPanel
from .widgets import set_pill
from .workers import ConnectWorker, SweepWorker, TimeLapseWorker, start_in_thread

log = logging.getLogger(__name__)

PAGES = [("spectrum", "📈 Spectrum"), ("timelapse", "⏱ Time-lapse"), ("log", "📜 Log"), ("method", "📘 Method")]
DEFAULT_MODES = {"A": "WRTA", "B": "FIXB", "C": "FIXC"}


@dataclass
class Trace:
    label: str
    wavelengths: list
    levels: list
    source: str = "instrument"          # instrument | import | timelapse
    taken: datetime = field(default_factory=datetime.now)
    path: str = ""

    @property
    def points(self) -> int:
        return len(self.wavelengths)

    @property
    def span(self) -> float:
        return (max(self.wavelengths) - min(self.wavelengths)) if self.wavelengths else 0.0


class MainWindow(QMainWindow):
    resultsChanged = Signal()           # a trace or its analysis changed (the smoke test listens)

    def __init__(self, store: Optional[Store] = None, parent=None):
        super().__init__(parent)
        self.store = store or Store()
        self.rm = None
        self.rm_error: Optional[str] = None
        self.osa = None
        self.traces: dict[str, Trace] = {}
        self.visible: dict[str, bool] = {"A": True, "B": False, "C": False}
        self.trace_modes: dict[str, str] = dict(DEFAULT_MODES)
        self.results: dict[str, dict] = {}
        self.overlays: dict[str, dict] = {}
        self.quick = QuickSaver()
        self.busy_mode: Optional[str] = None
        self.sweep_worker = self.sweep_thread = None
        self.tl_worker = self.tl_thread = None
        self.connect_worker = self.connect_thread = None
        self.tl_interval = 0.0
        self.console: Optional[CommandConsole] = None
        self._silent_connect = False

        self.setWindowTitle(APP_NAME)
        self.resize(1500, 950)
        self.setMinimumSize(QSize(1000, 650))
        self.settings = QSettings("kayEi", "SpectrumStudio")
        self._build_pages()
        self._build_dock()
        self._build_menus()
        self._build_status()
        self._install_logging()
        self.setAcceptDrops(True)
        self.restoreGeometry(self.settings.value("geometry", b""))
        self.restoreState(self.settings.value("state", b""))
        self.page_spectrum.set_visibility(self.visible)
        self.page_spectrum.set_trace_modes(self.trace_modes)
        self._refresh()
        self._set_busy(None)

    # ---- construction ----------------------------------------------------------------------
    def _build_pages(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.pages: dict[str, QWidget] = {}
        self.page_spectrum = SpectrumPage()
        self.page_timelapse = TimeLapsePage(self.store)
        self.page_log = LogPage()
        self.page_method = MethodPage()
        for key, w in (("spectrum", self.page_spectrum), ("timelapse", self.page_timelapse), ("log", self.page_log),
                       ("method", self.page_method)):
            self.pages[key] = w
            self.tabs.addTab(w, dict(PAGES)[key])
        self.setCentralWidget(self.tabs)
        sp = self.page_spectrum
        sp.traceVisibilityChanged.connect(self.set_trace_visible)
        sp.traceModeChanged.connect(self.set_trace_mode)
        sp.importRequested.connect(lambda: self.import_csv())
        sp.quickSaveRequested.connect(self.quick_save)
        sp.saveAsRequested.connect(self.save_as)
        sp.clearImportsRequested.connect(self.clear_imports)
        sp.clearTracesRequested.connect(self.clear_traces)
        self.page_timelapse.startRequested.connect(self.start_timelapse)
        self.page_timelapse.stopRequested.connect(self.stop)

    def _build_dock(self) -> None:
        self.panel = InstrumentPanel(self.store)
        p = self.panel
        p.connectRequested.connect(lambda res: self.connect_device(res, silent=False))
        p.disconnectRequested.connect(self.disconnect_device)
        p.simulatorRequested.connect(self.use_simulator)
        p.scanRequested.connect(self.scan_bus)
        p.sweepRequested.connect(self.start_sweep)
        p.stopRequested.connect(self.stop)
        p.settingsChanged.connect(self.on_sweep_settings_changed)
        p.activeTraceChanged.connect(self.on_active_trace_changed)
        p.measurementModeChanged.connect(self.on_measurement_mode_changed)
        p.analysisChanged.connect(self.on_analysis_changed)
        p.powerRangesRequested.connect(self.power_ranges)
        p.installUpdate.connect(self.install_update)
        dock = QDockWidget("INSTRUMENT", self)
        dock.setObjectName("instrumentDock")
        dock.setWidget(p)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        dock.setMinimumWidth(270)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.dock = dock

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&File")
        self._act(m, "Import trace (CSV)…", lambda: self.import_csv(), "Ctrl+O")
        self._act(m, "Quick save active trace", self.quick_save, "Ctrl+S")
        self._act(m, "Save active trace as…", self.save_as, "Ctrl+Shift+S")
        self._act(m, "Quick-save folder…", self.set_quick_save_folder)
        m.addSeparator()
        self._act(m, "Open data folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.home))))
        m.addSeparator()
        self._act(m, "Exit", self.close, "Ctrl+Q")

        m = mb.addMenu("&Instrument")
        self._act(m, "Connect (scan for an Ando OSA)", lambda: self.connect_device("", silent=False))
        self._act(m, "Disconnect", self.disconnect_device)
        self._act(m, "Scan bus", self.scan_bus)
        self._act(m, "Use the simulator", self.use_simulator)
        m.addSeparator()
        self._act(m, "Initialize instrument (CW, write A, blank B/C)", self.initialize_instrument)
        self._act(m, "Send command…", self.send_command)
        m.addSeparator()
        self._act(m, "Preferences…", self.preferences)

        m = mb.addMenu("&Sweep")
        self._act(m, "Start sweep", self.start_sweep, "F5")
        self._act(m, "Stop", self.stop, "Esc")
        self.a_continuous = QAction("Continuous", self, checkable=True)
        self.a_continuous.setChecked(self.panel.is_continuous)
        self.a_continuous.triggered.connect(self.panel.continuous.setChecked)
        self.panel.continuous.toggled.connect(self.a_continuous.setChecked)
        m.addAction(self.a_continuous)
        m.addSeparator()
        self._act(m, "Clear imported traces", self.clear_imports)
        self._act(m, "Clear all traces", self.clear_traces)

        m = mb.addMenu("&Analysis")
        self._act(m, "Analyse now", self.analyse_all, "F6")
        self._act(m, "Power content ranges…", self.power_ranges)
        self.a_overlays = QAction("Show markers on the plot", self, checkable=True)
        self.a_overlays.setChecked(self.panel.show_overlays)
        self.a_overlays.triggered.connect(self.panel.overlays.setChecked)
        self.panel.overlays.toggled.connect(self.a_overlays.setChecked)
        m.addAction(self.a_overlays)

        m = mb.addMenu("&View")
        for i, (key, label) in enumerate(PAGES):
            self._act(m, label, lambda _=False, k=key: self.show_page(k), f"Ctrl+{i + 1}")
        m.addSeparator()
        m.addAction(self.dock.toggleViewAction())

        m = mb.addMenu("&Help")
        self._act(m, "Method (how the numbers are computed)", lambda: self.show_page("method"))
        self._act(m, "What's new", self.whats_new)
        self._act(m, "Check for updates", self.check_updates_now)
        self._act(m, "Project page on GitHub", lambda: webbrowser.open(f"https://github.com/{REPO}"))
        m.addSeparator()
        self._act(m, f"About {APP_NAME}", self.about)

    def _act(self, menu, text: str, fn, shortcut: Optional[str] = None) -> QAction:
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(fn)
        menu.addAction(a)
        return a

    def _build_status(self) -> None:
        sb = self.statusBar()
        self.conn_lab = QLabel()
        self.conn_lab.setProperty("pill", True)
        set_pill(self.conn_lab, "● Not connected", T.MUTED)
        sb.addPermanentWidget(self.conn_lab)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(140)
        self.progress.setTextVisible(False)
        self.progress.hide()
        sb.addPermanentWidget(self.progress)
        self.info_lab = QLabel("")
        self.info_lab.setProperty("muted", True)
        sb.addPermanentWidget(self.info_lab)

    def _install_logging(self) -> None:
        root = logging.getLogger()
        root.addHandler(self.page_log.handler)
        if root.level > logging.DEBUG or root.level == logging.NOTSET:
            root.setLevel(logging.DEBUG)            # the page's level combo filters per logger
        for h in root.handlers:
            if h is not self.page_log.handler and h.level == logging.NOTSET:
                h.setLevel(logging.INFO)

    # ---- lifecycle -------------------------------------------------------------------------
    def start(self, open_paths: Optional[list[str]] = None, simulate: bool = False) -> None:
        if simulate:
            self.use_simulator()
        elif pref(self.store, "auto_connect"):
            QTimer.singleShot(0, lambda: self.connect_device("", silent=True))
        for p in open_paths or []:
            self.import_csv(p)
        if pref(self.store, "update_check"):
            updates.start()
            QTimer.singleShot(8000, self._show_update)

    def closeEvent(self, e):  # noqa: N802
        for worker in (self.sweep_worker, self.tl_worker, self.connect_worker):
            if worker is not None:
                worker.stop()
        for thread in (self.sweep_thread, self.tl_thread, self.connect_thread):
            if thread is not None:
                thread.quit()
                if not thread.wait(5000):
                    log.warning("Worker thread did not stop within 5 s")
        self._close_osa()
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("state", self.saveState())
        logging.getLogger().removeHandler(self.page_log.handler)
        super().closeEvent(e)

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):  # noqa: N802
        for url in e.mimeData().urls():
            if url.isLocalFile():
                self.import_csv(url.toLocalFile())

    # ---- connection ------------------------------------------------------------------------
    def _resource_manager(self):
        if self.rm is None and self.rm_error is None:
            try:
                from ando_osa.instrument import open_resource_manager
                self.rm = open_resource_manager()
            except Exception as ex:  # noqa: BLE001
                self.rm_error = str(ex)
                log.warning("No VISA backend: %s", ex)
        return self.rm

    def connect_device(self, resource: str = "", silent: bool = False, auto_connect: bool = True) -> None:
        if self.busy_mode is not None:
            self.flash("Busy – wait for the current operation to finish.", "ℹ️")
            return
        if self.osa is not None and not self.osa.is_simulated:
            self.flash(f"Already connected to {self.osa.idn}", "ℹ️")
            return
        rm = self._resource_manager()
        if rm is None:
            self.panel.set_connection("novisa")
            msg = ("No VISA backend found. Install NI-VISA (or Keysight IO Libraries) for GPIB, or pyvisa-py; "
                   "the simulator works without one.")
            self.page_spectrum.set_notice("⚠️ " + msg)
            if not silent:
                QMessageBox.warning(self, "No VISA backend", msg + f"\n\n{self.rm_error}")
            return
        self._silent_connect = silent
        self.connect_worker = ConnectWorker(rm, resource or None, auto_connect)
        self.connect_worker.scanned.connect(self.on_scanned)
        self.connect_worker.connected.connect(self.on_connected)
        self.connect_worker.message.connect(self.on_worker_message)
        self.connect_worker.finished.connect(self.on_connect_finished)
        self.connect_thread = start_in_thread(self.connect_worker, self)
        self._set_busy("connect")
        self.panel.set_connection("scanning")
        self.flash("Searching the VISA bus for an Ando OSA…", "🔎")

    def scan_bus(self) -> None:
        self.connect_device("", silent=True, auto_connect=False)

    def on_scanned(self, found: list) -> None:
        self.panel.set_resources(found)
        n = len(found)
        self.flash(f"Scan found {n} VISA resource{'s' if n != 1 else ''}." if n else "Scan found no VISA resources.", "🔎")

    def on_connected(self, osa) -> None:
        if osa is None:
            if self.connect_worker is not None and self.connect_worker.auto_connect:
                self.flash("No Ando OSA found.", "⚠️")
                self.page_spectrum.set_notice("⚠️ No Ando OSA found. Check the GPIB cable and the VISA driver, pick the "
                                              "resource in the panel, or use the <b>Simulator</b> to try the app.")
                if not self._silent_connect:
                    QMessageBox.warning(self, "Connect", "No Ando OSA found on the VISA bus.")
            return
        self._adopt(osa)

    def on_connect_finished(self) -> None:
        self._cleanup_thread("connect")
        if self.osa is None:
            self.panel.set_connection("none")
        self._set_busy(None)

    def _adopt(self, osa) -> None:
        self._close_osa()
        self.osa = osa
        try:
            osa.initialize()
            self._push_instrument_state()
        except Exception as ex:  # noqa: BLE001
            log.exception("Device initialization failed")
            self.flash(f"Connected, but initialization failed: {ex}", "⚠️")
        state = "simulator" if osa.is_simulated else "connected"
        self.panel.set_connection(state, osa.idn)
        set_pill(self.conn_lab, "● Simulator" if osa.is_simulated else "● " + (osa.idn.split(",")[1].strip() if "," in osa.idn else osa.idn),
                 T.ACCENT if osa.is_simulated else T.GOOD)
        self.page_spectrum.set_notice("ℹ️ <b>Simulator</b>: a synthetic 1064 nm fibre-laser spectrum, nothing is connected."
                                      if osa.is_simulated else "")
        self._set_busy(None)
        self.flash(f"Connected to {osa.idn}", "🔌")

    def _push_instrument_state(self) -> None:
        """The panel's choices onto a freshly connected instrument."""
        osa = self.osa
        osa.set_active_trace(self.panel.active_trace)
        for t in TRACES:
            osa.set_trace_mode(self.trace_modes[t])
            osa.set_trace_display(t, bool(self.visible.get(t)))
        self.on_measurement_mode_changed()

    def _close_osa(self) -> None:
        if self.osa is not None:
            try:
                self.osa.close()
            except Exception:  # noqa: BLE001
                log.exception("Error closing instrument")
        self.osa = None

    def disconnect_device(self) -> None:
        if self.osa is None:
            self.flash("No instrument to disconnect.", "ℹ️")
            return
        if self.busy_mode in ("sweep", "timelapse"):
            self.stop()
        self._close_osa()
        self.panel.set_connection("none")
        set_pill(self.conn_lab, "● Not connected", T.MUTED)
        self.page_spectrum.set_notice("")
        self._set_busy(None)
        self.flash("Disconnected.", "🔌")

    def use_simulator(self) -> None:
        if self.busy_mode is not None:
            self.flash("Busy – stop the sweep first.", "ℹ️")
            return
        from ando_osa.simulator import SimulatedOSA
        self._adopt(SimulatedOSA())

    def initialize_instrument(self) -> None:
        if not self._require_osa():
            return
        try:
            self.osa.initialize()
            self._push_instrument_state()
            self.flash("Instrument initialized.", "✅")
        except Exception as ex:  # noqa: BLE001
            log.exception("Initialize failed")
            self.flash(f"Initialize failed: {ex}", "⚠️")

    def send_command(self) -> None:
        if self.console is None:
            self.console = CommandConsole(lambda: self.osa, self)
        self.console.show()
        self.console.raise_()
        self.console.activateWindow()

    def _require_osa(self) -> bool:
        if self.osa is None:
            self.flash("No instrument connected – Connect, or use the Simulator.", "⚠️")
            return False
        return True

    # ---- sweep -----------------------------------------------------------------------------
    def _params(self):
        try:
            return self.panel.sweep_params()
        except ValueError as ex:
            QMessageBox.warning(self, "Sweep settings", str(ex))
            return None

    def start_sweep(self) -> None:
        if not self._require_osa():
            return
        if self.busy_mode is not None:
            self.flash("Busy – stop the current operation first.", "ℹ️")
            return
        params = self._params()
        if params is None:
            return
        trace = self.panel.active_trace
        self.sweep_worker = SweepWorker(self.osa, params, trace, self.panel.is_continuous,
                                        bool(pref(self.store, "ref_to_peak")), float(pref(self.store, "sweep_timeout_s")))
        self.sweep_worker.message.connect(self.on_worker_message)
        self.sweep_worker.dataReady.connect(self.on_sweep_data)
        self.sweep_worker.sweepStarted.connect(self.on_sweep_started)
        self.sweep_worker.finished.connect(self.on_sweep_finished)
        self.sweep_thread = start_in_thread(self.sweep_worker, self)
        self._set_busy("sweep")
        self.show_page("spectrum")

    def stop(self) -> None:
        if self.sweep_worker is not None:
            self.sweep_worker.stop()
            self.flash("Stopping sweep…", "⏹")
        if self.tl_worker is not None:
            self.tl_worker.stop()
            self.flash("Stopping time-lapse…", "⏹")

    # worker signals land here through queued connections (bound slots of this QObject):
    # a bare lambda would run in the worker's thread and touch widgets from there
    @Slot(str)
    def on_worker_message(self, text: str) -> None:
        self.flash(text, "⚠️" if "failed" in text.lower() else "ℹ️")

    @Slot(int)
    def on_sweep_started(self, n: int) -> None:
        self.statusBar().showMessage(f"Sweep {n} running…" if self.panel.is_continuous else "Sweep running…")

    @Slot(str, list, list)
    def on_sweep_data(self, trace: str, wavelengths: list, levels: list) -> None:
        self.traces[trace] = Trace(trace, wavelengths, levels)
        if not self.visible.get(trace):
            self.visible[trace] = True
            self.page_spectrum.set_visibility(self.visible)
        if self.panel.auto_analyse:
            self._analyse(trace)
        else:
            self.results.pop(trace, None)
            self.overlays.pop(trace, None)
        self._refresh()

    def on_sweep_finished(self) -> None:
        self._cleanup_thread("sweep")
        self._set_busy(None)
        self.statusBar().showMessage("Sweep finished.", 4000)

    def on_sweep_settings_changed(self) -> None:
        if self.sweep_worker is not None:
            self.sweep_worker.set_continuous(self.panel.is_continuous)
            try:
                self.sweep_worker.set_params(self.panel.sweep_params())
            except ValueError:
                pass

    # ---- time-lapse ------------------------------------------------------------------------
    def start_timelapse(self) -> None:
        if not self._require_osa():
            return
        if self.busy_mode is not None:
            self.flash("Busy – stop the current operation first.", "ℹ️")
            return
        params = self._params()
        if params is None:
            return
        try:
            s = self.page_timelapse.settings()
        except ValueError as ex:
            QMessageBox.warning(self, "Time-lapse", str(ex))
            return
        try:
            run_dir = storage.timestamp_dir(s["directory"], "timelapse")
        except OSError as ex:
            QMessageBox.warning(self, "Time-lapse", f"Cannot create the run folder: {ex}")
            return
        trace = self.panel.active_trace
        self.tl_interval = s["interval_s"]
        self.tl_worker = TimeLapseWorker(self.osa, params, trace, s["interval_s"], s["count"], run_dir,
                                         self.panel.analysis_options(), bool(pref(self.store, "ref_to_peak")),
                                         float(pref(self.store, "sweep_timeout_s")), bool(pref(self.store, "dark_png")))
        self.tl_worker.message.connect(self.on_worker_message)
        self.tl_worker.measurementDone.connect(self.on_timelapse_measurement)
        self.tl_worker.finished.connect(self.on_timelapse_finished)
        self.page_timelapse.begin(s["count"], run_dir)
        self.tl_thread = start_in_thread(self.tl_worker, self)
        self._set_busy("timelapse")
        self.show_page("timelapse")
        self.flash(f"Time-lapse started – saving to {run_dir}", "⏱")

    def on_timelapse_measurement(self, index: int, elapsed: float, wavelengths: list, levels: list, results: dict) -> None:
        self.page_timelapse.add_measurement(index, elapsed, wavelengths, levels, results, self.tl_interval)
        trace = self.panel.active_trace
        self.traces[trace] = Trace(trace, wavelengths, levels, source="timelapse")
        self.results[trace] = dict(results)
        _r, self.overlays[trace] = analyze(wavelengths, levels, self.panel.analysis_options())
        self.statusBar().showMessage(f"Time-lapse: measurement {index + 1} recorded")
        self._refresh()

    def on_timelapse_finished(self) -> None:
        self._cleanup_thread("timelapse")
        self.page_timelapse.end()
        self._set_busy(None)
        self.statusBar().showMessage("Time-lapse finished.", 6000)

    # ---- traces, analysis, plot ------------------------------------------------------------
    def _analyse(self, label: str) -> None:
        tr = self.traces.get(label)
        if tr is None:
            return
        self.results[label], self.overlays[label] = analyze(tr.wavelengths, tr.levels, self.panel.analysis_options())

    def analyse_all(self) -> None:
        for label in list(self.traces):
            self._analyse(label)
        self._refresh()
        if self.traces:
            self.flash(f"Analysed {len(self.traces)} trace(s).", "🧮")

    def on_analysis_changed(self) -> None:
        self.a_overlays.setChecked(self.panel.show_overlays)
        for label in list(self.results):
            self._analyse(label)
        self._refresh()

    def power_ranges(self) -> None:
        dlg = PowerRangesDialog(self.panel.power_ranges, self)
        if dlg.exec() == QDialog.Accepted:
            self.panel.set_power_ranges(dlg.ranges())

    def _shown(self) -> list[Trace]:
        return [t for t in self.traces.values() if t.source == "import" or self.visible.get(t.label, True)]

    def _refresh(self) -> None:
        shown = self._shown()
        active = self.panel.active_trace
        self.page_spectrum.show_traces([(t.label, t.wavelengths, t.levels) for t in shown], self.overlays,
                                       self.panel.show_overlays)
        rows = []
        for t in self.traces.values():
            row = {"trace": t.label if t.source != "import" else f"{t.label} ({Path(t.path).name})", "points": t.points,
                   "span": t.span}
            row.update({k: self.results.get(t.label, {}).get(k) for k in METRICS})
            rows.append(row)
        has_imports = any(t.source == "import" for t in self.traces.values())
        self.page_spectrum.set_results(rows, self.results.get(active), f"Trace {active}", has_imports)
        tr = self.traces.get(active)
        if tr is not None and tr.wavelengths:
            self.info_lab.setText(f"Trace {active}: {tr.points} points · {min(tr.wavelengths):.2f}–{max(tr.wavelengths):.2f} nm"
                                  f" · {tr.taken:%H:%M:%S}")
        else:
            self.info_lab.setText(f"Trace {active}: no data")
        self.resultsChanged.emit()

    def set_trace_visible(self, trace: str, on: bool) -> None:
        self.visible[trace] = bool(on)
        if self.osa is not None:
            try:
                self.osa.set_trace_display(trace, bool(on))
            except Exception as ex:  # noqa: BLE001
                log.exception("Setting trace display failed")
                self.flash(f"Failed to set trace display: {ex}", "⚠️")
        self._refresh()

    def set_trace_mode(self, trace: str, cmd: str) -> None:
        self.trace_modes[trace] = cmd
        if self.osa is not None:
            try:
                self.osa.set_trace_mode(cmd)
            except Exception as ex:  # noqa: BLE001
                log.exception("Setting trace mode failed")
                self.flash(f"Failed to set trace mode: {ex}", "⚠️")

    def on_active_trace_changed(self, trace: str) -> None:
        if self.osa is not None:
            try:
                self.osa.set_active_trace(trace)
            except Exception as ex:  # noqa: BLE001
                log.exception("Setting active trace failed")
                self.flash(f"Failed to set active trace: {ex}", "⚠️")
        self._refresh()

    def on_measurement_mode_changed(self) -> None:
        if self.osa is None:
            return
        mode, ms = self.panel.measurement_mode()
        try:
            if mode == "CW":
                self.osa.set_cw_mode()
            else:
                self.osa.set_pulsed_mode(ms)
        except ValueError as ex:
            self.flash(str(ex), "⚠️")
        except Exception as ex:  # noqa: BLE001
            log.exception("Measurement mode change failed")
            self.flash(f"Mode change failed: {ex}", "⚠️")

    def clear_imports(self) -> None:
        for label in [k for k, t in self.traces.items() if t.source == "import"]:
            for d in (self.traces, self.results, self.overlays):
                d.pop(label, None)
        self._refresh()

    def clear_traces(self) -> None:
        self.traces.clear()
        self.results.clear()
        self.overlays.clear()
        self._refresh()

    # ---- files -----------------------------------------------------------------------------
    def import_csv(self, path: Optional[str] = None) -> Optional[str]:
        if not path:
            start = self.store.get_pref("import_dir") or str(Path.home())
            path, _ = QFileDialog.getOpenFileName(self, "Import trace", start, "CSV files (*.csv *.txt);;All files (*)")
            if not path:
                return None
        try:
            w, lv = storage.read_trace_csv(path)
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self, "Import failed", str(ex))
            return None
        n = 1
        while f"Import {n}" in self.traces:
            n += 1
        label = f"Import {n}"
        self.traces[label] = Trace(label, w, lv, source="import", path=str(path))
        self.store.set_pref("import_dir", str(Path(path).parent))
        if self.panel.auto_analyse:
            self._analyse(label)
        self._refresh()
        self.show_page("spectrum")
        self.flash(f"Imported {Path(path).name} as {label} ({len(w)} points).", "📂")
        return label

    def _active_data(self) -> Optional[Trace]:
        tr = self.traces.get(self.panel.active_trace)
        if tr is None or not tr.wavelengths:
            QMessageBox.warning(self, "No data", f"Trace {self.panel.active_trace} has no data yet – run a sweep first.")
            return None
        return tr

    def _write_set(self, base: Path, tr: Trace) -> list[Path]:
        """``<base>.csv`` + ``<base>_anal.csv`` + ``<base>.png`` (+ ``_overlay.png`` with markers)."""
        written = [storage.write_trace_csv(base.with_suffix(".csv"), tr.wavelengths, tr.levels)]
        a = storage.write_analysis_csv(base.parent / f"{base.name}_anal.csv", self.results.get(tr.label))
        if a:
            written.append(a)
        dark = bool(pref(self.store, "dark_png"))
        traces = [(tr.label, tr.wavelengths, tr.levels)]
        written.append(Path(render_png(base.with_suffix(".png"), traces, None, False, dark=dark, title=base.name)))
        if self.overlays.get(tr.label) and self.panel.show_overlays:
            written.append(Path(render_png(base.parent / f"{base.name}_overlay.png", traces, {tr.label: self.overlays[tr.label]},
                                           True, dark=dark, title=base.name)))
        return written

    def quick_save(self) -> Optional[Path]:
        tr = self._active_data()
        if tr is None:
            return None
        if not self.quick.active:
            directory = self.store.get_pref("quick_save_dir")
            if not directory or not Path(directory).is_dir():
                directory = QFileDialog.getExistingDirectory(self, "Quick-save folder", str(Path.home()))
                if not directory:
                    return None
                self.store.set_pref("quick_save_dir", directory)
            self.quick.start(directory)
        base = self.quick.next_base()
        try:
            self._write_set(base, tr)
        except OSError as ex:
            QMessageBox.warning(self, "Quick save", f"Could not write {base}: {ex}")
            return None
        self.flash(f"Quick-saved {base.name} to {base.parent}", "💾")
        return base

    def set_quick_save_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Quick-save folder",
                                                     self.store.get_pref("quick_save_dir") or str(Path.home()))
        if directory:
            self.store.set_pref("quick_save_dir", directory)
            self.quick.start(directory)
            self.flash(f"Quick saves go to {self.quick.folder}", "📁")

    def save_as(self) -> Optional[str]:
        tr = self._active_data()
        if tr is None:
            return None
        start = self.store.get_pref("save_dir") or str(Path.home())
        stem = f"trace_{tr.label}_{tr.taken:%Y%m%d_%H%M%S}"
        path, selected = QFileDialog.getSaveFileName(self, "Save trace", str(Path(start) / stem), "CSV (*.csv);;PNG (*.png)")
        if not path:
            return None
        p = Path(path)
        if not p.suffix:
            p = p.with_suffix(".png" if "PNG" in selected else ".csv")
        self.store.set_pref("save_dir", str(p.parent))
        try:
            if p.suffix.lower() == ".csv":
                storage.write_trace_csv(p, tr.wavelengths, tr.levels)
                storage.write_analysis_csv(p.parent / f"{p.stem}_anal.csv", self.results.get(tr.label))
            else:
                render_png(p, [(tr.label, tr.wavelengths, tr.levels)], {tr.label: self.overlays.get(tr.label, {})},
                           self.panel.show_overlays, dark=bool(pref(self.store, "dark_png")), title=p.stem)
        except OSError as ex:
            QMessageBox.warning(self, "Save", f"Could not write {p}: {ex}")
            return None
        self.flash(f"Saved {p}", "💾")
        return str(p)

    # ---- plumbing --------------------------------------------------------------------------
    def _set_busy(self, mode: Optional[str]) -> None:
        self.busy_mode = mode
        self.panel.set_busy(mode, self.osa is not None)
        self.progress.setVisible(mode in ("sweep", "timelapse", "connect"))
        self.page_timelapse.b_start.setEnabled(mode is None and self.osa is not None)

    def _cleanup_thread(self, which: str) -> None:
        if which == "sweep":
            thread, self.sweep_thread, self.sweep_worker = self.sweep_thread, None, None
        elif which == "connect":
            thread, self.connect_thread, self.connect_worker = self.connect_thread, None, None
        else:
            thread, self.tl_thread, self.tl_worker = self.tl_thread, None, None
        if thread is not None:
            thread.quit()
            thread.wait(2000)

    def flash(self, text: str, icon: str = "") -> None:
        self.statusBar().showMessage(f"{icon} {text}".strip(), 6000)
        log.info(text)

    def show_page(self, key: str) -> None:
        self.tabs.setCurrentWidget(self.pages[key])

    def report_exception(self, text: str) -> None:
        last = (text.strip().splitlines() or ["error"])[-1]
        self.flash(f"Unexpected error: {last} (see the Log page)", "⚠️")

    def preferences(self) -> None:
        if PreferencesDialog(self.store, self).exec() == QDialog.Accepted:
            self.flash("Preferences saved.", "✅")

    # ---- updates, help ---------------------------------------------------------------------
    def install_update(self) -> None:
        new = updates.available()
        if not new:
            return
        from .update_dialog import UpdateDialog
        dlg = UpdateDialog(new, self)
        dlg.exec()
        if dlg.unpacked:
            self.flash(f"New version unpacked to {dlg.unpacked} – close this app and start it from there.", "⬆️")

    def check_updates_now(self) -> None:
        updates._started = False
        updates.start()
        QTimer.singleShot(5000, lambda: self._show_update(explicit=True))

    def _show_update(self, explicit: bool = False) -> None:
        new = updates.available()
        if new:
            self.panel.update_lab.setText(f'⬆️ Version {new["version"]} is available – <a href="#install">install</a> · '
                                          f'<a href="{new["url"]}">release page</a>')
            self.panel.update_lab.show()
            if explicit:
                self.install_update()
        elif explicit:
            self.flash(f"You have the newest version ({__version__}) – or the check could not reach GitHub.", "✅")

    def whats_new(self) -> None:
        cands = [Path(__file__).resolve().parents[1] / "CHANGELOG.md", Path(getattr(sys, "_MEIPASS", ".")) / "CHANGELOG.md"]
        p = next((x for x in cands if x.exists()), None)
        text = p.read_text(encoding="utf-8") if p else "# What's new\n\nNo changelog found."
        dlg = QDialog(self)
        dlg.setWindowTitle(f"What's new in {APP_NAME}")
        dlg.resize(720, 560)
        lay = QVBoxLayout(dlg)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setMarkdown(text)
        lay.addWidget(tb)
        dlg.exec()

    def about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(f"About {APP_NAME}")
        pm = QPixmap(str(T.ASSETS / "logo.png"))
        if not pm.isNull():
            box.setIconPixmap(pm.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        box.setTextFormat(Qt.RichText)
        box.setText(f"<b>{APP_NAME} {__version__}</b><br>Control, analysis and time-lapse for Ando AQ63xx optical "
                    "spectrum analyzers over GPIB/VISA.<br><br>Everything runs locally; nothing leaves your PC."
                    f"<br><br>Data folder: {self.store.home}<br>"
                    f"<a href='https://github.com/{REPO}'>github.com/{REPO}</a>")
        box.exec()
