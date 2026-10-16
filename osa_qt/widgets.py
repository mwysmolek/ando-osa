"""Shared widgets: KPI tiles, the notice banner, section labels, pills, a sortable /
copyable / exportable table over plain rows, and the save-file helper."""
from __future__ import annotations

import csv
import io
import math
from typing import Callable, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QMenu,
                               QMessageBox, QTableView, QVBoxLayout, QWidget)

from . import theme as T


def _is_nan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


class Kpi(QFrame):
    """One number with its title and a sub-line."""

    def __init__(self, title: str, tip: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("card", True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(2)
        self.t = QLabel(title)
        self.t.setProperty("muted", True)
        self.v = QLabel("–")
        self.v.setProperty("kpi", True)
        self.d = QLabel("")
        self.d.setProperty("muted", True)
        lay.addWidget(self.t)
        lay.addWidget(self.v)
        lay.addWidget(self.d)
        if tip:
            self.setToolTip(tip)

    def set(self, value: str, delta: str = "", color: Optional[str] = None) -> None:
        self.v.setText(value)
        self.d.setText(delta)
        self.v.setStyleSheet(f"color:{color};" if color else "")


class KpiRow(QWidget):
    def __init__(self, items: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.tiles: dict[str, Kpi] = {}
        for title, tip in items:
            k = Kpi(title, tip)
            self.tiles[title] = k
            lay.addWidget(k, 1)

    def set(self, title: str, value: str, delta: str = "", color: Optional[str] = None) -> None:
        self.tiles[title].set(value, delta, color)


class Notice(QFrame):
    """An amber banner (not connected, analysis off, a failed sweep)."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("notice", True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        self.lab = QLabel(text)
        self.lab.setWordWrap(True)
        self.lab.setTextFormat(Qt.RichText)
        lay.addWidget(self.lab, 1)
        self.setVisible(bool(text))

    def set(self, html: str) -> None:
        self.lab.setText(html)
        self.setVisible(bool(html))


def section(title: str) -> QLabel:
    lab = QLabel(title)
    lab.setProperty("h2", True)
    return lab


def heading(title: str) -> QLabel:
    """The small upper-case section label of the side panel."""
    lab = QLabel(title.upper())
    lab.setProperty("section", True)
    return lab


def caption(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setProperty("muted", True)
    lab.setWordWrap(True)
    return lab


def pill(text: str, color: str) -> QLabel:
    lab = QLabel(text)
    lab.setProperty("pill", True)
    set_pill(lab, text, color)
    return lab


def set_pill(lab: QLabel, text: str, color: str) -> None:
    lab.setText(text)
    lab.setStyleSheet(f"background:{T.rgba(color, .2)}; border:1px solid {color}; padding:1px 8px; border-radius:9px;")


# ---- tables -----------------------------------------------------------------------------------
class RowsModel(QAbstractTableModel):
    """Read-only view of ``rows`` (dicts) in ``columns`` with per-column formatting: numbers
    right-aligned, None/NaN as '–', the raw value for sorting."""
    SORT = Qt.UserRole + 1

    def __init__(self, rows: list[dict], columns: list[str], fmt: Optional[dict] = None, titles: Optional[dict] = None,
                 parent=None):
        super().__init__(parent)
        self.rows = list(rows)
        self.columns = list(columns)
        self.fmt = fmt or {}
        self.titles = titles or {}

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            c = self.columns[section]
            return self.titles.get(c, c)
        return None

    def text(self, row: int, col: int) -> str:
        c = self.columns[col]
        v = self.rows[row].get(c)
        if _is_nan(v):
            return "–"
        if c in self.fmt:
            try:
                return self.fmt[c](v)
            except (TypeError, ValueError):
                return str(v)
        if isinstance(v, bool):
            return "yes" if v else ""
        if isinstance(v, int):
            return f"{v:,}"
        if isinstance(v, float):
            return f"{v:,.3f}"
        return str(v)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.DisplayRole:
            return self.text(index.row(), index.column())
        if role == Qt.ToolTipRole:
            t = self.text(index.row(), index.column())
            return t if len(t) > 24 else None
        if role == Qt.TextAlignmentRole:
            v = self.rows[index.row()].get(self.columns[index.column()])
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return None
        if role == self.SORT:
            return self.rows[index.row()].get(self.columns[index.column()])
        return None


class _SortProxy(QSortFilterProxyModel):
    def lessThan(self, left, right) -> bool:  # noqa: N802
        a = self.sourceModel().data(left, RowsModel.SORT)
        b = self.sourceModel().data(right, RowsModel.SORT)
        na, nb = _is_nan(a), _is_nan(b)
        if na or nb:
            return (not na) and nb if self.sortOrder() == Qt.AscendingOrder else na and (not nb)
        if isinstance(a, (int, float, bool)) and isinstance(b, (int, float, bool)):
            return float(a) < float(b)
        return str(a).lower() < str(b).lower()


class Table(QTableView):
    """Rows of dicts; sortable by clicking the header, Ctrl+C copies, right-click exports."""
    rowActivated = Signal(dict)

    def __init__(self, parent=None, height: Optional[int] = None):
        super().__init__(parent)
        self.doubleClicked.connect(self._activated)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.setSortingEnabled(True)
        self.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)      # rows as given until a header is clicked
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self._proxy = _SortProxy(self)
        self._model: Optional[RowsModel] = None
        self.export_name = "table"
        if height:
            self.setFixedHeight(height)

    @property
    def rows(self) -> list[dict]:
        return self._model.rows if self._model is not None else []

    def set_rows(self, rows: list[dict], columns: list[str], fmt: Optional[dict] = None, titles: Optional[dict] = None,
                 widths: Optional[dict] = None) -> None:
        sort_col, sort_order = self.horizontalHeader().sortIndicatorSection(), self.horizontalHeader().sortIndicatorOrder()
        self._model = RowsModel(rows, columns, fmt, titles, self)
        self._proxy.setSourceModel(self._model)
        self.setModel(self._proxy)
        self.horizontalHeader().setSortIndicatorShown(True)
        if 0 <= sort_col < len(columns):
            self.sortByColumn(sort_col, sort_order)
        else:
            self._proxy.sort(-1)
        self.resizeColumnsToContents()
        for i, c in enumerate(columns):
            if widths and c in widths:
                self.setColumnWidth(i, widths[c])
            else:
                self.setColumnWidth(i, min(max(self.columnWidth(i) + 12, 70), 320))

    def _source_row(self, index) -> int:
        return self._proxy.mapToSource(index).row() if index.model() is self._proxy else index.row()

    def _activated(self, index) -> None:
        if self._model is None:
            return
        r = self._source_row(index)
        if 0 <= r < len(self._model.rows):
            self.rowActivated.emit(dict(self._model.rows[r]))

    def _lines(self, rows: Optional[list[int]] = None, sep: str = "\t") -> str:
        m = self._model
        if m is None:
            return ""
        order = [self._source_row(self._proxy.index(r, 0)) for r in range(self._proxy.rowCount())]
        if rows is not None:
            keep = set(rows)
            order = [r for r in order if r in keep]
        out = io.StringIO()
        w = csv.writer(out, delimiter=sep, lineterminator="\n")
        w.writerow([m.titles.get(c, c) for c in m.columns])
        for r in order:
            w.writerow([m.text(r, c) for c in range(len(m.columns))])
        return out.getvalue()

    def _selected_rows(self) -> list[int]:
        sm = self.selectionModel()
        return sorted({self._source_row(i) for i in sm.selectedRows()}) if sm is not None else []

    def copy_rows(self) -> None:
        rows = self._selected_rows()
        QGuiApplication.clipboard().setText(self._lines(rows if rows else None))

    def copy_table(self) -> None:
        QGuiApplication.clipboard().setText(self._lines())

    def export_csv(self) -> None:
        if self._model is None:
            return
        save_file(self, f"{self.export_name}.csv", "CSV (*.csv)",
                  lambda p: open(p, "w", encoding="utf-8", newline="").write(self._lines(sep=",")))

    def keyPressEvent(self, e):  # noqa: N802
        if e.matches(QKeySequence.StandardKey.Copy):
            self.copy_rows()
            return
        super().keyPressEvent(e)

    def _menu(self, pos) -> None:
        if self._model is None:
            return
        menu = QMenu(self)
        for text, fn in (("Copy row(s)\tCtrl+C", self.copy_rows), ("Copy table", self.copy_table),
                         ("Export CSV…", self.export_csv)):
            a = QAction(text, self)
            a.triggered.connect(fn)
            menu.addAction(a)
        menu.exec(self.viewport().mapToGlobal(pos))


def save_file(parent, suggested: str, filter_: str, writer: Callable[[str], None], title: str = "Save") -> Optional[str]:
    """Ask where to save, write with ``writer(path)``, report an error in a dialog."""
    path, _ = QFileDialog.getSaveFileName(parent, title, suggested, filter_)
    if not path:
        return None
    try:
        writer(path)
    except Exception as ex:  # noqa: BLE001 - shown to the user, never lost in the log
        QMessageBox.warning(parent, title, f"Could not write {path}:\n{type(ex).__name__}: {ex}")
        return None
    return path
