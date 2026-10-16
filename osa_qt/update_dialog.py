"""Install an update: download the portable zip, verify it, unpack it next to this folder."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from ando_osa import APP_NAME, APP_SLUG, updates

from .widgets import caption, section

_LIVE: set = set()          # running downloads: parentless, so "Later" never destroys a running thread


class _Worker(QThread):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, asset: dict, sha: str | None):
        super().__init__()
        self.asset, self.sha = asset, sha
        _LIVE.add(self)
        self.finished.connect(self._release)

    def _release(self) -> None:
        _LIVE.discard(self)
        self.deleteLater()

    def run(self) -> None:
        try:
            dest = Path(tempfile.gettempdir()) / f"{APP_SLUG}-update" / self.asset["name"]
            path = updates.download(self.asset["url"], dest, self.progress.emit, self.sha)
            self.done.emit(path)
        except Exception as ex:  # noqa: BLE001 - shown to the user
            self.failed.emit(str(ex))


class UpdateDialog(QDialog):
    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.info = info
        self.setWindowTitle(f"Update {APP_NAME}")
        self.resize(560, 300)
        lay = QVBoxLayout(self)
        lay.addWidget(section(f"⬆️ Version {info['version']} is available"))
        self.asset = updates.asset_for_platform(info.get("assets") or [])
        notes = (info.get("notes") or "").strip()
        if notes:
            lab = QLabel(notes[:1200] + ("…" if len(notes) > 1200 else ""))
            lab.setWordWrap(True)
            lab.setProperty("muted", True)
            lay.addWidget(lab)
        if self.asset is None:
            lay.addWidget(caption("No download for this operating system in the release – open the release page "
                                  "to pick one."))
        else:
            mb = self.asset["size"] / 2**20
            lay.addWidget(caption(f"{self.asset['name']} ({mb:,.0f} MB). The file is checked against the published "
                                  "SHA-256 before anything is started. The portable zip is unpacked into a folder "
                                  "next to this one (or your data folder); close this app and start the new one – "
                                  f"settings in ~/.{APP_SLUG} stay."))
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = caption("")
        lay.addWidget(self.status)
        lay.addStretch(1)
        row = QHBoxLayout()
        self.b_page = QPushButton("Open release page")
        self.b_page.clicked.connect(lambda: __import__("webbrowser").open(info["url"]))
        row.addWidget(self.b_page)
        row.addStretch(1)
        self.b_go = QPushButton("Download and install")
        self.b_go.setProperty("primary", True)
        self.b_go.setEnabled(self.asset is not None)
        self.b_go.clicked.connect(self.start)
        row.addWidget(self.b_go)
        self.b_close = QPushButton("Later")
        self.b_close.clicked.connect(self.reject)
        row.addWidget(self.b_close)
        lay.addLayout(row)
        self.worker: _Worker | None = None
        self.path: str | None = None
        self.unpacked: str | None = None

    def start(self) -> None:
        self.b_go.setEnabled(False)
        self.bar.show()
        self.status.setText("Downloading…")
        sums = updates.checksums(self.info.get("assets") or [])
        sha = sums.get(self.asset["name"])
        if not sha:
            self._failed("no published SHA-256 for this file could be read, so it is not installed – open the "
                         "release page and check the file yourself")
            return
        self.worker = _Worker(self.asset, sha)
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _progress(self, done: int, total: int) -> None:
        if total:
            self.bar.setValue(int(100 * done / total))
        else:
            self.bar.setRange(0, 0)

    def _done(self, path: str) -> None:
        self.path = path
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self.status.setText("Verified. Unpacking…")
        try:
            where = updates.launch(path, self.info.get("version"))
        except (OSError, ValueError) as ex:
            self._failed(str(ex))
            return
        if Path(where).is_dir():
            self.unpacked = where
            self.status.setText(f"Unpacked to {where}. Close this app and start {APP_SLUG}.exe from there; delete the "
                                "old folder whenever you like.")
            self.b_close.setText("Close")
            return
        self.status.setText("Verified. Started.")
        self.accept()

    def _failed(self, msg: str) -> None:
        self.bar.hide()
        self.b_go.setEnabled(True)
        self.status.setText(f"Update not installed: {msg}")
