"""The trace analysis: peak, interpolated FWHM, SNR window, anti-Stokes side, powers."""
import math

import numpy as np
import pytest

from ando_osa import analysis as A


def trace(center=1064.0, fwhm=0.5, peak=10.0, floor=-60.0, start=1000.0, stop=1100.0, step=0.02, extra=()):
    w = np.arange(start, stop + step / 2, step)
    lin = 10 ** (peak / 10) * np.exp(-0.5 * ((w - center) / (fwhm / 2.3548)) ** 2) + 10 ** (floor / 10)
    for c, fw, p in extra:
        lin += 10 ** (p / 10) * np.exp(-0.5 * ((w - c) / (fw / 2.3548)) ** 2)
    return list(w), list(10 * np.log10(lin))


def test_peak_fwhm_and_centre_are_interpolated():
    w, lv = trace()
    r, ov = A.analyze(w, lv, A.DEFAULT_OPTIONS)
    assert abs(r["Peak Wavelength"] - 1064.0) <= 0.02 and abs(r["Peak Level"] - 10.0) < 0.01
    assert abs(r["FWHM"] - 0.5) < 0.01                      # 0.02 nm sampling, interpolated crossings
    assert abs(r["Center Wavelength"] - 1064.0) < 0.005
    lo, hi, half = ov["fwhm"]
    assert hi - lo == pytest.approx(r["FWHM"]) and half == pytest.approx(r["Peak Level"] - 3.0)
    assert ov["peak"] == (r["Peak Wavelength"], r["Peak Level"])
    assert "SNR" not in r and "SRS" not in r                 # off by default
    assert r["Total Power"] == pytest.approx(10 * math.log10(sum(10 ** (np.asarray(lv) / 10))))


def test_snr_ignores_the_window_around_the_peak():
    w, lv = trace(extra=[(1066.0, 0.5, -20.0), (1090.0, 1.0, -30.0)])    # side mode inside ±10 nm, a line outside
    r, ov = A.analyze(w, lv, {"Peak Search": True, "SNR": True})
    assert abs(r["SNR"] - 40.0) < 0.2
    wl, lvl, lo, hi = ov["snr"]
    assert abs(wl - 1090.0) < 0.05 and (lo, hi) == pytest.approx((1054.0, 1074.0))


def test_srs_looks_on_the_anti_stokes_side():
    anti = A.anti_stokes_wavelength(1064.0)
    stokes = A.stokes_wavelength(1064.0)
    assert anti < 1064.0 < stokes and abs(anti - 1016.4) < 0.1 and abs(stokes - 1116.6) < 0.5
    w, lv = trace(extra=[(anti, 1.0, -40.0), (stokes, 1.0, -15.0)])
    r, ov = A.analyze(w, lv, {"SRS": True, "Peak Search": True})
    assert abs(r["SRS"] - 50.0) < 0.2                        # the Stokes line is not what is measured
    lo, hi, wl, lvl, centre = ov["srs"]
    assert lo < wl < hi and centre == pytest.approx(anti)


def test_power_content_and_total_power():
    w, lv = trace()
    opts = {"Total Power": True, "Power Content": [{"start": 1000, "stop": 1100}, {"start": 1063, "stop": 1065},
                                                   {"start": 1080, "stop": 1090}]}
    r, ov = A.analyze(w, lv, opts)
    assert r["Power Content 1"] == pytest.approx(100.0)
    assert r["Power Content 2"] > 99.0 and r["Power Content 3"] < 0.01
    assert [b[2] for b in ov["power"]] == [r["Power Content 1"], r["Power Content 2"], r["Power Content 3"]]


def test_edge_cases_empty_unsorted_nan_and_flat():
    assert A.analyze([], [], A.DEFAULT_OPTIONS) == ({}, {})
    w, lv = trace()
    r1, _ = A.analyze(w, lv, A.DEFAULT_OPTIONS)
    r2, _ = A.analyze(list(reversed(w)), list(reversed(lv)), A.DEFAULT_OPTIONS)
    assert r1 == pytest.approx(r2)
    w3, lv3 = list(w), list(lv)
    lv3[10] = float("nan")
    r3, _ = A.analyze(w3, lv3, A.DEFAULT_OPTIONS)
    assert r3["Peak Wavelength"] == r1["Peak Wavelength"]
    r4, ov4 = A.analyze([1, 2, 3], [0.0, 0.0, 0.0], {"FWHM": True, "Peak Search": True})
    assert "FWHM" not in r4 and "fwhm" not in ov4           # never drops 3 dB: no width
    assert A.fwhm(np.array([1.0, 2.0, 3.0]), np.array([0.0, 10.0, 0.0])) == pytest.approx((1.7, 2.3, 7.0))


def test_options_formatting_and_order():
    opts = A.normalize_options({"SNR": 1, "Power Content": [{"start": 5, "stop": 1}, {"start": "a"}, {"start": 1, "stop": 2}] * 4})
    assert opts["SNR"] is True and opts["Peak Search"] is True and len(opts["Power Content"]) == 4
    assert A.format_value("Peak Wavelength", 1064.12345) == "1064.123 nm"
    assert A.format_value("Power Content 1", 12.345) == "12.3 %" and A.format_value("SNR", None) == "–"
    assert A.format_value("SRS", float("nan")) == "–" and A.unit_of("Total Power") == "dBm"
    assert [k for k, _ in A.ordered({"SNR": 1, "Peak Level": 2, "zzz": 3, "Peak Wavelength": 4})] == \
        ["Peak Wavelength", "Peak Level", "SNR", "zzz"]
