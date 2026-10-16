"""The kayEi palette (shared with RiskStudio and TwinStudio): every colour the plots and the
desktop app use, in one place – standard library only, no Qt, no matplotlib."""
from __future__ import annotations

BG = "#001a45"          # the window and the plot background
BG2 = "#002259"         # inputs, cards
PANEL = "#0b2a66"       # menus, tooltips
LINE = "#1e3a6e"        # borders, grid
INK = "#e6edf7"         # primary text
MUTED = "#9fb3c8"       # secondary text, axis labels
ACCENT = "#22d3ee"      # cyan: primary buttons, trace A
ACCENT_INK = "#002238"
GOOD, WARN, BAD = "#22c55e", "#f59e0b", "#ef4444"

# categorical slots in fixed order (imports, extra traces)
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]

TRACE_COLORS = {"A": ACCENT, "B": "#f97316", "C": "#a78bfa"}     # the instrument's three traces
PEAK = "#f87171"          # peak marker
FWHM = WARN               # the -3 dB bar
SNR_NOISE = "#cbd5e1"     # highest level outside the exclusion window
SRS = "#f472b6"           # anti-Stokes search window
POWER_FILL = SERIES       # power-content ranges, one slot each

# the printed / saved figure (white paper)
LIGHT_BG, LIGHT_INK, LIGHT_MUTED, LIGHT_LINE = "#ffffff", "#0f172a", "#64748b", "#e2e8f0"
LIGHT_TRACE_COLORS = {"A": "#0e7490", "B": "#ea580c", "C": "#7c3aed"}


def hex_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgba(hex_color: str, alpha: float) -> str:
    """'#rrggbb' + alpha -> 'rgba(r,g,b,a)' for Qt style sheets."""
    r, g, b = hex_rgb(hex_color)
    return f"rgba({r},{g},{b},{alpha:g})"


def rgba_tuple(hex_color: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    """'#rrggbb' + alpha -> (r, g, b, a) in 0..1 for matplotlib."""
    r, g, b = hex_rgb(hex_color)
    return r / 255.0, g / 255.0, b / 255.0, alpha


def trace_color(label: str, light: bool = False) -> str:
    """Colour of a trace by its label: A/B/C have fixed colours, everything else (imports)
    takes the next categorical slot, stable for the label."""
    table = LIGHT_TRACE_COLORS if light else TRACE_COLORS
    if label in table:
        return table[label]
    digits = "".join(ch for ch in label if ch.isdigit())
    return SERIES[(int(digits) if digits else len(label)) % len(SERIES)]
