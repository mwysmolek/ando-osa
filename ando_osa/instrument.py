"""Thread-safe VISA driver for Ando AQ63xx-series optical spectrum analyzers.

The command set follows the Ando AQ6315/AQ6317 family GPIB syntax
(``STAWL``/``STPWL``/``RESLN``/``SGL``/...). All instrument I/O is
serialized through a lock so the GUI thread and background workers can
safely share one connection.
"""

import logging
import threading

log = logging.getLogger(__name__)

# Wavelength limits of the AQ6315A, the widest of the family (the
# AQ6317B covers 600-1750 nm). This is a first-line sanity check for
# user input; the instrument still enforces its own range.
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

TRACES = ("A", "B", "C")

# NOTE: the AQ6317 manual documents ACTV0/1/2 for traces A/B/C. An
# earlier version of this tool sent ACTV3 for trace C, which the
# instrument silently ignores. Verify on your unit if trace C
# selection misbehaves.
_ACTIVE_TRACE_CMD = {"A": "ACTV0", "B": "ACTV1", "C": "ACTV2"}
_WAVE_CMD = {"A": "WDATA", "B": "WDATB", "C": "WDATC"}
_LEVEL_CMD = {"A": "LDATA", "B": "LDATB", "C": "LDATC"}

SCAN_TIMEOUT_MS = 2000
DEFAULT_TIMEOUT_MS = 10000
TRACE_READ_TIMEOUT_MS = 30000

PEAK_HOLD_MIN_MS = 1
PEAK_HOLD_MAX_MS = 9999


def validate_sweep_range(start_nm, stop_nm):
    """Raise ValueError if the sweep range is out of bounds or inverted."""
    if not (WAVELENGTH_MIN_NM <= start_nm <= WAVELENGTH_MAX_NM):
        raise ValueError(
            f"Start wavelength {start_nm:g} nm is outside the instrument range "
            f"({WAVELENGTH_MIN_NM:g}-{WAVELENGTH_MAX_NM:g} nm)."
        )
    if not (WAVELENGTH_MIN_NM <= stop_nm <= WAVELENGTH_MAX_NM):
        raise ValueError(
            f"Stop wavelength {stop_nm:g} nm is outside the instrument range "
            f"({WAVELENGTH_MIN_NM:g}-{WAVELENGTH_MAX_NM:g} nm)."
        )
    if stop_nm <= start_nm:
        raise ValueError("Stop wavelength must be greater than start wavelength.")


def _parse_trace_block(raw):
    """Parse a WDATx/LDATx response: '<count>, v1, v2, ...' -> [v1, v2, ...]."""
    return [float(x) for x in raw.split(",")[1:] if x.strip()]


class AndoOSA:
    """One connected Ando OSA. Use :meth:`find` to locate and open one."""

    def __init__(self, resource, idn=""):
        self._res = resource
        self._lock = threading.Lock()
        self.idn = idn

    @classmethod
    def find(cls, resource_manager):
        """Scan VISA resources and return the first Ando OSA found, or None.

        Non-matching resources are closed again so the scan does not leak
        VISA sessions.
        """
        for name in resource_manager.list_resources():
            inst = None
            try:
                inst = resource_manager.open_resource(name)
                inst.timeout = SCAN_TIMEOUT_MS
                inst.write("*IDN?")
                idn = inst.read().strip()
                if "ANDO" in idn.upper():
                    inst.timeout = DEFAULT_TIMEOUT_MS
                    log.info("Found Ando OSA %r at %s", idn, name)
                    return cls(inst, idn)
            except Exception:
                log.debug("No Ando OSA at %s", name, exc_info=True)
            if inst is not None:
                try:
                    inst.close()
                except Exception:
                    pass
        return None

    # ------------------------------------------------------------- raw I/O
    def write(self, command):
        with self._lock:
            self._res.write(command)

    def query(self, command):
        with self._lock:
            self._res.write(command)
            return self._res.read()

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

    def sweep_in_progress(self):
        """True while a sweep is running (SWEEP? returns non-zero)."""
        return int(self.query("SWEEP?").strip()) != 0

    def set_reference_to_peak(self):
        self.write("REF=P")

    # --------------------------------------------------------------- traces
    def read_trace(self, trace):
        """Return (wavelengths_nm, levels_dbm) for trace 'A', 'B' or 'C'.

        Both lists are truncated to the shorter of the two in case the
        instrument returns mismatched point counts.
        """
        with self._lock:
            previous_timeout = self._res.timeout
            self._res.timeout = TRACE_READ_TIMEOUT_MS
            try:
                self._res.write(_WAVE_CMD[trace])
                wave_raw = self._res.read()
                self._res.write(_LEVEL_CMD[trace])
                level_raw = self._res.read()
            finally:
                self._res.timeout = previous_timeout
        wavelengths = _parse_trace_block(wave_raw)
        levels = _parse_trace_block(level_raw)
        n = min(len(wavelengths), len(levels))
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
            raise ValueError(
                f"Peak hold must be {PEAK_HOLD_MIN_MS}-{PEAK_HOLD_MAX_MS} ms."
            )
        self.write("PLMES")
        self.write(f"PKHLD{peak_hold_ms}")
