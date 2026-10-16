"""Matplotlib drawing shared by the desktop canvas and the saved PNGs, so what you save is
what you saw. ``dark`` draws on the kayEi navy (the screen); the default for files is the
light "paper" look that prints well.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.transforms import blended_transform_factory

from . import palette as P

TRACE_LABELS = ("A", "B", "C")


def _colors(dark: bool):
    if dark:
        return dict(bg=P.BG, ink=P.INK, muted=P.MUTED, line=P.LINE, axes=P.rgba_tuple(P.MUTED, .06),
                    grid=P.rgba_tuple(P.MUTED, .18))
    return dict(bg=P.LIGHT_BG, ink=P.LIGHT_INK, muted=P.LIGHT_MUTED, line=P.LIGHT_LINE, axes="#fbfcfe",
                grid=P.rgba_tuple(P.LIGHT_MUTED, .22))


def style_axes(ax, dark: bool = True) -> None:
    c = _colors(dark)
    ax.figure.patch.set_facecolor(c["bg"])
    ax.set_facecolor(c["axes"])
    for sp in ax.spines.values():
        sp.set_color(c["line"])
    ax.tick_params(colors=c["muted"], labelcolor=c["ink"], labelsize=9)
    ax.xaxis.label.set_color(c["ink"])
    ax.yaxis.label.set_color(c["ink"])
    ax.title.set_color(c["ink"])
    ax.grid(True, color=c["grid"], linewidth=0.8)
    ax.set_axisbelow(True)


def legend(ax, dark: bool = True, loc: str = "upper right"):
    handles, labels = ax.get_legend_handles_labels()
    if not handles:
        return None
    c = _colors(dark)
    leg = ax.legend(loc=loc, fontsize=9, frameon=True, framealpha=0.9)
    leg.get_frame().set_facecolor(P.PANEL if dark else P.LIGHT_BG)
    leg.get_frame().set_edgecolor(c["line"])
    for t in leg.get_texts():
        t.set_color(c["ink"])
    return leg


def series_label(label: str) -> str:
    return f"Trace {label}" if label in TRACE_LABELS else label


def draw_spectrum(ax, traces, overlays: Optional[dict] = None, show_overlays: bool = True, dark: bool = True,
                  title: str = "") -> None:
    """``traces``: ``[(label, wavelengths, levels)]``; ``overlays``: ``{label: analysis overlays}``."""
    ax.clear()
    style_axes(ax, dark)
    for label, w, lv in traces:
        if len(w) == 0:
            continue
        ax.plot(w, lv, color=P.trace_color(label, light=not dark), linewidth=1.1, label=series_label(label))
    if show_overlays and overlays:
        for label, _w, _l in traces:
            ov = overlays.get(label)
            if ov:
                draw_overlays(ax, ov, dark)
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Level (dBm)")
    if title:
        ax.set_title(title, loc="left", fontsize=11)
    legend(ax, dark)


def draw_overlays(ax, ov: dict, dark: bool = True) -> None:
    """Markers for the analysis results: peak, FWHM bar, SNR reference, anti-Stokes window,
    power-content bands."""
    c = _colors(dark)
    top = blended_transform_factory(ax.transData, ax.transAxes)
    for i, (a, b, pct) in enumerate(ov.get("power") or []):
        col = P.POWER_FILL[i % len(P.POWER_FILL)]
        ax.axvspan(a, b, color=P.rgba_tuple(col, .16), lw=0)
        ax.text(0.5 * (a + b), 0.015, f"P{i + 1} {pct:.1f} %", transform=top, ha="center", va="bottom", fontsize=8,
                color=col if dark else P.LIGHT_INK)
    if "snr" in ov:
        wl, lvl, lo, hi = ov["snr"]
        ax.axvspan(lo, hi, color=P.rgba_tuple(P.MUTED, .08), lw=0)
        ax.plot([wl], [lvl], "v", color=P.SNR_NOISE if dark else P.LIGHT_MUTED, ms=6)
        ax.annotate("SNR ref", (wl, lvl), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=8,
                    color=P.SNR_NOISE if dark else P.LIGHT_MUTED)
    if "srs" in ov:
        lo, hi, wl, lvl, anti = ov["srs"]
        ax.axvspan(lo, hi, color=P.rgba_tuple(P.SRS, .15), lw=0)
        ax.plot([wl], [lvl], "s", color=P.SRS, ms=5)
        ax.annotate(f"anti-Stokes\n{anti:.1f} nm", (wl, lvl), xytext=(0, 10), textcoords="offset points", ha="center",
                    fontsize=8, color=P.SRS)
    if "fwhm" in ov:
        lo, hi, level = ov["fwhm"]
        ax.hlines(level, lo, hi, colors=P.FWHM, linestyles="--", lw=1.4)
        ax.annotate(f"FWHM {hi - lo:.3f} nm", (0.5 * (lo + hi), level), xytext=(0, -14), textcoords="offset points",
                    ha="center", fontsize=8, color=P.FWHM)
    if "peak" in ov:
        pw, pl = ov["peak"]
        ax.plot([pw], [pl], "o", color=P.PEAK, ms=6)
        ax.annotate(f"{pw:.3f} nm\n{pl:.2f} dBm", (pw, pl), xytext=(8, 8), textcoords="offset points", fontsize=8,
                    color=c["ink"])


def envelope(runs):
    """(wavelengths, min, max, median) over runs with identical point counts, else None."""
    if len(runs) < 2:
        return None
    n = len(runs[0][1])
    if not n or any(len(lv) != n for _w, lv in runs):
        return None
    arr = np.array([lv for _w, lv in runs], dtype=float)
    return runs[0][0], arr.min(axis=0), arr.max(axis=0), np.median(arr, axis=0)


def draw_timelapse(ax, runs, dark: bool = True, current_label: str = "Current") -> None:
    """The latest measurement with the min / max / median envelope of the run so far."""
    ax.clear()
    style_axes(ax, dark)
    if not runs:
        ax.set_xlabel("Wavelength (nm)")
        ax.set_ylabel("Level (dBm)")
        return
    w, lv = runs[-1]
    env = envelope(runs)
    if env is not None:
        bw, lo, hi, med = env
        ax.fill_between(bw, lo, hi, color=P.rgba_tuple(P.ACCENT, .12), lw=0, label="Min … max")
        ax.plot(bw, med, ":", color=P.WARN, lw=1.0, label="Median")
    ax.plot(w, lv, color=P.ACCENT if dark else P.LIGHT_TRACE_COLORS["A"], lw=1.1, label=current_label)
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Level (dBm)")
    legend(ax, dark)


def _pad(ax, values, minimum: float) -> None:
    """Y limits with a sensible margin: a constant series must not blow up to ±5 % of itself."""
    v = np.asarray([x for x in values if x is not None], dtype=float)
    if v.size == 0:
        return
    lo, hi = float(v.min()), float(v.max())
    pad = max(minimum, 0.15 * (hi - lo))
    ax.set_ylim(lo - pad, hi + pad)


def draw_trend(ax, elapsed_s, peak_wl, peak_lvl, dark: bool = True):
    """Peak wavelength (left axis) and peak level (right axis) over the run. Returns the
    right-hand axes (a fresh twin every call – clear the figure before redrawing)."""
    ax.clear()
    style_axes(ax, dark)
    c = _colors(dark)
    t = np.asarray(elapsed_s, dtype=float)
    unit, scale = ("min", 60.0) if (t.size and t[-1] > 180) else ("s", 1.0)
    col_wl = P.ACCENT if dark else P.LIGHT_TRACE_COLORS["A"]
    col_lv = P.WARN if dark else "#b45309"
    ax.plot(t / scale, peak_wl, "o-", color=col_wl, ms=3, lw=1.0, label="Peak wavelength")
    _pad(ax, peak_wl, 0.05)
    ax.ticklabel_format(axis="y", useOffset=False)
    ax.set_xlabel(f"Elapsed ({unit})")
    ax.set_ylabel("Peak wavelength (nm)", color=col_wl)
    ax.tick_params(axis="y", labelcolor=col_wl)
    ax2 = ax.twinx()
    ax2.plot(t / scale, peak_lvl, "s-", color=col_lv, ms=3, lw=1.0, label="Peak level")
    _pad(ax2, peak_lvl, 0.1)
    ax2.set_ylabel("Peak level (dBm)", color=col_lv)
    ax2.tick_params(axis="y", labelcolor=col_lv, colors=c["muted"])
    for sp in ax2.spines.values():
        sp.set_color(c["line"])
    ax2.set_facecolor("none")
    return ax2


# ------------------------------------------------------------------------ PNG files
def render_png(path, traces, overlays: Optional[dict] = None, show_overlays: bool = True, dark: bool = False,
               title: str = "", size=(9.0, 5.0), dpi: int = 120) -> str:
    """Draw ``traces`` (``[(label, w, l)]``) to a PNG with the Agg canvas (thread-safe)."""
    fig = Figure(figsize=size, dpi=dpi)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    draw_spectrum(ax, traces, overlays, show_overlays, dark, title)
    fig.tight_layout()
    fig.savefig(path, facecolor=fig.get_facecolor())
    return str(path)


def render_timelapse_png(path, runs, dark: bool = False, title: str = "", size=(9.0, 5.0), dpi: int = 120) -> str:
    fig = Figure(figsize=size, dpi=dpi)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    draw_timelapse(ax, runs, dark)
    if title:
        ax.set_title(title, loc="left", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, facecolor=fig.get_facecolor())
    return str(path)
