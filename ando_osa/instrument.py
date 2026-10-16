"""Thread-safe VISA driver for Ando AQ63xx-series optical spectrum analyzers.

The command set follows the Ando AQ6315/AQ6317 family GPIB syntax
(``STAWL``/``STPWL``/``RESLN``/``SGL``/``STP``/...). All instrument I/O is serialized
through a lock so the GUI thread and background workers can safely share one connection.
Every command and answer is logged at DEBUG level (the app's Log page shows them).
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

# Wavelength limits of the AQ6315A, the widest of the family (the AQ6317B covers
# 600-1750 nm). A first-line sanity check for user input; the instrument still
# enforces its own range.
WAVELENGTH_MIN_NM = 350.0
WAVELENGTH_MAX_NM = 1750.0

RESOLUTIONS_NM = ("0.01", "0.02", "0.05", "0.1", "0.2", "0.5", "1.0", "2.0")

SENSITIVITY_MODES = (
    ("Mid (SMID)", "SMID"),
    ("Normal Hold (SNHD)", "SNHD"),
    ("High 1 (SHI1)", "SHI1"),
    ("High 2 (SHI2)", "SHI2"),
    ("High 3 (SHI3)", "SHI3"),
    ("High 4 (SHI4)", "SHI4"),
)
SENSITIVITY_CMDS = tuple(cmd for _label, cmd in SENSITIVITY_MODES)

TRACES = ("A", "B", "C")
TRACE_MODES = {"A": ("WRTA", "FIXA", "MAXA", "RAVA"),
               "B": ("WRTB", "FIXB", "MINB", "RAVB"),
               "C": ("WRTC", "FIXC")}
TRACE_MODE_LABELS = {"WRT": "write", "FIX": "fix (hold)", "MAX": "max hold", "MIN": "min hold",
                     "RAV": "rolling average"}

# NOTE: the AQ6317 manual documents ACTV0/1/2 for traces A/B/C. An earlier version of
# this tool sent ACTV3 for trace C, which the instrument silently ignores. Verify on
# your unit if trace C selection misbehaves.
_ACTIVE_TRACE_CMD = {"A": "ACTV0", "B": "ACTV1", "C": "ACTV2"}
_WAVE_CMD = {"A": "WDATA", "B": "WDATB", "C": "WDATC"}
_LEVEL_CMD = {"A": "LDATA", "B": "LDATB", "C": "LDATC"}

SCAN_TIMEOUT_MS = 2000
DEFAULT_TIMEOUT_MS = 10000
TRACE_READ_TIMEOUT_MS = 30000

PEAK_HOLD_MIN_MS = 1
PEAK_HOLD_MAX_MS = 9999


def trace_mode_label(cmd: str) -> str:
    """'MAXA' -> 'MAXA – max hold'."""
    return f"{cmd} – {TRACE_MODE_LABELS.get(cmd[:3], cmd)}"


def validate_sweep_range(start_nm, stop_nm):
    """Raise ValueError if the sweep range is out of bounds or inverted."""
    if not (WAVELENGTH_MIN_NM <= start_nm <= WAVELENGTH_MAX_NM):
        raise ValueError(
            f"Start wavelength {start_nm:g} nm is outside the instrument range "
            f"({WAVELENGTH_MIN_NM:g}-{WAVELENGTH_MAX_NM:g} nm).")
    if not (WAVELENGTH_MIN_NM <= stop_nm <= WAVELENGTH_MAX_NM):
        raise ValueError(
            f"Stop wavelength {stop_nm:g} nm is outside the instrument range "
            f"({WAVELENGTH_MIN_NM:g}-{WAVELENGTH_MAX_NM:g} nm).")
    if stop_nm <= start_nm:
        raise ValueError("Stop wavelength must be greater than start wavelength.")


def _parse_trace_block(raw):
    """Parse a WDATx/LDATx response: '<count>, v1, v2, ...' -> [v1, v2, ...]."""
    return [float(x) for x in raw.split(",")[1:] if x.strip()]


# ------------------------------------------------------------------ VISA plumbing
def open_resource_manager(backend: str | None = None):
    """A pyvisa ResourceManager: the system backend (NI-VISA, Keysight IO Libraries)
    first, ``pyvisa-py`` as the fallback. Raises RuntimeError when neither loads."""
    import pyvisa
    errors = []
    for be in ([backend] if backend else ["", "@py"]):
        try:
            rm = pyvisa.ResourceManager(be) if be else pyvisa.ResourceManager()
            log.info("VISA backend: %s", be or "system default")
            return rm
        except Exception as ex:  # noqa: BLE001 - try the next backend
            errors.append(f"{be or 'default'}: {ex}")
            log.debug("VISA backend %s not available: %s", be or "default", ex)
    raise RuntimeError("No VISA backend could be loaded (" + "; ".join(errors) + "). "
                       "Install NI-VISA or Keysight IO Libraries, or pyvisa-py.")


def probe_resources(resource_manager, timeout_ms: int = SCAN_TIMEOUT_MS, stop=None):
    """``[(resource name, *IDN? answer or '')]`` for every VISA resource. Each session is
    closed again so the scan does not leak. ``stop()`` returning True ends the scan early."""
    found = []
    try:
        names = list(resource_manager.list_resources())
    except Exception:  # noqa: BLE001 - a backend without any interface
        log.exception("VISA resource listing failed")
        return found
    for name in names:
        if stop is not None and stop():
            break
        inst, idn = None, ""
        try:
            inst = resource_manager.open_resource(name)
            inst.timeout = timeout_ms
            inst.write("*IDN?")
            idn = inst.read().strip()
        except Exception:  # noqa: BLE001 - a device that does not talk SCPI, a busy port
            log.debug("No answer at %s", name, exc_info=True)
        finally:
            if inst is not None:
                try:
                    inst.close()
                except Exception:  # noqa: BLE001
                    pass
        found.append((name, idn))
        log.info("VISA %s: %s", name, idn or "(no *IDN? answer)")
    return found


def is_ando(idn: str) -> bool:
    return "ANDO" in (idn or "").upper()


class AndoOSA:
    """One connected Ando OSA. Use :meth:`find` or :meth:`open` to get one."""

    is_simulated = False

    def __init__(self, resource, idn="", name=""):
        self._res = resource
        self._lock = threading.Lock()
        self.idn = idn
        self.name = name

    @classmethod
    def open(cls, resource_manager, name: str, require_ando: bool = True) -> "AndoOSA":
        """Open one VISA resource by name and check that an Ando answers ``*IDN?``."""
        inst = resource_manager.open_resource(name)
        try:
            inst.timeout = SCAN_TIMEOUT_MS
            inst.write("*IDN?")
            idn = inst.read().strip()
            if require_ando and not is_ando(idn):
                raise ValueError(f"{name} answers '{idn}', which is not an Ando OSA.")
            inst.timeout = DEFAULT_TIMEOUT_MS
        except Exception:
            try:
                inst.close()
            except Exception:  # noqa: BLE001
                pass
            raise
        log.info("Opened %r at %s", idn, name)
        return cls(inst, idn, name)

    @classmethod
    def find(cls, resource_manager, stop=None):
        """Scan VISA resources and return the first Ando OSA found, or None."""
        for name, idn in probe_resources(resource_manager, stop=stop):
            if is_ando(idn):
                try:
                    return cls.open(resource_manager, name)
                except Exception:  # noqa: BLE001 - vanished between the probe and the open
                    log.exception("Could not reopen %s", name)
        return None

    # ------------------------------------------------------------- raw I/O
    def write(self, command):
        log.debug(">> %s", command)
        with self._lock:
            self._res.write(command)

    def query(self, command):
        log.debug(">> %s", command)
        with self._lock:
            self._res.write(command)
            answer = self._res.read()
        log.debug("<< %s", answer.strip()[:120])
        return answer

    def close(self):
        with self._lock:
            self._res.close()

    # ------------------------------------------------------- initialization
    def initialize(self):
        """Put the instrument in a known state: CW, write to A, blank B/C."""
        for command in ("CLMES", "WRTA", "DSPA", _ACTIVE_TRACE_CMD["A"],
                        "FIXB", "BLKB", "FIXC", "BLKC"):
            self.write(command)

    # --------------------------------------------------------------- sweep
    def configure_sweep(self, start_nm, stop_nm, resolution_nm, sensitivity_cmd):
        validate_sweep_range(start_nm, stop_nm)
        self.write(f"STAWL{start_nm:.2f}")
        self.write(f"STPWL{stop_nm:.2f}")
        self.write(f"RESLN{resolution_nm}")
        self.write(sensitivity_cmd)

    def start_single_sweep(self):
        self.write("SGL")

    def abort_sweep(self):
        """Stop a running sweep (``STP``)."""
        self.write("STP")

    def sweep_in_progress(self):
        """True while a sweep is running (SWEEP? returns non-zero)."""
        return int(self.query("SWEEP?").strip()) != 0

    def set_reference_to_peak(self):
        self.write("REF=P")

    # --------------------------------------------------------------- traces
    def read_trace(self, trace):
        """Return (wavelengths_nm, levels_dbm) for trace 'A', 'B' or 'C'.

        Both lists are truncated to the shorter of the two in case the instrument
        returns mismatched point counts.
        """
        with self._lock:
            previous_timeout = self._res.timeout
            self._res.timeout = TRACE_READ_TIMEOUT_MS
            try:
                log.debug(">> %s", _WAVE_CMD[trace])
                self._res.write(_WAVE_CMD[trace])
                wave_raw = self._res.read()
                log.debug(">> %s", _LEVEL_CMD[trace])
                self._res.write(_LEVEL_CMD[trace])
                level_raw = self._res.read()
            finally:
                self._res.timeout = previous_timeout
        wavelengths = _parse_trace_block(wave_raw)
        levels = _parse_trace_block(level_raw)
        n = min(len(wavelengths), len(levels))
        log.debug("<< trace %s: %d points", trace, n)
        return wavelengths[:n], levels[:n]

    def set_active_trace(self, trace):
        self.write(_ACTIVE_TRACE_CMD[trace])

    def set_trace_mode(self, mode_cmd):
        """Send a trace mode command such as WRTA, FIXB, MAXA, RAVB..."""
        self.write(mode_cmd)

    def set_trace_display(self, trace, visible):
        self.write(("DSP" if visible else "BLK") + trace)

    # ------------------------------------------------------ measurement mode
    def set_cw_mode(self):
        self.write("CLMES")

    def set_pulsed_mode(self, peak_hold_ms):
        if not (PEAK_HOLD_MIN_MS <= peak_hold_ms <= PEAK_HOLD_MAX_MS):
            raise ValueError(f"Peak hold must be {PEAK_HOLD_MIN_MS}-{PEAK_HOLD_MAX_MS} ms.")
        self.write("PLMES")
        self.write(f"PKHLD{peak_hold_ms}")
