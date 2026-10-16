"""Spectrum page: trace switches, KPI tiles, the plot with its markers, the results table."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QSplitter, QVBoxLayout, QWidget

from ando_osa import palette as P
from ando_osa.analysis import METRICS, format_value
from ando_osa.instrument import TRACE_MODES, TRACES, trace_mode_label

from ..plot import SpectrumCanvas, Toolbar
from ..widgets import KpiRow, Notice, Table, section

KPIS = [("Peak wavelength", "Peak Wavelength", "Wavelength of the global maximum"),
        ("Peak level", "Peak Level", "Level of the global maximum"),
        ("FWHM", "FWHM", "Width between the outermost −3 dB crossings"),
        ("SNR", "SNR", "Peak minus the highest level outside ±10 nm"),
        ("SRS", "SRS", "Anti-Stokes suppression (13.2 THz Raman shift)"),
        ("Total power", "Total Power", "Sum of the linear powers of all samples")]
TABLE_COLUMNS = ["trace", "points", "span", *METRICS]
TABLE_TITLES = {"trace": "Trace", "points": "Points", "span": "Span (nm)"}


class SpectrumPage(QWidget):
    traceVisibilityChanged = Signal(str, bool)
    traceModeChanged = Signal(str, str)
    importRequested = Signal()
    quickSaveRequested = Signal()
    saveAsRequested = Signal()
    clearImportsRequested = Signal()
    clearTracesRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("Traces"))
        self.trace_buttons: dict[str, QPushButton] = {}
        self.mode_boxes: dict[str, QComboBox] = {}
        for t in TRACES:
            b = QPushButton(t)
            b.setCheckable(True)
            b.setProperty("chip", True)
            b.setToolTip(f"Show trace {t} on the plot (and on the instrument's screen)")
            b.setStyleSheet(f"QPushButton:checked {{ background:{P.rgba(P.TRACE_COLORS[t], .3)}; border-color:{P.TRACE_COLORS[t]}; }}")
            b.toggled.connect(lambda on, t=t: self.traceVisibilityChanged.emit(t, on))
            row.addWidget(b)
            self.trace_buttons[t] = b
            m = QComboBox()
            for cmd in TRACE_MODES[t]:
                m.addItem(trace_mode_label(cmd), cmd)
            m.setToolTip(f"Trace {t} mode on the instrument: write every sweep, hold, max/min hold or rolling average")
            m.currentIndexChanged.connect(lambda _i, t=t, m=m: self.traceModeChanged.emit(t, m.currentData()))
            row.addWidget(m)
            self.mode_boxes[t] = m
            row.addSpacing(6)
        row.addStretch(1)
        self.b_import = QPushButton("Import CSV…")
        self.b_import.setToolTip("Overlay a saved trace (Ctrl+O)")
        self.b_import.clicked.connect(self.importRequested)
        self.b_clear_imports = QPushButton("Clear imports")
        self.b_clear_imports.clicked.connect(self.clearImportsRequested)
        self.b_clear_imports.setEnabled(False)
        self.b_quick = QPushButton("Quick save")
        self.b_quick.setToolTip("Save the active trace as X0000.csv / .png (+ analysis) into the quick-save folder (Ctrl+S)")
        self.b_quick.clicked.connect(self.quickSaveRequested)
        self.b_save = QPushButton("Save as…")
        self.b_save.setToolTip("Save the active trace as CSV or PNG where you choose (Ctrl+Shift+S)")
        self.b_save.clicked.connect(self.saveAsRequested)
        for b in (self.b_import, self.b_clear_imports, self.b_quick, self.b_save):
            row.addWidget(b)
        lay.addLayout(row)

        self.notice = Notice("")
        lay.addWidget(self.notice)
        self.kpis = KpiRow([(title, tip) for title, _key, tip in KPIS])
        lay.addWidget(self.kpis)

        split = QSplitter(Qt.Vertical)
        plot_box = QWidget()
        pl = QVBoxLayout(plot_box)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        self.canvas = SpectrumCanvas(plot_box)
        self.toolbar = Toolbar(self.canvas, plot_box)
        pl.addWidget(self.toolbar)
        pl.addWidget(self.canvas, 1)
        split.addWidget(plot_box)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        self.table_label = section("Analysis per trace")
        bl.addWidget(self.table_label)
        self.table = Table()
        self.table.export_name = "analysis"
        self.table.setToolTip("Right-click to copy or export; Ctrl+C copies the selected rows")
        bl.addWidget(self.table, 1)
        split.addWidget(bottom)
        split.setSizes([700, 160])
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)

    # ---- API -------------------------------------------------------------------------------
    def set_notice(self, html: str) -> None:
        self.notice.set(html)

    def set_visibility(self, visible: dict, loading: bool = True) -> None:
        for t, b in self.trace_buttons.items():
            b.blockSignals(loading)
            b.setChecked(bool(visible.get(t)))
            b.blockSignals(False)

    def set_trace_modes(self, modes: dict) -> None:
        for t, m in self.mode_boxes.items():
            idx = m.findData(modes.get(t))
            if idx >= 0:
                m.blockSignals(True)
                m.setCurrentIndex(idx)
                m.blockSignals(False)

    def show_traces(self, traces, overlays: Optional[dict], show_overlays: bool, title: str = "") -> None:
        self.canvas.show_spectrum(traces, overlays, show_overlays, title)

    def set_results(self, rows: list[dict], kpi: Optional[dict], kpi_label: str, has_imports: bool) -> None:
        """``rows``: one dict per trace for the table; ``kpi``: the active trace's results."""
        for title, key, _tip in KPIS:
            v = (kpi or {}).get(key)
            sub = ""
            if key == "FWHM" and kpi and "Center Wavelength" in kpi:
                sub = f"centre {kpi['Center Wavelength']:.3f} nm"
            self.kpis.set(title, format_value(key, v) if v is not None else "–", sub or (kpi_label if v is not None else ""))
        fmt = {k: (lambda v, k=k: format_value(k, v)) for k in METRICS}
        fmt["span"] = lambda v: f"{v:.2f}"
        self.table.set_rows(rows, TABLE_COLUMNS, fmt=fmt, titles=TABLE_TITLES)
        self.table_label.setText(f"Analysis per trace ({len(rows)})" if rows else "Analysis per trace")
        self.b_clear_imports.setEnabled(has_imports)
