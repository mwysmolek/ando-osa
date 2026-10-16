"""The simulated OSA behaves like the driver: sweeps take time, traces hold, modes work."""
import time

import numpy as np
import pytest

from ando_osa.simulator import SimulatedOSA


def floor(w, lv, above_nm=1180.0):
    """Median level where nothing but noise is: beyond the Raman Stokes line."""
    return float(np.median([v for x, v in zip(w, lv) if x > above_nm]))


def sweep(sim, trace="A"):
    sim.start_single_sweep()
    deadline = time.time() + 5
    while sim.sweep_in_progress():
        assert time.time() < deadline
        time.sleep(0.01)
    return sim.read_trace(trace)


def test_sweep_lifecycle_and_spectrum():
    sim = SimulatedOSA(seed=1, sweep_seconds=0.05, drift=False)
    assert sim.is_simulated and "ANDO" in sim.query("*IDN?")
    sim.initialize()
    sim.configure_sweep(1000, 1200, "0.1", "SMID")
    sim.start_single_sweep()
    assert sim.sweep_in_progress() is True
    time.sleep(0.08)
    assert sim.sweep_in_progress() is False
    w, lv = sim.read_trace("A")
    assert len(w) == len(lv) == 4001 and w[0] == 1000.0 and w[-1] == 1200.0
    i = int(np.argmax(lv))
    assert abs(w[i] - 1064.0) < 0.1 and 9.0 < lv[i] < 11.0
    assert -70 < floor(w, lv) < -58                              # SMID noise floor
    assert sim.read_trace("B") == ([], [])                        # never written
    assert sim.commands[0] == "*IDN?" and sim.commands[1:4] == ["CLMES", "WRTA", "DSPA"] and "SGL" in sim.commands


def test_sensitivity_and_pulsed_mode_change_the_floor():
    sim = SimulatedOSA(seed=2, sweep_seconds=0.0, drift=False)
    sim.configure_sweep(1000, 1200, "0.1", "SMID")
    w, mid = sweep(sim)
    sim.configure_sweep(1000, 1200, "0.1", "SHI3")
    w3, hi3 = sweep(sim)
    assert floor(w, mid) - floor(w3, hi3) > 10
    sim.set_pulsed_mode(5)
    assert sim.measurement_mode == "PULSED" and sim.peak_hold_ms == 5
    with pytest.raises(ValueError):
        sim.set_pulsed_mode(0)
    sim.set_cw_mode()
    assert sim.measurement_mode == "CW"


def test_trace_modes_hold_max_and_fix():
    sim = SimulatedOSA(seed=3, sweep_seconds=0.0, drift=False)
    sim.configure_sweep(1050, 1080, "0.1", "SMID")
    sim.set_active_trace("B")
    sim.set_trace_mode("MAXB")
    _w, first = sweep(sim, "B")
    for _ in range(3):
        _w, held = sweep(sim, "B")
    assert all(h >= f - 1e-9 for h, f in zip(held, first))
    sim.set_trace_mode("FIXB")
    _w, fixed = sweep(sim, "B")
    assert fixed == held                                           # a fixed trace keeps its data
    sim.set_trace_mode("WRTB")
    _w, written = sweep(sim, "B")
    assert written != held
    sim.set_trace_display("B", False)
    assert sim.displayed["B"] is False
    sim.start_single_sweep()
    sim.abort_sweep()
    assert sim.sweep_in_progress() is False
    sim.close()


def test_bad_range_and_points_cap():
    sim = SimulatedOSA(sweep_seconds=0.0)
    with pytest.raises(ValueError):
        sim.configure_sweep(1500, 1000, "0.1", "SMID")
    sim.configure_sweep(350, 1750, "0.01", "SMID")
    w, _ = sweep(sim)
    assert len(w) == 20001
