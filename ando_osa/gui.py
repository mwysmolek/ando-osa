"""PyQt5 GUI for controlling an Ando AQ63xx optical spectrum analyzer."""

import csv
import logging
import os
from datetime import datetime

import numpy as np
import pyvisa
from PyQt5.QtCore import Qt, QThread
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
    QComboBox, QLabel, QLineEdit, QFileDialog, QCheckBox, QMessageBox,
    QDialog, QFormLayout, QDialogButtonBox, QPushButton, QGroupBox, QStatusBar
)
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT as NavigationToolbar
)
from matplotlib.figure import Figure

from . import analysis
from .instrument import (
    AndoOSA, RESOLUTIONS_NM, SENSITIVITY_MODES, TRACES, validate_sweep_range,
)
from .workers import SweepWorker, TimeLapseWorker

log = logging.getLogger(__name__)


###############################################################################
#                               AnalysisDialog                                #
###############################################################################
class AnalysisDialog(QDialog):
    """Select which analyses to run and their parameters."""

    N_POWER_RANGES = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Analyses")
        self._selected = None

        layout = QFormLayout()

        self.fwhm_checkbox = QCheckBox("FWHM")
        self.peak_search_checkbox = QCheckBox("Peak Search")
        self.snr_checkbox = QCheckBox("SNR")
        self.srs_checkbox = QCheckBox("SRS (Anti-Stokes)")

        layout.addRow(self.fwhm_checkbox)
        layout.addRow(self.peak_search_checkbox)
        layout.addRow(self.snr_checkbox)
        layout.addRow(self.srs_checkbox)

        self.power_content_ranges = []
        for i in range(self.N_POWER_RANGES):
            checkbox = QCheckBox(f"Power Content Range {i + 1}")
            start_edit = QLineEdit()
            stop_edit = QLineEdit()
            row = QHBoxLayout()
            row.addWidget(QLabel("Start (nm):"))
            row.addWidget(start_edit)
            row.addWidget(QLabel("Stop (nm):"))
            row.addWidget(stop_edit)
            container = QWidget()
            container.setLayout(row)
            layout.addRow(checkbox, container)
            self.power_content_ranges.append((checkbox, start_edit, stop_edit))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def accept(self):
        try:
            self._selected = self._collect()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Input", str(e))
            return
        super().accept()

    def selected_analyses(self):
        return self._selected

    def _collect(self):
        ranges = []
        for i, (checkbox, start_edit, stop_edit) in enumerate(self.power_content_ranges, 1):
            if not checkbox.isChecked():
                continue
            try:
                start = float(start_edit.text())
                stop = float(stop_edit.text())
            except ValueError:
                raise ValueError(f"Power content range {i}: start and stop must be numbers.")
            if stop <= start:
                raise ValueError(f"Power content range {i}: stop must be greater than start.")
            ranges.append({"start": start, "stop": stop})
        return {
            "FWHM": self.fwhm_checkbox.isChecked(),
            "Peak Search": self.peak_search_checkbox.isChecked(),
            "SNR": self.snr_checkbox.isChecked(),
            "SRS": self.srs_checkbox.isChecked(),
            "Power Content": ranges,
        }


###############################################################################
#                              TimeLapseDialog                                #
###############################################################################
class TimeLapseDialog(QDialog):
    """Configure interval, measurement count and save directory."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Time-Lapse Settings")
        self._settings = None

        layout = QFormLayout()
        self.interval_input = QLineEdit("5")
        self.measurements_input = QLineEdit("10")
        self.directory_input = QLineEdit()
        browse = QPushButton("Browse")
        browse.clicked.connect(self.browse_directory)

        layout.addRow(QLabel("Interval (seconds):"), self.interval_input)
        layout.addRow(QLabel("Number of Measurements:"), self.measurements_input)
        layout.addRow(QLabel("Save Directory:"), self.directory_input)
        layout.addRow(browse)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def browse_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            self.directory_input.setText(directory)

    def accept(self):
        try:
            self._settings = self._collect()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Input", str(e))
            return
        super().accept()

    def settings(self):
        return self._settings

    def _collect(self):
        try:
            interval = float(self.interval_input.text())
        except ValueError:
            raise ValueError("Interval must be a number of seconds.")
        if interval < 0:
            raise ValueError("Interval cannot be negative.")
        try:
            measurements = int(self.measurements_input.text())
        except ValueError:
            raise ValueError("Number of measurements must be an integer.")
        if measurements < 1:
            raise ValueError("Number of measurements must be at least 1.")
        directory = self.directory_input.text().strip()
        if not directory or not os.path.isdir(directory):
            raise ValueError("Please choose an existing save directory.")
        return {"interval": interval, "measurements": measurements, "directory": directory}


###############################################################################
#                             SpectrometerGUI                                 #
###############################################################################
class SpectrometerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ando OSA Control")
        self.setGeometry(100, 100, 1600, 900)

        try:
            self.rm = pyvisa.ResourceManager()
        except Exception:
            # No VISA backend installed - keep the GUI usable for CSV
            # import/analysis and explain what is missing on connect.
            log.exception("Could not initialize VISA")
            self.rm = None
        self.osa = None

        self.trace_data = {}
        self.trace_display = {"A": True, "B": False, "C": False}
        self.analysis_results = {}
        self.analysis_overlays = {}
        self.selected_analyses = {}
        self.active_trace = "A"

        self.quick_save_subdir = None
        self.quick_save_counter = 0

        self.sweep_thread = None
        self.sweep_worker = None
        self.tl_thread = None
        self.tl_worker = None
        self._tl_runs = []

        self.init_ui()
        self.auto_connect_device()

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)

        main_layout = QHBoxLayout()
        control_layout = QVBoxLayout()

        # --- Sweep group ---
        sweep_group = QGroupBox("Sweep Settings")
        sweep_layout = QVBoxLayout()
        self.start_wl_input = QLineEdit("1000")
        self.stop_wl_input = QLineEdit("1500")
        sweep_layout.addWidget(QLabel("Start WL (nm):"))
        sweep_layout.addWidget(self.start_wl_input)
        sweep_layout.addWidget(QLabel("Stop WL (nm):"))
        sweep_layout.addWidget(self.stop_wl_input)
        self.res_combo = QComboBox()
        self.res_combo.addItems(RESOLUTIONS_NM)
        sweep_layout.addWidget(QLabel("Resolution (nm):"))
        sweep_layout.addWidget(self.res_combo)
        self.sens_combo = QComboBox()
        for label, _cmd in SENSITIVITY_MODES:
            self.sens_combo.addItem(label)
        sweep_layout.addWidget(QLabel("Sensitivity:"))
        sweep_layout.addWidget(self.sens_combo)
        self.sweep_button = QPushButton("Start Sweep")
        self.sweep_button.clicked.connect(self.start_sweep)
        self.stop_button = QPushButton("Stop Sweep")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_sweep)
        sweep_layout.addWidget(self.sweep_button)
        sweep_layout.addWidget(self.stop_button)
        sweep_group.setLayout(sweep_layout)
        control_layout.addWidget(sweep_group)

        # --- Trace group ---
        trace_group = QGroupBox("Trace Management")
        trace_layout = QVBoxLayout()
        self.traceA_check = QCheckBox("Display Trace A")
        self.traceA_check.setChecked(True)
        self.traceA_check.stateChanged.connect(
            lambda state: self.set_trace_display("A", state == Qt.Checked))
        trace_layout.addWidget(self.traceA_check)
        self.traceB_check = QCheckBox("Display Trace B")
        self.traceB_check.stateChanged.connect(
            lambda state: self.set_trace_display("B", state == Qt.Checked))
        trace_layout.addWidget(self.traceB_check)
        self.traceC_check = QCheckBox("Display Trace C")
        self.traceC_check.stateChanged.connect(
            lambda state: self.set_trace_display("C", state == Qt.Checked))
        trace_layout.addWidget(self.traceC_check)
        self.trace_modeA = QComboBox()
        self.trace_modeA.addItems(["WRTA", "FIXA", "MAXA", "RAVA"])
        self.trace_modeA.currentTextChanged.connect(self.set_trace_mode)
        trace_layout.addWidget(QLabel("Trace A Mode:"))
        trace_layout.addWidget(self.trace_modeA)
        self.trace_modeB = QComboBox()
        self.trace_modeB.addItems(["WRTB", "FIXB", "MINB", "RAVB"])
        self.trace_modeB.currentTextChanged.connect(self.set_trace_mode)
        trace_layout.addWidget(QLabel("Trace B Mode:"))
        trace_layout.addWidget(self.trace_modeB)
        self.trace_modeC = QComboBox()
        self.trace_modeC.addItems(["WRTC", "FIXC"])
        self.trace_modeC.currentTextChanged.connect(self.set_trace_mode)
        trace_layout.addWidget(QLabel("Trace C Mode:"))
        trace_layout.addWidget(self.trace_modeC)
        self.active_trace_combo = QComboBox()
        self.active_trace_combo.addItems(["Trace A", "Trace B", "Trace C"])
        self.active_trace_combo.currentIndexChanged.connect(self.on_active_trace_changed)
        trace_layout.addWidget(QLabel("Active Trace:"))
        trace_layout.addWidget(self.active_trace_combo)
        trace_group.setLayout(trace_layout)
        control_layout.addWidget(trace_group)

        # --- CW / Pulsed ---
        mode_group = QGroupBox("CW / Pulsed")
        mode_layout = QVBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["CW", "Pulsed"])
        self.mode_combo.currentTextChanged.connect(self.on_measurement_mode_changed)
        mode_layout.addWidget(QLabel("Measurement Mode:"))
        mode_layout.addWidget(self.mode_combo)
        self.peak_hold_label = QLabel("Peak Hold (ms):")
        self.peak_hold_input = QLineEdit("100")
        self.peak_hold_label.hide()
        self.peak_hold_input.hide()
        mode_layout.addWidget(self.peak_hold_label)
        mode_layout.addWidget(self.peak_hold_input)
        mode_group.setLayout(mode_layout)
        control_layout.addWidget(mode_group)

        # --- Analysis & Data ---
        analysis_group = QGroupBox("Analysis & Data")
        analysis_layout = QVBoxLayout()
        self.analysis_button = QPushButton("Analysis Dialog")
        self.analysis_button.clicked.connect(self.open_analysis_dialog)
        self.hold_analysis_check = QCheckBox("Hold Analysis (Auto after each sweep)")
        self.overlay_check = QCheckBox("Show Overlays")
        self.overlay_check.setChecked(True)
        self.overlay_check.stateChanged.connect(lambda _state: self.update_plot())
        import_button = QPushButton("Import Data (CSV)")
        import_button.clicked.connect(self.import_data_csv)
        self.save_button = QPushButton("Save Data")
        self.save_button.clicked.connect(self.save_data)
        self.quick_save_button = QPushButton("Quick Save")
        self.quick_save_button.clicked.connect(self.quick_save_data)
        self.time_lapse_button = QPushButton("Time-Lapse")
        self.time_lapse_button.clicked.connect(self.start_time_lapse)
        self.stop_time_lapse_button = QPushButton("Stop Time-Lapse")
        self.stop_time_lapse_button.setEnabled(False)
        self.stop_time_lapse_button.clicked.connect(self.stop_time_lapse)
        analysis_layout.addWidget(self.analysis_button)
        analysis_layout.addWidget(self.hold_analysis_check)
        analysis_layout.addWidget(self.overlay_check)
        analysis_layout.addWidget(import_button)
        analysis_layout.addWidget(self.save_button)
        analysis_layout.addWidget(self.quick_save_button)
        analysis_layout.addWidget(self.time_lapse_button)
        analysis_layout.addWidget(self.stop_time_lapse_button)
        analysis_group.setLayout(analysis_layout)
        control_layout.addWidget(analysis_group)

        # --- Device connection ---
        device_group = QGroupBox("Device Connection")
        device_layout = QHBoxLayout()
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_device)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self.disconnect_device)
        device_layout.addWidget(self.connect_button)
        device_layout.addWidget(self.disconnect_button)
        device_group.setLayout(device_layout)
        control_layout.addWidget(device_group)

        control_layout.addStretch()
        left_widget = QWidget()
        left_widget.setLayout(control_layout)

        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        toolbar = NavigationToolbar(self.canvas, self)
        plot_layout = QVBoxLayout()
        plot_layout.addWidget(toolbar)
        plot_layout.addWidget(self.canvas)
        right_widget = QWidget()
        right_widget.setLayout(plot_layout)

        main_layout.addWidget(left_widget, 1)
        main_layout.addWidget(right_widget, 3)
        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

    def _set_busy(self, mode):
        """Enable/disable controls while a worker runs. mode: None, 'sweep', 'timelapse'."""
        busy = mode is not None
        for button in (self.sweep_button, self.time_lapse_button,
                       self.connect_button, self.disconnect_button):
            button.setEnabled(not busy)
        self.stop_button.setEnabled(mode == "sweep")
        self.stop_time_lapse_button.setEnabled(mode == "timelapse")

    # ------------------------------------------------------------ connection
    def auto_connect_device(self):
        self._connect(silent=True)

    def connect_device(self):
        self._connect(silent=False)

    def _connect(self, silent):
        if self.rm is None:
            message = ("No VISA implementation found. Install NI-VISA "
                       "(or pyvisa-py) and restart the application.")
            self.statusbar.showMessage(message)
            if not silent:
                QMessageBox.warning(self, "No VISA Backend", message)
            return
        if self.osa is not None:
            self.statusbar.showMessage(f"Already connected to {self.osa.idn}")
            return
        osa = AndoOSA.find(self.rm)
        if osa is None:
            self.statusbar.showMessage("No Ando OSA found.")
            if not silent:
                QMessageBox.warning(self, "Connect Failed", "No Ando OSA found.")
            return
        self.osa = osa
        try:
            osa.initialize()
        except Exception as e:
            log.exception("Device initialization failed")
            self.statusbar.showMessage(f"Connected, but initialization failed: {e}")
            return
        self.statusbar.showMessage(f"Connected to {osa.idn}")

    def disconnect_device(self):
        if self.osa is None:
            self.statusbar.showMessage("No device to disconnect.")
            return
        try:
            self.osa.close()
        except Exception:
            log.exception("Error closing instrument")
        self.osa = None
        self.statusbar.showMessage("Disconnected.")

    # ----------------------------------------------------------------- sweep
    def _sweep_params(self):
        """Validated (start, stop, resolution, sensitivity_cmd) or None."""
        try:
            start = float(self.start_wl_input.text())
            stop = float(self.stop_wl_input.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid Sweep Settings",
                                "Start and stop wavelengths must be numbers.")
            return None
        try:
            validate_sweep_range(start, stop)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Sweep Settings", str(e))
            return None
        sensitivity_cmd = SENSITIVITY_MODES[self.sens_combo.currentIndex()][1]
        return start, stop, self.res_combo.currentText(), sensitivity_cmd

    def start_sweep(self):
        if self.osa is None:
            self.statusbar.showMessage("No instrument connected.")
            return
        params = self._sweep_params()
        if params is None:
            return
        start, stop, resolution, sensitivity_cmd = params

        self.sweep_worker = SweepWorker(self.osa, start, stop, resolution,
                                        sensitivity_cmd, self.active_trace)
        self.sweep_worker.message.connect(self.statusbar.showMessage)
        self.sweep_worker.dataReady.connect(self.on_sweep_data)
        self.sweep_worker.finished.connect(self.on_sweep_finished)
        self.sweep_thread = QThread(self)
        self.sweep_worker.moveToThread(self.sweep_thread)
        self.sweep_thread.started.connect(self.sweep_worker.run)
        self.sweep_thread.start()

        self._set_busy("sweep")
        self.statusbar.showMessage("Sweep started…")

    def stop_sweep(self):
        if self.sweep_worker:
            self.sweep_worker.stop()
            self.statusbar.showMessage("Stopping sweep…")

    def on_sweep_data(self, trace, wavelengths, levels):
        self.trace_data[trace] = (wavelengths, levels)
        if self.hold_analysis_check.isChecked() and self.selected_analyses:
            self.perform_analysis_on_trace(trace)
        self.update_plot()

    def on_sweep_finished(self):
        if self.osa:
            try:
                self.osa.set_reference_to_peak()
            except Exception:
                log.exception("Setting reference to peak failed")
        self._cleanup_thread("sweep")
        self._set_busy(None)
        self.statusbar.showMessage("Sweep finished.")

    def _cleanup_thread(self, which):
        if which == "sweep":
            thread, self.sweep_thread, self.sweep_worker = self.sweep_thread, None, None
        else:
            thread, self.tl_thread, self.tl_worker = self.tl_thread, None, None
        if thread:
            thread.quit()
            thread.wait(2000)

    # ------------------------------------------------- trace / mode handling
    def on_active_trace_changed(self, index):
        self.active_trace = TRACES[index]
        if self.osa:
            try:
                self.osa.set_active_trace(self.active_trace)
            except Exception as e:
                log.exception("Setting active trace failed")
                self.statusbar.showMessage(f"Failed to set active trace: {e}")

    def on_measurement_mode_changed(self, mode):
        cw = mode == "CW"
        self.peak_hold_label.setVisible(not cw)
        self.peak_hold_input.setVisible(not cw)
        if self.osa is None:
            return
        try:
            if cw:
                self.osa.set_cw_mode()
            else:
                try:
                    peak_hold_ms = int(self.peak_hold_input.text())
                except ValueError:
                    self.statusbar.showMessage("Peak hold must be an integer (ms).")
                    return
                self.osa.set_pulsed_mode(peak_hold_ms)
        except ValueError as e:
            self.statusbar.showMessage(str(e))
        except Exception as e:
            log.exception("Measurement mode change failed")
            self.statusbar.showMessage(f"Mode change failed: {e}")

    def set_trace_display(self, trace, visible):
        self.trace_display[trace] = visible
        if self.osa:
            try:
                self.osa.set_trace_display(trace, visible)
            except Exception as e:
                log.exception("Setting trace display failed")
                self.statusbar.showMessage(f"Failed to set trace display: {e}")
        self.update_plot()

    def set_trace_mode(self, mode_cmd):
        if self.osa:
            try:
                self.osa.set_trace_mode(mode_cmd)
            except Exception as e:
                log.exception("Setting trace mode failed")
                self.statusbar.showMessage(f"Failed to set trace mode: {e}")

    # ------------------------------------------------------------- analysis
    def open_analysis_dialog(self):
        dialog = AnalysisDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return
        self.selected_analyses = dialog.selected_analyses()
        for trace in self.trace_data:
            self.perform_analysis_on_trace(trace)
        self.update_plot()

    def perform_analysis_on_trace(self, trace):
        wavelengths, levels = self.trace_data[trace]
        results, overlays = analysis.analyze(wavelengths, levels, self.selected_analyses)
        self.analysis_results[trace] = results
        self.analysis_overlays[trace] = overlays

    # ------------------------------------------------------------- plotting
    def update_plot(self):
        self.ax.clear()
        for trace, (wavelengths, levels) in self.trace_data.items():
            if not self.trace_display.get(trace):
                continue
            self.ax.plot(wavelengths, levels, label=f"Trace {trace}")
            if self.overlay_check.isChecked():
                self._draw_overlays(trace)
        self.ax.set_xlabel("Wavelength (nm)")
        self.ax.set_ylabel("Level (dBm)")
        if self.ax.get_legend_handles_labels()[0]:
            self.ax.legend()
        self.canvas.draw()

    def _draw_overlays(self, trace):
        overlays = self.analysis_overlays.get(trace) or {}
        if "peak" in overlays:
            peak_wl, peak_lvl = overlays["peak"]
            self.ax.plot([peak_wl], [peak_lvl], "o", color="red")
            self.ax.annotate(f"{peak_wl:.2f} nm\n{peak_lvl:.2f} dBm",
                             (peak_wl, peak_lvl), textcoords="offset points",
                             xytext=(8, 8), fontsize=8)
        if "fwhm" in overlays:
            lo, hi, level = overlays["fwhm"]
            self.ax.hlines(level, lo, hi, colors="orange", linestyles="--")

    # --------------------------------------------------- import / save data
    def import_data_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Data", "", "CSV Files (*.csv)")
        if not path:
            return
        wavelengths, levels = [], []
        with open(path, newline="") as f:
            for row in csv.reader(f):
                try:
                    wavelengths.append(float(row[0]))
                    levels.append(float(row[1]))
                except (ValueError, IndexError):
                    continue  # header or malformed line
        if not wavelengths:
            QMessageBox.warning(self, "Import Failed", "No numeric data found in the file.")
            return
        label = f"Import{sum(1 for k in self.trace_data if k.startswith('Import')) + 1}"
        self.trace_data[label] = (wavelengths, levels)
        self.trace_display[label] = True
        if self.hold_analysis_check.isChecked() and self.selected_analyses:
            self.perform_analysis_on_trace(label)
        self.statusbar.showMessage(f"Imported {os.path.basename(path)} as {label}")
        self.update_plot()

    def save_data(self):
        if self.active_trace not in self.trace_data:
            QMessageBox.warning(self, "No Data", "The active trace has no data.")
            return
        wavelengths, levels = self.trace_data[self.active_trace]
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Save Data", "", "CSV (*.csv);;PNG (*.png)")
        if not path:
            return
        root, ext = os.path.splitext(path)
        if not ext:
            ext = ".csv" if "CSV" in selected_filter else ".png"
        if ext.lower() == ".csv":
            self._write_trace_csv(root + ext, wavelengths, levels)
            self._write_analysis_csv(root + "_anal.csv", self.active_trace)
            self.statusbar.showMessage(f"Saved {root + ext}")
        else:
            self._save_plot_pngs(root, ext)
            self.statusbar.showMessage(f"Saved {root + ext}")

    def quick_save_data(self):
        data = self.trace_data.get(self.active_trace)
        if not data or not data[0]:
            QMessageBox.warning(self, "No Data", "Nothing to save.")
            return
        if not self.quick_save_subdir:
            directory = QFileDialog.getExistingDirectory(self, "Quick Save Directory")
            if not directory:
                return
            self.quick_save_subdir = os.path.join(
                directory, datetime.now().strftime("%Y%m%d_%H%M%S"))
            os.makedirs(self.quick_save_subdir, exist_ok=True)
            self.quick_save_counter = 0
        base = os.path.join(self.quick_save_subdir, f"X{self.quick_save_counter:04d}")
        self.quick_save_counter += 1
        wavelengths, levels = data
        self._write_trace_csv(base + ".csv", wavelengths, levels)
        self._write_analysis_csv(base + "_anal.csv", self.active_trace)
        self._save_plot_pngs(base, ".png")
        self.statusbar.showMessage(f"Quick-saved {os.path.basename(base)}")

    def _write_trace_csv(self, path, wavelengths, levels):
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Wavelength (nm)", "Level (dBm)"])
            writer.writerows(zip(wavelengths, levels))

    def _write_analysis_csv(self, path, trace):
        results = self.analysis_results.get(trace)
        if not results:
            return
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Metric", "Value"])
            writer.writerows(results.items())

    def _save_plot_pngs(self, root, ext):
        """Save the plot without overlays, plus an overlay variant if enabled."""
        original = self.overlay_check.isChecked()
        self.overlay_check.setChecked(False)
        self.figure.savefig(root + ext)
        if original and self.analysis_overlays.get(self.active_trace):
            self.overlay_check.setChecked(True)
            self.figure.savefig(root + "_overlay" + ext)
        self.overlay_check.setChecked(original)

    # ------------------------------------------------------------ time-lapse
    def start_time_lapse(self):
        if self.osa is None:
            QMessageBox.warning(self, "Not Connected", "Connect to the instrument first.")
            return
        params = self._sweep_params()
        if params is None:
            return
        dialog = TimeLapseDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return
        settings = dialog.settings()
        run_dir = os.path.join(settings["directory"],
                               datetime.now().strftime("timelapse_%Y%m%d_%H%M%S"))
        try:
            os.makedirs(run_dir, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "Save Directory", f"Cannot create {run_dir}: {e}")
            return

        start, stop, resolution, sensitivity_cmd = params
        self._tl_runs = []
        self.tl_worker = TimeLapseWorker(
            self.osa, start, stop, resolution, sensitivity_cmd,
            settings["interval"], settings["measurements"], run_dir, self.active_trace)
        self.tl_worker.message.connect(self.statusbar.showMessage)
        self.tl_worker.measurementDone.connect(self.on_time_lapse_measurement)
        self.tl_worker.finished.connect(self.on_time_lapse_finished)
        self.tl_thread = QThread(self)
        self.tl_worker.moveToThread(self.tl_thread)
        self.tl_thread.started.connect(self.tl_worker.run)
        self.tl_thread.start()

        self._set_busy("timelapse")
        self.statusbar.showMessage(f"Time-lapse started – saving to {run_dir}")

    def stop_time_lapse(self):
        if self.tl_worker:
            self.tl_worker.stop()
            self.statusbar.showMessage("Stopping time-lapse…")

    def on_time_lapse_measurement(self, index, wavelengths, levels):
        self._tl_runs.append((wavelengths, levels))
        self.ax.clear()
        self.ax.plot(wavelengths, levels, label=f"Current (Trace {self.active_trace})")
        # Min/max/median statistics only make sense while every
        # measurement has the same number of points.
        first_levels = self._tl_runs[0][1]
        if len(self._tl_runs) > 1 and all(len(lv) == len(first_levels)
                                          for _wl, lv in self._tl_runs):
            arr = np.array([lv for _wl, lv in self._tl_runs])
            base_wl = self._tl_runs[0][0]
            self.ax.plot(base_wl, arr.min(axis=0), "--", label="Min")
            self.ax.plot(base_wl, arr.max(axis=0), "--", label="Max")
            self.ax.plot(base_wl, np.median(arr, axis=0), ":", label="Median")
        self.ax.set_xlabel("Wavelength (nm)")
        self.ax.set_ylabel("Level (dBm)")
        self.ax.legend()
        self.canvas.draw()
        self.statusbar.showMessage(f"Time-lapse: measurement {index + 1} recorded")

    def on_time_lapse_finished(self):
        self._cleanup_thread("timelapse")
        self._set_busy(None)
        self.statusbar.showMessage("Time-lapse finished.")

    # ------------------------------------------------------------------ exit
    def closeEvent(self, event):
        for worker, thread in ((self.sweep_worker, self.sweep_thread),
                               (self.tl_worker, self.tl_thread)):
            if worker:
                worker.stop()
            if thread:
                thread.quit()
                if not thread.wait(5000):
                    log.warning("Worker thread did not stop within 5 s")
        if self.osa:
            try:
                self.osa.close()
            except Exception:
                log.exception("Error closing instrument on exit")
        super().closeEvent(event)
