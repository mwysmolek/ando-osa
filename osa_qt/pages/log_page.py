"""Log page: what the app and the instrument driver report, with the bus traffic at DEBUG."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from ..widgets import caption, save_file


class _Relay(QObject):
    record = Signal(str)


OWN_LOGGERS = ("ando_osa", "osa_qt", "pyvisa")       # shown at any level; everything else from WARNING up


class _OwnOrWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING or record.name.startswith(OWN_LOGGERS)


class QtLogHandler(logging.Handler):
    """Hands log records to the GUI thread through a queued signal."""

    def __init__(self):
        super().__init__()
        self.relay = _Relay()
        self.addFilter(_OwnOrWarning())
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.relay.record.emit(self.format(record))
        except RuntimeError:                    # the page is gone
            pass


class LogPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.handler = QtLogHandler()
        self.handler.relay.record.connect(self.append, Qt.QueuedConnection)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        row = QHBoxLayout()
        row.addWidget(QLabel("Detail"))
        self.level = QComboBox()
        self.level.addItem("Events (INFO)", logging.INFO)
        self.level.addItem("Bus traffic (DEBUG)", logging.DEBUG)
        self.level.setToolTip("DEBUG shows every command sent to the instrument and the answers")
        self.level.currentIndexChanged.connect(self._level)
        row.addWidget(self.level)
        row.addStretch(1)
        b_copy = QPushButton("Copy")
        b_copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.view.toPlainText()))
        b_save = QPushButton("Save…")
        b_save.clicked.connect(self._save)
        b_clear = QPushButton("Clear")
        b_clear.clicked.connect(self.clear)
        for b in (b_copy, b_save, b_clear):
            row.addWidget(b)
        lay.addLayout(row)
        lay.addWidget(caption("The packaged app also writes this to the log file in the data folder."))
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        self.view.setStyleSheet('font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: 12px;')
        lay.addWidget(self.view, 1)
        self._level()

    def _level(self) -> None:
        for name in OWN_LOGGERS:
            logging.getLogger(name).setLevel(int(self.level.currentData()))
        for name in ("matplotlib", "PIL"):                 # font-manager chatter has no place in an instrument log
            logging.getLogger(name).setLevel(logging.WARNING)

    def append(self, text: str) -> None:
        self.view.appendPlainText(text)

    def clear(self) -> None:
        self.view.clear()

    def _save(self) -> None:
        save_file(self, "spectrumstudio.log", "Log (*.log *.txt)",
                  lambda p: open(p, "w", encoding="utf-8").write(self.view.toPlainText()))
