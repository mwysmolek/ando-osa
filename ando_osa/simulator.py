"""A simulated Ando OSA with the driver's interface, for demos, tests and the CI smoke test.

It answers the same commands the real instrument gets (``STAWL``, ``SGL``, ``SWEEP?``,
``WDATA`` …) and produces a plausible spectrum: a 1064 nm fibre-laser line on an ASE
pedestal, its Raman Stokes and anti-Stokes lines, a side mode, and a noise floor that
drops with the sensitivity setting. Wavelength and power drift slowly so time-lapses
show something.
"""
from __future__ import annotations

import logging
import math
import threading
import time

import numpy as np

from .analysis import C_NM_THZ, RAMAN_SHIFT_THZ
from .instrument import (PEAK_HOLD_MAX_MS, PEAK_HOLD_MIN_MS, SENSITIVITY_CMDS, TRACES,
                         validate_sweep_range)

log = logging.getLogger(__name__)

NOISE_FLOOR_DBM = {"SMID": -65.0, "SNHD": -60.0, "SHI1": -72.0, "SHI2": -78.0, "SHI3": -83.0, "SHI4": -88.0}
SWEEP_SECONDS = {"SMID": 0.6, "SNHD": 0.5, "SHI1": 1.2, "SHI2": 2.0, "SHI3": 3.0, "SHI4": 4.5}
PUMP_NM = 1064.0
PUMP_DBM = 10.0
MAX_POINTS = 20001
_ACTIVE = {"ACTV0": "A", "ACTV1": "B", "ACTV2": "C"}


class SimulatedOSA:
    """Same methods as :class:`ando_osa.instrument.AndoOSA`; nothing is connected."""

    is_simulated = True
    idn = "ANDO,AQ6317B,SIMULATOR,1.00"
    name = "SIM::AQ6317B::INSTR"

    def __init__(self, seed: int | None = None, sweep_seconds: float | None = None, drift: bool = True):
        self._lock = threading.RLock()
        self._rng = np.random.default_rng(seed)
        self.sweep_seconds = sweep_seconds          # None: realistic, depends on sensitivity
        self.drift = drift
        self.start_nm, self.stop_nm, self.resolution_nm, self.sensitivity = 1000.0, 1500.0, 0.1, "SMID"
        self.active = "A"
        self.modes = {"A": "WRT", "B": "FIX", "C": "FIX"}
        self.displayed = {"A": True, "B": False, "C": False}
        self.measurement_mode, self.peak_hold_ms = "CW", 100
        self._traces: dict[str, tuple[list, list] | None] = {t: None for t in TRACES}
        self._sweep_end: float | None = None
        self._sweep_trace = "A"
        self._t0 = time.monotonic()
        self.commands: list[str] = []
        self.sweeps = 0

    # ------------------------------------------------------------- raw I/O
    def write(self, command: str) -> None:
        with self._lock:
            self.commands.append(command)
            log.debug(">> %s (sim)", command)
            self._handle(command)

    def query(self, command: str) -> str:
        with self._lock:
            self.commands.append(command)
            if command.startswith("*IDN"):
                return self.idn
            if command.startswith("SWEEP?"):
                return "1" if self._in_progress() else "0"
            if command.startswith("WDAT") or command.startswith("LDAT"):
                trace = command[4]
                self._finish_sweep()
                data = self._traces.get(trace) or ([], [])
                vals = data[0] if command.startswith("WDAT") else data[1]
                return ",".join([str(len(vals)), *(f"{v:.4f}" for v in vals)])
            return "0"

    def close(self) -> None:
        pass

    def _handle(self, c: str) -> None:
        try:
            if c.startswith("STAWL"):
                self.start_nm = float(c[5:])
            elif c.startswith("STPWL"):
                self.stop_nm = float(c[5:])
            elif c.startswith("RESLN"):
                self.resolution_nm = float(c[5:])
            elif c in SENSITIVITY_CMDS:
                self.sensitivity = c
            elif c == "SGL":
                self._begin_sweep()
            elif c == "STP":
                self._sweep_end = None
            elif c in _ACTIVE:
                self.active = _ACTIVE[c]
            elif c[:3] in ("WRT", "FIX", "MAX", "MIN", "RAV") and c[3:] in TRACES:
                self.modes[c[3:]] = c[:3]
            elif c[:3] in ("DSP", "BLK") and c[3:] in TRACES:
                self.displayed[c[3:]] = c[:3] == "DSP"
            elif c == "CLMES":
                self.measurement_mode = "CW"
            elif c == "PLMES":
                self.measurement_mode = "PULSED"
            elif c.startswith("PKHLD"):
                self.peak_hold_ms = int(c[5:])
        except ValueError:
            log.warning("simulator: cannot parse %r", c)

    # ------------------------------------------------------- driver interface
    def initialize(self) -> None:
        for command in ("CLMES", "WRTA", "DSPA", "ACTV0", "FIXB", "BLKB", "FIXC", "BLKC"):
            self.write(command)

    def configure_sweep(self, start_nm, stop_nm, resolution_nm, sensitivity_cmd) -> None:
        validate_sweep_range(start_nm, stop_nm)
        self.write(f"STAWL{start_nm:.2f}")
        self.write(f"STPWL{stop_nm:.2f}")
        self.write(f"RESLN{resolution_nm}")
        self.write(sensitivity_cmd)

    def start_single_sweep(self) -> None:
        self.write("SGL")

    def abort_sweep(self) -> None:
        self.write("STP")

    def sweep_in_progress(self) -> bool:
        return self.query("SWEEP?").strip() != "0"

    def set_reference_to_peak(self) -> None:
        self.write("REF=P")

    def read_trace(self, trace: str):
        wave = self.query(f"WDAT{trace}")
        level = self.query(f"LDAT{trace}")
        w = [float(x) for x in wave.split(",")[1:] if x.strip()]
        lv = [float(x) for x in level.split(",")[1:] if x.strip()]
        n = min(len(w), len(lv))
        return w[:n], lv[:n]

    def set_active_trace(self, trace: str) -> None:
        self.write({"A": "ACTV0", "B": "ACTV1", "C": "ACTV2"}[trace])

    def set_trace_mode(self, mode_cmd: str) -> None:
        self.write(mode_cmd)

    def set_trace_display(self, trace: str, visible: bool) -> None:
        self.write(("DSP" if visible else "BLK") + trace)

    def set_cw_mode(self) -> None:
        self.write("CLMES")

    def set_pulsed_mode(self, peak_hold_ms: int) -> None:
        if not (PEAK_HOLD_MIN_MS <= peak_hold_ms <= PEAK_HOLD_MAX_MS):
            raise ValueError(f"Peak hold must be {PEAK_HOLD_MIN_MS}-{PEAK_HOLD_MAX_MS} ms.")
        self.write("PLMES")
        self.write(f"PKHLD{peak_hold_ms}")

    # ----------------------------------------------------------- the sweep
    def _begin_sweep(self) -> None:
        dur = self.sweep_seconds
        if dur is None:
            n = self._points()
            dur = SWEEP_SECONDS.get(self.sensitivity, 0.6) * (0.5 + n / 10000.0)
        self._sweep_trace = self.active
        self._sweep_end = time.monotonic() + max(0.0, float(dur))

    def _in_progress(self) -> bool:
        if self._sweep_end is None:
            return False
        if time.monotonic() >= self._sweep_end:
            self._finish_sweep()
            return False
        return True

    def _finish_sweep(self) -> None:
        if self._sweep_end is None or time.monotonic() < self._sweep_end:
            return
        self._sweep_end = None
        w, lv = self.spectrum()
        trace = self._sweep_trace
        mode = self.modes.get(trace, "WRT")
        old = self._traces.get(trace)
        same = old is not None and len(old[0]) == len(w) and old[0] and abs(old[0][0] - w[0]) < 1e-9
        if mode == "FIX" and old is not None:
            pass                                    # a fixed trace keeps what it holds
        elif mode == "MAX" and same:
            lv = list(np.maximum(old[1], lv))
            self._traces[trace] = (w, lv)
        elif mode == "MIN" and same:
            lv = list(np.minimum(old[1], lv))
            self._traces[trace] = (w, lv)
        elif mode == "RAV" and same:
            lv = list(0.7 * np.asarray(old[1]) + 0.3 * np.asarray(lv))
            self._traces[trace] = (w, lv)
        else:
            self._traces[trace] = (w, lv)
        self.sweeps += 1

    def _points(self) -> int:
        span = max(self.stop_nm - self.start_nm, 1e-6)
        return int(min(MAX_POINTS, max(51, round(span / (self.resolution_nm / 2.0)) + 1)))

    def spectrum(self):
        """(wavelengths, levels_dBm) of the current settings, right now."""
        n = self._points()
        w = np.linspace(self.start_nm, self.stop_nm, n)
        t = (time.monotonic() - self._t0) if self.drift else 0.0
        pump_nm = PUMP_NM + 0.03 * math.sin(t / 47.0)
        pump_dbm = PUMP_DBM + 0.4 * math.sin(t / 29.0) + float(self._rng.normal(0, 0.03))
        res = max(self.resolution_nm, 0.01)
        sigma_line = 0.08 / 2.3548                 # a 0.08 nm wide laser line
        sigma = math.sqrt(sigma_line ** 2 + (res / 2.3548) ** 2)
        stokes_nm = pump_nm / (1.0 - RAMAN_SHIFT_THZ * pump_nm / C_NM_THZ)
        anti_nm = pump_nm / (1.0 + RAMAN_SHIFT_THZ * pump_nm / C_NM_THZ)

        def gauss(center, width_sigma, peak_dbm):
            return 10 ** (peak_dbm / 10.0) * np.exp(-0.5 * ((w - center) / width_sigma) ** 2)

        lin = gauss(pump_nm, sigma, pump_dbm)
        lin += gauss(pump_nm + 1.6, sigma, pump_dbm - 42.0)                  # a side mode
        lin += gauss(1072.0, 14.0, pump_dbm - 46.0)                           # ASE pedestal
        lin += gauss(stokes_nm, 3.5, pump_dbm - 28.0 + 0.6 * math.sin(t / 19.0))   # Raman Stokes
        lin += gauss(anti_nm, 1.5, pump_dbm - 58.0)                           # anti-Stokes
        floor_dbm = NOISE_FLOOR_DBM.get(self.sensitivity, -65.0)
        if self.measurement_mode == "PULSED":
            floor_dbm += 6.0
        floor = 10 ** (floor_dbm / 10.0) * np.exp(self._rng.normal(0.0, 0.35, n))
        levels = 10.0 * np.log10(lin + floor)
        return [float(x) for x in w], [round(float(x), 3) for x in levels]
