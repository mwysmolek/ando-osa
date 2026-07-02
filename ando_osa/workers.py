"""Background workers for single-sweep and time-lapse acquisition.

Both workers are meant to be moved to a QThread. They never touch Qt
widgets or pyplot; results go back to the GUI through signals, and
time-lapse PNGs are rendered with the thread-safe Agg canvas.
"""

import csv
import logging
import os
import time

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

log = logging.getLogger(__name__)

SWEEP_TIMEOUT_S = 40.0
SWEEP_POLL_S = 1.0
ABORT_POLL_S = 0.1


class _AbortableWorker(QObject):
    """Shared abort flag and sweep-completion polling."""

    def __init__(self):
        super().__init__()
        self._abort = False

    def stop(self):
        """Request abort. Safe to call from any thread."""
        self._abort = True

    def _wait_for_sweep(self, osa):
        """Poll SWEEP? until the sweep finishes.

        Returns True when the sweep completed, False when aborted.
        Raises TimeoutError if the sweep does not finish in time;
        transient query errors are logged and retried until the deadline.
        """
        deadline = time.monotonic() + SWEEP_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._abort:
                return False
            try:
                if not osa.sweep_in_progress():
                    return True
            except Exception:
                log.warning("SWEEP? poll failed", exc_info=True)
            time.sleep(SWEEP_POLL_S)
        raise TimeoutError(f"Sweep did not finish within {SWEEP_TIMEOUT_S:.0f} s.")


class SweepWorker(_AbortableWorker):
    """Runs one sweep and emits the resulting trace."""

    finished = pyqtSignal()
    dataReady = pyqtSignal(str, list, list)  # trace label, wavelengths, levels
    message = pyqtSignal(str)

    def __init__(self, osa, start_nm, stop_nm, resolution_nm, sensitivity_cmd, trace):
        super().__init__()
        self.osa = osa
        self.start_nm = start_nm
        self.stop_nm = stop_nm
        self.resolution_nm = resolution_nm
        self.sensitivity_cmd = sensitivity_cmd
        self.trace = trace

    @pyqtSlot()
    def run(self):
        try:
            self._run()
        except Exception as e:
            log.exception("Sweep failed")
            self.message.emit(f"Sweep failed: {e}")
        finally:
            self.finished.emit()

    def _run(self):
        self.osa.configure_sweep(self.start_nm, self.stop_nm,
                                 self.resolution_nm, self.sensitivity_cmd)
        self.osa.start_single_sweep()
        if not self._wait_for_sweep(self.osa):
            self.message.emit("Sweep aborted.")
            return
        wavelengths, levels = self.osa.read_trace(self.trace)
        self.dataReady.emit(self.trace, wavelengths, levels)


class TimeLapseWorker(_AbortableWorker):
    """Runs a series of sweeps, saving each as CSV + PNG."""

    finished = pyqtSignal()
    measurementDone = pyqtSignal(int, list, list)  # index, wavelengths, levels
    message = pyqtSignal(str)

    def __init__(self, osa, start_nm, stop_nm, resolution_nm, sensitivity_cmd,
                 interval_s, measurements, directory, trace):
        super().__init__()
        self.osa = osa
        self.start_nm = start_nm
        self.stop_nm = stop_nm
        self.resolution_nm = resolution_nm
        self.sensitivity_cmd = sensitivity_cmd
        self.interval_s = interval_s
        self.measurements = measurements
        self.directory = directory
        self.trace = trace

    @pyqtSlot()
    def run(self):
        try:
            self._run()
        except Exception as e:
            log.exception("Time-lapse failed")
            self.message.emit(f"Time-lapse failed: {e}")
        finally:
            self.finished.emit()

    def _run(self):
        for i in range(self.measurements):
            if self._abort:
                break
            self.osa.configure_sweep(self.start_nm, self.stop_nm,
                                     self.resolution_nm, self.sensitivity_cmd)
            self.osa.start_single_sweep()
            if not self._wait_for_sweep(self.osa):
                break  # aborted mid-sweep: do not record a partial measurement
            self.osa.set_reference_to_peak()
            wavelengths, levels = self.osa.read_trace(self.trace)
            self._save_measurement(i, wavelengths, levels)
            self.measurementDone.emit(i, wavelengths, levels)
            if i < self.measurements - 1 and not self._sleep_interval():
                break

    def _sleep_interval(self):
        """Wait between measurements. Returns False if aborted."""
        deadline = time.monotonic() + self.interval_s
        while time.monotonic() < deadline:
            if self._abort:
                return False
            time.sleep(ABORT_POLL_S)
        return True

    def _save_measurement(self, index, wavelengths, levels):
        base = os.path.join(self.directory, f"measurement_{index:03d}")
        with open(base + ".csv", "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Wavelength (nm)", "Level (dBm)"])
            writer.writerows(zip(wavelengths, levels))
        # Rendered with the Agg canvas: pyplot is not thread-safe and
        # must not be used outside the GUI thread.
        fig = Figure(figsize=(8, 5), dpi=100)
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        ax.plot(wavelengths, levels)
        ax.set_xlabel("Wavelength (nm)")
        ax.set_ylabel("Level (dBm)")
        ax.set_title(f"Measurement {index:03d}")
        fig.savefig(base + ".png")
