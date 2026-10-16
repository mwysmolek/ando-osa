"""Method page: how the numbers are computed and what to verify on the instrument."""
from __future__ import annotations

from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget

from ando_osa.method_text import METHOD_MD


class MethodPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setMarkdown(METHOD_MD)
        self.view.setStyleSheet("QTextBrowser { padding: 12px 18px; font-size: 13px; }")
        lay.addWidget(self.view)
