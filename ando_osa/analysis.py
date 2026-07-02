"""Trace analysis routines for OSA spectra.

``analyze`` operates on wavelength (nm) / level (dBm) arrays and returns
two dicts: numeric results (what gets written to the ``*_anal.csv``
files) and overlay geometry for drawing markers on the plot.
"""

import numpy as np

C_NM_THZ = 299792.458    # speed of light, in nm * THz
RAMAN_SHIFT_THZ = 13.2   # peak Raman gain shift of fused silica
SNR_EXCLUSION_NM = 10.0  # window around the peak excluded from the noise search
SRS_WINDOW_NM = 5.0      # search window around the expected anti-Stokes wavelength
FWHM_DROP_DB = 3.0


def analyze(wavelengths, levels, options):
    """Run the analyses selected in ``options`` on one trace.

    ``options`` is the dict produced by the analysis dialog: boolean flags
    "Peak Search", "SNR", "SRS", "FWHM" and a "Power Content" list of
    ``{"start": nm, "stop": nm}`` ranges.

    Returns ``(results, overlays)``.
    """
    w = np.asarray(wavelengths, dtype=float)
    l = np.asarray(levels, dtype=float)
    results = {}
    overlays = {}
    if w.size == 0 or l.size == 0:
        return results, overlays

    peak_idx = int(np.argmax(l))
    peak_wl = float(w[peak_idx])
    peak_lvl = float(l[peak_idx])

    if options.get("Peak Search"):
        results["Peak Wavelength"] = peak_wl
        results["Peak Level"] = peak_lvl
        overlays["peak"] = (peak_wl, peak_lvl)

    if options.get("SNR"):
        # Peak level minus the highest level outside a +/-10 nm window
        # around the peak. Strictly this is a side-mode suppression
        # figure rather than a true SNR; see the README.
        mask = (w < peak_wl - SNR_EXCLUSION_NM) | (w > peak_wl + SNR_EXCLUSION_NM)
        if np.any(mask):
            results["SNR"] = peak_lvl - float(np.max(l[mask]))

    if options.get("SRS"):
        # Expected anti-Stokes wavelength for the fused-silica Raman
        # shift: lambda_as = lambda_p / (1 + dnu * lambda_p / c). The
        # anti-Stokes line sits at a *shorter* wavelength than the pump.
        anti_stokes_wl = peak_wl / (1.0 + RAMAN_SHIFT_THZ * peak_wl / C_NM_THZ)
        mask = (w >= anti_stokes_wl - SRS_WINDOW_NM) & (w <= anti_stokes_wl + SRS_WINDOW_NM)
        if np.any(mask):
            results["SRS"] = peak_lvl - float(np.max(l[mask]))

    if options.get("FWHM"):
        # Width between the outermost -3 dB crossings. If several peaks
        # rise above the threshold this spans all of them.
        half_level = peak_lvl - FWHM_DROP_DB
        above = np.where(l >= half_level)[0]
        if above.size > 1:
            lo, hi = float(w[above[0]]), float(w[above[-1]])
            results["FWHM"] = hi - lo
            overlays["fwhm"] = (lo, hi, half_level)

    ranges = options.get("Power Content") or []
    if ranges:
        linear = 10.0 ** (l / 10.0)
        total = float(linear.sum())
        for i, rng in enumerate(ranges, 1):
            mask = (w >= rng["start"]) & (w <= rng["stop"])
            in_range = 100.0 * float(linear[mask].sum()) / total if total > 0 else 0.0
            results[f"Power Content {i}"] = in_range

    return results, overlays
