"""Trace analysis for OSA spectra.

``analyze`` operates on wavelength (nm) / level (dBm) arrays and returns two dicts:
numeric results (what the KPI tiles show and the ``*_anal.csv`` files hold) and overlay
geometry for drawing markers on the plot. Definitions are in ``method_text.py`` and the
README – read them before trusting a number.
"""
from __future__ import annotations

import math

import numpy as np

C_NM_THZ = 299792.458    # speed of light, in nm * THz
RAMAN_SHIFT_THZ = 13.2   # peak Raman gain shift of fused silica
SNR_EXCLUSION_NM = 10.0  # window around the peak excluded from the noise search
SRS_WINDOW_NM = 5.0      # search window around the expected anti-Stokes wavelength
FWHM_DROP_DB = 3.0
N_POWER_RANGES = 5

# metric -> (unit, decimals), in display order
METRICS = {
    "Peak Wavelength": ("nm", 3),
    "Peak Level": ("dBm", 2),
    "FWHM": ("nm", 3),
    "Center Wavelength": ("nm", 3),
    "SNR": ("dB", 2),
    "SRS": ("dB", 2),
    "Total Power": ("dBm", 2),
}
for _i in range(1, N_POWER_RANGES + 1):
    METRICS[f"Power Content {_i}"] = ("%", 1)

# the analysis flags (the "Power Content" entry is a list of {"start", "stop"} ranges)
FLAGS = ("Peak Search", "FWHM", "SNR", "SRS", "Total Power")
DEFAULT_OPTIONS = {"Peak Search": True, "FWHM": True, "SNR": False, "SRS": False, "Total Power": True,
                   "Power Content": []}


def unit_of(metric: str) -> str:
    return METRICS.get(metric, ("", 3))[0]


def format_value(metric: str, value) -> str:
    """'1064.012 nm', '–' for a missing value."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    unit, digits = METRICS.get(metric, ("", 3))
    return f"{float(value):.{digits}f} {unit}".strip()


def normalize_options(options) -> dict:
    """Fill in defaults; drop malformed power ranges."""
    out = dict(DEFAULT_OPTIONS)
    out.update({k: bool(v) for k, v in (options or {}).items() if k in FLAGS})
    ranges = []
    for r in (options or {}).get("Power Content") or []:
        try:
            start, stop = float(r["start"]), float(r["stop"])
        except (KeyError, TypeError, ValueError):
            continue
        if stop > start:
            ranges.append({"start": start, "stop": stop})
    out["Power Content"] = ranges[:N_POWER_RANGES]
    return out


def anti_stokes_wavelength(pump_nm: float, shift_thz: float = RAMAN_SHIFT_THZ) -> float:
    """λ_AS = λ_p / (1 + Δν·λ_p/c): the anti-Stokes line sits at a *shorter* wavelength."""
    return pump_nm / (1.0 + shift_thz * pump_nm / C_NM_THZ)


def stokes_wavelength(pump_nm: float, shift_thz: float = RAMAN_SHIFT_THZ) -> float:
    return pump_nm / (1.0 - shift_thz * pump_nm / C_NM_THZ)


def _crossing(w, lv, i, j, level):
    """Linear interpolation of the wavelength where the level crosses ``level`` between
    samples i and j (falls back to the sample inside the peak when flat)."""
    if lv[j] == lv[i]:
        return float(w[j])
    return float(w[i] + (level - lv[i]) * (w[j] - w[i]) / (lv[j] - lv[i]))


def fwhm(w, lv, drop_db: float = FWHM_DROP_DB):
    """(lo, hi, half_level) between the *outermost* -3 dB crossings, interpolated between
    samples. None when the trace does not cross the threshold on both sides (a flat trace,
    or a peak cut off by the edge of the sweep) – a width is then not defined."""
    peak_idx = int(np.argmax(lv))
    half = float(lv[peak_idx]) - drop_db
    above = np.where(lv >= half)[0]
    if above.size == 0:
        return None
    a, b = int(above[0]), int(above[-1])
    if a == 0 or b == len(w) - 1:
        return None
    lo = _crossing(w, lv, a - 1, a, half)
    hi = _crossing(w, lv, b + 1, b, half)
    if hi <= lo:
        return None
    return lo, hi, half


def analyze(wavelengths, levels, options):
    """Run the analyses selected in ``options`` on one trace. Returns ``(results, overlays)``.

    ``options``: boolean flags "Peak Search", "FWHM", "SNR", "SRS", "Total Power" and a
    "Power Content" list of ``{"start": nm, "stop": nm}`` ranges.
    """
    opts = normalize_options(options)
    w = np.asarray(wavelengths, dtype=float)
    lv = np.asarray(levels, dtype=float)
    results: dict[str, float] = {}
    overlays: dict = {}
    n = min(w.size, lv.size)
    if n == 0:
        return results, overlays
    w, lv = w[:n], lv[:n]
    good = np.isfinite(w) & np.isfinite(lv)
    w, lv = w[good], lv[good]
    if w.size == 0:
        return results, overlays
    order = np.argsort(w, kind="stable")
    w, lv = w[order], lv[order]

    peak_idx = int(np.argmax(lv))
    peak_wl = float(w[peak_idx])
    peak_lvl = float(lv[peak_idx])
    linear = 10.0 ** (lv / 10.0)

    if opts["Peak Search"]:
        results["Peak Wavelength"] = peak_wl
        results["Peak Level"] = peak_lvl
        overlays["peak"] = (peak_wl, peak_lvl)

    if opts["FWHM"]:
        f = fwhm(w, lv)
        if f is not None:
            lo, hi, half = f
            results["FWHM"] = hi - lo
            results["Center Wavelength"] = 0.5 * (lo + hi)
            overlays["fwhm"] = (lo, hi, half)

    if opts["SNR"]:
        # Peak level minus the highest level outside a +/-10 nm window around the peak.
        # Strictly a side-mode suppression figure rather than a true SNR; see the README.
        mask = (w < peak_wl - SNR_EXCLUSION_NM) | (w > peak_wl + SNR_EXCLUSION_NM)
        if np.any(mask):
            j = int(np.argmax(np.where(mask, lv, -np.inf)))
            results["SNR"] = peak_lvl - float(lv[j])
            overlays["snr"] = (float(w[j]), float(lv[j]), peak_wl - SNR_EXCLUSION_NM, peak_wl + SNR_EXCLUSION_NM)

    if opts["SRS"]:
        anti = anti_stokes_wavelength(peak_wl)
        lo, hi = anti - SRS_WINDOW_NM, anti + SRS_WINDOW_NM
        mask = (w >= lo) & (w <= hi)
        if np.any(mask):
            j = int(np.argmax(np.where(mask, lv, -np.inf)))
            results["SRS"] = peak_lvl - float(lv[j])
            overlays["srs"] = (lo, hi, float(w[j]), float(lv[j]), anti)

    if opts["Total Power"]:
        total = float(linear.sum())
        results["Total Power"] = 10.0 * math.log10(total) if total > 0 else float("nan")

    ranges = opts["Power Content"]
    if ranges:
        total = float(linear.sum())
        bands = []
        for i, rng in enumerate(ranges, 1):
            mask = (w >= rng["start"]) & (w <= rng["stop"])
            pct = 100.0 * float(linear[mask].sum()) / total if total > 0 else 0.0
            results[f"Power Content {i}"] = pct
            bands.append((rng["start"], rng["stop"], pct))
        overlays["power"] = bands

    return results, overlays


def ordered(results: dict) -> list[tuple[str, float]]:
    """Results in display order (METRICS order, unknown names last)."""
    keys = list(METRICS)
    return sorted(results.items(), key=lambda kv: (keys.index(kv[0]) if kv[0] in keys else len(keys), kv[0]))
