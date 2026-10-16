"""Background workers: the VISA scan, single / continuous sweeps and the time-lapse.

Each is a QObject moved to a QThread. They never touch widgets; results come back through
signals, files are written with the thread-safe Agg canvas.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ando_osa import storage
from ando_osa.analysis import analyze
from ando_osa.plots import render_png

log = logging.getLogger(__name__)

SWEEP_POLL_S = 0.25
ABORT_POLL_S = 0.1
DEFAULT_SWEEP_TIMEOUT_S = 40.0


@dataclass(frozen=True)
class SweepParams:
    start_nm: float
    stop_nm: float
    resolution_nm: str
    sensitivity_cmd: str

    def apply(self, osa) -> None:
        osa.configure_sweep(self.start_nm, self.stop_nm, self.resolution_nm, self.sensitivity_cmd)


class _AbortableWorker(QObject):
    """Shared abort flag and sweep-completion polling."""
    finished = Signal()
    message = Signal(str)

    def __init__(self, timeout_s: float = DEFAULT_SWEEP_TIMEOUT_S):
        super().__init__()
        self._abort = False
        self.timeout_s = float(timeout_s)

    @property
    def aborted(self) -> bool:
        return self._abort

    def stop(self) -> None:
        """Request abort. Safe to call from any thread."""
        self._abort = True

    def _wait_for_sweep(self, osa) -> bool:
        """Poll SWEEP? until the sweep finishes. True when it completed, False when aborted
        (the instrument is told to stop). Raises TimeoutError after ``timeout_s``."""
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            if self._abort:
                try:
                    osa.abort_sweep()
                except Exception:  # noqa: BLE001 - best effort
                    log.debug("STP failed", exc_info=True)
                return False
            try:
                if not osa.sweep_in_progress():
                    return True
            except Exception:  # noqa: BLE001 - transient bus error: retry until the deadline
                log.warning("SWEEP? poll failed", exc_info=True)
            time.sleep(SWEEP_POLL_S)
        try:
            osa.abort_sweep()
        except Exception:  # noqa: BLE001
            pass
        raise TimeoutError(f"Sweep did not finish within {self.timeout_s:.0f} s (Preferences ▸ sweep timeout).")

    def _sleep(self, seconds: float) -> bool:
        """Abortable sleep. False if aborted."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._abort:
                return False
            time.sleep(min(ABORT_POLL_S, max(0.0, deadline - time.monotonic())))
        return True


class ConnectWorker(_AbortableWorker):
    """Scans the VISA bus (``scanned``) and opens the Ando OSA (``connected``) without
    blocking the GUI – resource discovery can take long with pyvisa-py."""
    scanned = Signal(list)          # [(resource name, idn)]
    connected = Signal(object)      # AndoOSA or None

    def __init__(self, resource_manager, resource: Optional[str] = None, auto_connect: bool = True):
        super().__init__()
        self.rm = resource_manager
        self.resource = resource
        self.auto_connect = auto_connect

    @Slot()
    def run(self) -> None:
        osa = None
        try:
            from ando_osa.instrument import AndoOSA, is_ando, probe_resources
            if self.resource:
                osa = AndoOSA.open(self.rm, self.resource)
            else:
                found = probe_resources(self.rm, stop=lambda: self._abort)
                self.scanned.emit(found)
                if self.auto_connect:
                    for name, idn in found:
                        if is_ando(idn) and not self._abort:
                            osa = AndoOSA.open(self.rm, name)
                            break
        except Exception as ex:  # noqa: BLE001 - reported, never raised into the thread
            log.exception("VISA scan / connect failed")
            self.message.emit(f"Connect failed: {ex}")
        self.connected.emit(osa)
        self.finished.emit()


class SweepWorker(_AbortableWorker):
    """One sweep – or sweep after sweep until stopped – emitting every trace."""
    dataReady = Signal(str, list, list)     # trace, wavelengths, levels
    sweepStarted = Signal(int)              # 1-based sweep counter

    def __init__(self, osa, params: SweepParams, trace: str, continuous: bool = False, ref_to_peak: bool = True,
                 timeout_s: float = DEFAULT_SWEEP_TIMEOUT_S):
        super().__init__(timeout_s)
        self.osa = osa
        self.trace = trace
        self.continuous = continuous
        self.ref_to_peak = ref_to_peak
        self._params = params
        self._params_lock = threading.Lock()
        self.count = 0

    def set_params(self, params: SweepParams) -> None:
        """New settings for the next sweep of a continuous run (any thread)."""
        with self._params_lock:
            self._params = params

    def set_continuous(self, on: bool) -> None:
        self.continuous = bool(on)

    def params(self) -> SweepParams:
        with self._params_lock:
            return self._params

    @Slot()
    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001
            log.exception("Sweep failed")
            self.message.emit(f"Sweep failed: {e}")
        finally:
            self.finished.emit()

    def _run(self) -> None:
        applied = None
        self.osa.set_active_trace(self.trace)
        while not self._abort:
            p = self.params()
            if p != applied:
                p.apply(self.osa)
                applied = p
            self.count += 1
            self.sweepStarted.emit(self.count)
            self.osa.start_single_sweep()
            if not self._wait_for_sweep(self.osa):
                self.message.emit("Sweep aborted.")
                return
            if self.ref_to_peak:
                self.osa.set_reference_to_peak()
            wavelengths, levels = self.osa.read_trace(self.trace)
            self.dataReady.emit(self.trace, wavelengths, levels)
            if not self.continuous:
                return


class TimeLapseWorker(_AbortableWorker):
    """Repeated sweeps at a fixed interval; each saved as CSV + analysis + PNG, every result
    appended to ``summary.csv`` in the run folder."""
    measurementDone = Signal(int, float, list, list, dict)   # index, elapsed s, wavelengths, levels, results

    def __init__(self, osa, params: SweepParams, trace: str, interval_s: float, count: int, directory,
                 options: dict, ref_to_peak: bool = True, timeout_s: float = DEFAULT_SWEEP_TIMEOUT_S,
                 dark_png: bool = False):
        super().__init__(timeout_s)
        self.osa = osa
        self.params = params
        self.trace = trace
        self.interval_s = float(interval_s)
        self.count = int(count)
        self.directory = Path(directory)
        self.options = dict(options or {})
        self.ref_to_peak = ref_to_peak
        self.dark_png = dark_png
        self.done = 0

    @Slot()
    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001
            log.exception("Time-lapse failed")
            self.message.emit(f"Time-lapse failed: {e}")
        finally:
            self.finished.emit()

    def _run(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        summary = self.directory / "summary.csv"
        self.osa.set_active_trace(self.trace)
        t0 = time.monotonic()
        for i in range(self.count):
            if self._abort:
                break
            self.params.apply(self.osa)
            self.osa.start_single_sweep()
            if not self._wait_for_sweep(self.osa):
                self.message.emit("Time-lapse aborted.")
                break                               # aborted mid-sweep: no partial measurement
            if self.ref_to_peak:
                self.osa.set_reference_to_peak()
            wavelengths, levels = self.osa.read_trace(self.trace)
            elapsed = time.monotonic() - t0
            results, overlays = analyze(wavelengths, levels, self.options)
            self._save(i, wavelengths, levels, results, overlays)
            row = {"index": i, "timestamp": datetime.now().isoformat(timespec="seconds"), "elapsed_s": round(elapsed, 3),
                   "points": len(wavelengths), **results}
            storage.append_csv_row(summary, row)
            self.done = i + 1
            self.measurementDone.emit(i, elapsed, wavelengths, levels, results)
            if i < self.count - 1 and not self._sleep(self.interval_s):
                self.message.emit("Time-lapse aborted.")
                break

    def _save(self, index: int, wavelengths, levels, results, overlays) -> None:
        base = self.directory / f"measurement_{index:03d}"
        storage.write_trace_csv(base.with_suffix(".csv"), wavelengths, levels)
        storage.write_analysis_csv(base.parent / f"{base.name}_anal.csv", results)
        render_png(base.with_suffix(".png"), [(self.trace, wavelengths, levels)], {self.trace: overlays},
                   dark=self.dark_png, title=f"Measurement {index:03d}")


def start_in_thread(worker: QObject, parent: QObject) -> QThread:
    """Move ``worker`` to a new QThread that runs ``worker.run`` and quits when the worker
    says ``finished``. The caller keeps a reference until the thread has finished."""
    thread = QThread(parent)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.start()
    return thread
