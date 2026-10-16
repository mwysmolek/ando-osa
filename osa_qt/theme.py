"""Look of the desktop app: the kayEi navy palette as a Qt style sheet (shared with
RiskStudio and TwinStudio)."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from ando_osa import palette as P

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
ASSETS = ROOT / "assets"

BG, BG2, PANEL, LINE = P.BG, P.BG2, P.PANEL, P.LINE
INK, MUTED, ACCENT, ACCENT_INK = P.INK, P.MUTED, P.ACCENT, P.ACCENT_INK
GOOD, WARN, BAD = P.GOOD, P.WARN, P.BAD
SERIES = P.SERIES
rgba = P.rgba
CHECK = (ASSETS / "check.png").as_posix()

_CHECK_IMG = f'image: url("{CHECK}");' if (ASSETS / "check.png").exists() else ""
_HOVER = rgba(ACCENT, .14)
_SEL = rgba(ACCENT, .25)
_SOFT = rgba(ACCENT, .18)

QSS = f"""
* {{ font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif; }}
QMainWindow, QDialog, QWidget {{ background: {BG}; color: {INK}; }}
QToolTip {{ background: {PANEL}; color: {INK}; border: 1px solid {LINE}; padding: 4px 6px; }}
QMenuBar {{ background: {BG2}; border-bottom: 1px solid {LINE}; }}
QMenuBar::item:selected {{ background: {_SOFT}; border-radius: 4px; }}
QMenu {{ background: {PANEL}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 5px 24px 5px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {_SOFT}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}
QToolBar {{ background: {BG2}; border: 0; border-bottom: 1px solid {LINE}; spacing: 4px; padding: 3px; }}
QToolBar QToolButton {{ padding: 4px 8px; border-radius: 6px; }}
QToolButton:hover, QToolBar QToolButton:hover {{ background: {_HOVER}; }}
QToolButton:checked {{ background: {_SEL}; border: 1px solid {ACCENT}; }}
QStatusBar {{ background: {BG2}; border-top: 1px solid {LINE}; color: {MUTED}; }}
QDockWidget {{ titlebar-close-icon: none; titlebar-normal-icon: none; }}
QDockWidget::title {{ background: {BG2}; padding: 6px 10px; border-bottom: 1px solid {LINE};
                      font-weight: 600; letter-spacing: .06em; }}
QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: 6px; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 7px 14px; border-bottom: 2px solid transparent; color: {MUTED}; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {INK}; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: 8px; margin-top: 12px; padding: 10px 8px 6px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit, QTextBrowser {{
    background: {BG2}; border: 1px solid {LINE}; border-radius: 6px; padding: 4px 6px;
    selection-background-color: {ACCENT}; selection-color: {ACCENT_INK}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {MUTED}; }}
QComboBox::drop-down {{ border: 0; width: 22px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {LINE}; selection-background-color: {_SEL}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 14px; border: 0; }}
QPushButton {{ background: {BG2}; border: 1px solid {LINE}; border-radius: 6px; padding: 5px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; background: {rgba(ACCENT, .10)}; }}
QPushButton:pressed {{ background: {_SEL}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {LINE}; }}
QPushButton:checked {{ background: {_SEL}; border-color: {ACCENT}; }}
QPushButton[primary="true"] {{ background: {ACCENT}; color: {ACCENT_INK}; font-weight: 600; border-color: {ACCENT}; }}
QPushButton[primary="true"]:hover {{ background: {QColor(ACCENT).lighter(118).name()}; }}
QPushButton[primary="true"]:disabled {{ background: {rgba(ACCENT, .35)}; color: {rgba(ACCENT_INK, .7)}; border-color: transparent; }}
QPushButton[danger="true"]:hover {{ border-color: {BAD}; background: {rgba(BAD, .15)}; }}
QPushButton[chip="true"] {{ padding: 2px 9px; border-radius: 10px; font-size: 92%; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; }}
QCheckBox::indicator {{ border: 1px solid {MUTED}; border-radius: 3px; background: {BG2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; {_CHECK_IMG} }}
QCheckBox::indicator:disabled {{ border-color: {LINE}; }}
QSlider::groove:horizontal {{ height: 4px; background: {LINE}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; margin: -6px 0; background: {ACCENT}; border-radius: 7px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QHeaderView::section {{ background: {BG2}; color: {MUTED}; padding: 5px 6px; border: 0; border-bottom: 1px solid {LINE}; border-right: 1px solid {LINE}; }}
QTableView, QTreeView, QListView {{ background: {BG}; alternate-background-color: {BG2}; gridline-color: {LINE};
    border: 1px solid {LINE}; border-radius: 6px; selection-background-color: {_SEL}; selection-color: {INK}; }}
QTableView::item, QListView::item {{ padding: 3px 6px; }}
QListView::item:selected, QTreeView::item:selected {{ background: {_SEL}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {LINE}; min-height: 24px; border-radius: 5px; }}
QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {LINE}; min-width: 24px; border-radius: 5px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QSplitter::handle {{ background: {LINE}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QProgressBar {{ background: {BG2}; border: 1px solid {LINE}; border-radius: 4px; text-align: center; height: 8px; color: {INK}; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QFrame[card="true"] {{ background: {rgba(MUTED, .07)}; border: 1px solid {LINE}; border-radius: 10px; }}
QFrame[verdict="true"] {{ background: {rgba(SERIES[0], .12)}; border: 1px solid {rgba(SERIES[0], .4)}; border-radius: 10px; }}
QFrame[notice="true"] {{ background: {rgba(WARN, .14)}; border: 1px solid {rgba(WARN, .45)}; border-radius: 8px; }}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[h1="true"] {{ font-size: 20px; font-weight: 700; }}
QLabel[h2="true"] {{ font-size: 15px; font-weight: 700; }}
QLabel[kpi="true"] {{ font-size: 22px; font-weight: 600; }}
QLabel[pill="true"] {{ padding: 1px 8px; border-radius: 9px; font-weight: 600; }}
QLabel[section="true"] {{ color: {MUTED}; font-weight: 700; letter-spacing: .08em; font-size: 11px; margin-top: 6px; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(INK))
    pal.setColor(QPalette.Base, QColor(BG2))
    pal.setColor(QPalette.AlternateBase, QColor(PANEL))
    pal.setColor(QPalette.Text, QColor(INK))
    pal.setColor(QPalette.Button, QColor(BG2))
    pal.setColor(QPalette.ButtonText, QColor(INK))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor(ACCENT_INK))
    pal.setColor(QPalette.ToolTipBase, QColor(PANEL))
    pal.setColor(QPalette.ToolTipText, QColor(INK))
    pal.setColor(QPalette.PlaceholderText, QColor(MUTED))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(MUTED))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(MUTED))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
    f = QFont()
    for name in ("Segoe UI", "Inter", "Helvetica Neue", "DejaVu Sans"):
        if name in QFontDatabase.families():
            f.setFamily(name)
            break
    f.setPointSize(10)
    app.setFont(f)
    if (ASSETS / "favicon.png").exists():
        app.setWindowIcon(QIcon(str(ASSETS / "favicon.png")))


def icon(name: str) -> QIcon:
    p = ASSETS / "icons" / f"{name}.png"
    return QIcon(str(p)) if p.exists() else QIcon()
