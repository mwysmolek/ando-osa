"""The plot canvases: matplotlib's Qt canvas drawn in the kayEi look. All drawing goes
through ``ando_osa.plots`` so the saved PNGs match the screen."""
from __future__ import annotations

from typing import Optional

import matplotlib

matplotlib.use("QtAgg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QPalette  # noqa: E402

from ando_osa import plots  # noqa: E402

from . import theme as T  # noqa: E402


class _Canvas(FigureCanvasQTAgg):
    def __init__(self, parent=None, size=(8.0, 4.5)):
        fig = Figure(figsize=size, dpi=100, layout="constrained")
        super().__init__(fig)
        if parent is not None:
            self.setParent(parent)
        fig.patch.set_facecolor(T.BG)
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(T.BG))
        self.setPalette(pal)
        self.setAutoFillBackground(True)
        self.setMinimumHeight(220)
        self.setFocusPolicy(Qt.ClickFocus)


class SpectrumCanvas(_Canvas):
    """Traces with their analysis overlays."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ax = self.figure.add_subplot(111)
        self._traces: list = []
        self._overlays: dict = {}
        self._show_overlays = True
        self._title = ""
        plots.draw_spectrum(self.ax, [], None, True, True)
        self.draw_idle()

    def show_spectrum(self, traces, overlays: Optional[dict] = None, show_overlays: bool = True, title: str = "") -> None:
        """``traces``: ``[(label, wavelengths, levels)]``; ``overlays``: ``{label: overlays}``."""
        self._traces, self._overlays, self._show_overlays, self._title = list(traces), dict(overlays or {}), show_overlays, title
        # a zoomed or panned view (autoscale off) survives the redraw of a continuous sweep;
        # the toolbar's Home button switches autoscale back on
        keep = (not self.ax.get_autoscalex_on()) and bool(self._traces)
        xlim, ylim = (self.ax.get_xlim(), self.ax.get_ylim()) if keep else (None, None)
        plots.draw_spectrum(self.ax, self._traces, self._overlays, show_overlays, True, title)
        if keep:
            self.ax.set_xlim(xlim)
            self.ax.set_ylim(ylim)
        self.draw_idle()

    def save_png(self, path: str, dark: bool = False, with_overlays: Optional[bool] = None) -> str:
        """Render the current content to a file with the Agg canvas (light by default)."""
        ov = self._show_overlays if with_overlays is None else with_overlays
        return plots.render_png(path, self._traces, self._overlays, ov, dark=dark, title=self._title)


class TimeLapseCanvas(_Canvas):
    """The latest sweep with the min/max/median envelope above the peak trend."""

    def __init__(self, parent=None):
        super().__init__(parent, size=(8.0, 6.0))
        self.ax_env = self.figure.add_subplot(211)
        self.ax_trend = self.figure.add_subplot(212)
        self._runs: list = []
        plots.draw_timelapse(self.ax_env, [], True)
        plots.style_axes(self.ax_trend, True)
        self.ax_trend.set_xlabel("Elapsed (s)")
        self.ax_trend.set_ylabel("Peak wavelength (nm)")
        self.draw_idle()

    def reset(self) -> None:
        self._runs = []
        self.figure.clear()
        self.ax_env = self.figure.add_subplot(211)
        self.ax_trend = self.figure.add_subplot(212)
        plots.draw_timelapse(self.ax_env, [], True)
        plots.style_axes(self.ax_trend, True)
        self.draw_idle()

    def update_run(self, runs, elapsed_s, peak_wl, peak_lvl) -> None:
        self._runs = list(runs)
        self.figure.clear()
        self.ax_env = self.figure.add_subplot(211)
        self.ax_trend = self.figure.add_subplot(212)
        plots.draw_timelapse(self.ax_env, self._runs, True, current_label=f"Measurement {len(self._runs)}")
        if elapsed_s:
            plots.draw_trend(self.ax_trend, elapsed_s, peak_wl, peak_lvl, True)
        else:
            plots.style_axes(self.ax_trend, True)
        self.draw_idle()

    def save_png(self, path: str, dark: bool = False) -> str:
        return plots.render_timelapse_png(path, self._runs, dark=dark)


class Toolbar(NavigationToolbar2QT):
    """matplotlib's navigation toolbar without the subplot/config buttons."""
    toolitems = [t for t in NavigationToolbar2QT.toolitems if t[0] not in ("Subplots", "Customize")]

    def __init__(self, canvas, parent=None):
        super().__init__(canvas, parent, coordinates=True)
        self.setIconSize(self.iconSize() * 0.8)
        self.setStyleSheet(f"QToolBar {{ background: {T.BG}; border: 0; }} QLabel {{ color: {T.MUTED}; }}")

    def home(self, *args) -> None:
        """Back to autoscaling (the next sweep fits the view again)."""
        for ax in self.canvas.figure.get_axes():
            ax.set_autoscale_on(True)
            ax.relim()
            ax.autoscale_view()
        self._nav_stack.clear()
        self.set_history_buttons()
        self.canvas.draw_idle()
