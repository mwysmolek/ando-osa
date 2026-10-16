"""Small dialogs: the power-content ranges, the raw command console, the preferences."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout)

from ando_osa import updates
from ando_osa.analysis import N_POWER_RANGES
from ando_osa.instrument import WAVELENGTH_MAX_NM, WAVELENGTH_MIN_NM
from ando_osa.storage import ENV_HOME

from .widgets import caption, section

log = logging.getLogger(__name__)


class PowerRangesDialog(QDialog):
    """Up to five wavelength ranges whose share of the total power is reported."""

    def __init__(self, ranges: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Power content ranges")
        lay = QVBoxLayout(self)
        lay.addWidget(section("Power content"))
        lay.addWidget(caption("Share of the total linear power inside each range, in percent. Ranges are shaded on "
                              "the plot and reported as 'Power Content 1…5'."))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self.rows: list[tuple[QCheckBox, QDoubleSpinBox, QDoubleSpinBox]] = []
        for i in range(N_POWER_RANGES):
            on = QCheckBox(f"Range {i + 1}")
            a, b = QDoubleSpinBox(), QDoubleSpinBox()
            for sp in (a, b):
                sp.setRange(WAVELENGTH_MIN_NM, WAVELENGTH_MAX_NM)
                sp.setDecimals(2)
                sp.setSuffix(" nm")
                sp.setSingleStep(1.0)
            if i < len(ranges):
                on.setChecked(True)
                a.setValue(float(ranges[i]["start"]))
                b.setValue(float(ranges[i]["stop"]))
            else:
                a.setValue(1000.0 + 20 * i)
                b.setValue(1010.0 + 20 * i)
            grid.addWidget(on, i, 0)
            grid.addWidget(QLabel("from"), i, 1)
            grid.addWidget(a, i, 2)
            grid.addWidget(QLabel("to"), i, 3)
            grid.addWidget(b, i, 4)
            self.rows.append((on, a, b))
        lay.addLayout(grid)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self._ranges: list[dict] = list(ranges)

    def accept(self) -> None:
        out = []
        for i, (on, a, b) in enumerate(self.rows, 1):
            if not on.isChecked():
                continue
            if b.value() <= a.value():
                QMessageBox.warning(self, "Power content", f"Range {i}: 'to' must be greater than 'from'.")
                return
            out.append({"start": a.value(), "stop": b.value()})
        self._ranges = out
        super().accept()

    def ranges(self) -> list[dict]:
        return list(self._ranges)


class CommandConsole(QDialog):
    """Send any command to the instrument and read the answer (non-modal)."""

    def __init__(self, osa_getter: Callable[[], Optional[object]], parent=None):
        super().__init__(parent)
        self.osa_getter = osa_getter
        self.setWindowTitle("Send command")
        self.setWindowFlag(Qt.Tool, True)
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(caption("Raw GPIB commands as in the Ando programming manual. Send writes the command; Query "
                              "writes it and reads one answer (use it for commands ending in '?')."))
        row = QHBoxLayout()
        self.cmd = QLineEdit()
        self.cmd.setPlaceholderText("e.g. *IDN?  ·  STAWL1000.00  ·  SWEEP?")
        self.cmd.returnPressed.connect(self.query)
        row.addWidget(self.cmd, 1)
        b_send = QPushButton("Send")
        b_send.clicked.connect(self.send)
        row.addWidget(b_send)
        b_query = QPushButton("Query")
        b_query.setProperty("primary", True)
        b_query.clicked.connect(self.query)
        row.addWidget(b_query)
        lay.addLayout(row)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setMaximumBlockCount(2000)
        lay.addWidget(self.out, 1)
        b_clear = QPushButton("Clear")
        b_clear.clicked.connect(self.out.clear)
        lay.addWidget(b_clear, 0, Qt.AlignRight)

    def _osa(self):
        osa = self.osa_getter()
        if osa is None:
            self.out.appendPlainText("! not connected")
        return osa

    def send(self) -> None:
        osa, cmd = self._osa(), self.cmd.text().strip()
        if osa is None or not cmd:
            return
        try:
            osa.write(cmd)
            self.out.appendPlainText(f">> {cmd}")
        except Exception as ex:  # noqa: BLE001
            self.out.appendPlainText(f">> {cmd}\n! {type(ex).__name__}: {ex}")

    def query(self) -> None:
        osa, cmd = self._osa(), self.cmd.text().strip()
        if osa is None or not cmd:
            return
        try:
            answer = osa.query(cmd)
            text = str(answer).strip()
            if len(text) > 400:
                text = text[:400] + f"… ({len(text)} chars)"
            self.out.appendPlainText(f">> {cmd}\n<< {text}")
        except Exception as ex:  # noqa: BLE001
            self.out.appendPlainText(f">> {cmd}\n! {type(ex).__name__}: {ex}")


PREF_DEFAULTS = {"update_check": None, "ref_to_peak": True, "sweep_timeout_s": 40.0, "dark_png": False,
                 "auto_connect": True}


def pref(store, key: str):
    """A preference with its default (``update_check`` defaults by packaging)."""
    v = store.get_pref(key, PREF_DEFAULTS.get(key))
    if key == "update_check" and v is None:
        return updates.default_enabled()
    return v


class PreferencesDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Preferences")
        lay = QVBoxLayout(self)
        lay.addWidget(section("Instrument"))
        self.auto_connect = QCheckBox("Look for the instrument when the app starts")
        self.auto_connect.setChecked(bool(pref(store, "auto_connect")))
        lay.addWidget(self.auto_connect)
        self.ref_peak = QCheckBox("Set the reference level to the peak after each sweep (REF=P)")
        self.ref_peak.setChecked(bool(pref(store, "ref_to_peak")))
        lay.addWidget(self.ref_peak)
        row = QHBoxLayout()
        row.addWidget(QLabel("Sweep timeout"))
        self.timeout = QSpinBox()
        self.timeout.setRange(5, 3600)
        self.timeout.setSuffix(" s")
        self.timeout.setValue(int(pref(store, "sweep_timeout_s")))
        self.timeout.setToolTip("How long to wait for SWEEP? to report 0 – raise it for slow high-sensitivity sweeps")
        row.addWidget(self.timeout)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(section("Files"))
        self.dark_png = QCheckBox("Save plots with the dark (screen) background instead of white paper")
        self.dark_png.setChecked(bool(pref(store, "dark_png")))
        lay.addWidget(self.dark_png)
        lay.addWidget(section("Updates"))
        self.upd = QCheckBox("Check for new versions at start (reads the public release list on GitHub; nothing about "
                             "you or your measurements is sent)")
        self.upd.setChecked(bool(pref(store, "update_check")))
        lay.addWidget(self.upd)
        lay.addWidget(caption(f"Data folder: {store.home}\n(set the {ENV_HOME} environment variable to use another one)"))
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def values(self) -> dict:
        return {"auto_connect": self.auto_connect.isChecked(), "ref_to_peak": self.ref_peak.isChecked(),
                "sweep_timeout_s": float(self.timeout.value()), "dark_png": self.dark_png.isChecked(),
                "update_check": self.upd.isChecked()}

    def accept(self) -> None:
        self.store.update_prefs(self.values())
        super().accept()
