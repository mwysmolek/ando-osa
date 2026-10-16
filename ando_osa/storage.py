"""Files and folders: the data folder with the preferences, trace CSVs, analysis CSVs,
time-lapse run folders, the quick-save counter.

Everything the app remembers lives in one folder (``~/.kayei_spectrumstudio`` or
``$KAYEI_OSA_HOME``): ``settings.json`` (sweep settings, analysis options, folders,
update check) and ``kayei_spectrumstudio.log`` (the packaged app has no console).
Measurement data goes wherever the user points the app – never into the data folder.
"""
from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import APP_SLUG
from .analysis import METRICS

ENV_HOME = "KAYEI_OSA_HOME"
CSV_HEADER = ["Wavelength (nm)", "Level (dBm)"]
ANALYSIS_HEADER = ["Metric", "Value"]
SUMMARY_COLUMNS = ["index", "timestamp", "elapsed_s", "points", *METRICS]
_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def home_dir(home=None) -> Path:
    return Path(home or os.environ.get(ENV_HOME) or Path.home() / f".{APP_SLUG}")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Store:
    """The local data folder: preferences and the log file."""

    def __init__(self, home: Optional[os.PathLike | str] = None):
        self.home = home_dir(home)

    @property
    def prefs_path(self) -> Path:
        return self.home / "settings.json"

    @property
    def log_path(self) -> Path:
        return self.home / f"{APP_SLUG}.log"

    def prefs(self) -> dict:
        try:
            d = json.loads(self.prefs_path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def get_pref(self, key: str, default: Any = None) -> Any:
        return self.prefs().get(key, default)

    def set_pref(self, key: str, value: Any) -> None:
        self.update_prefs({key: value})

    def update_prefs(self, values: dict) -> None:
        d = self.prefs()
        d.update(values)
        _atomic_write(self.prefs_path, json.dumps(d, indent=1, default=str))


# ------------------------------------------------------------------------- CSV files
def write_trace_csv(path, wavelengths, levels) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        writer.writerows(zip(wavelengths, levels))
    return path


def read_trace_csv(path) -> tuple[list[float], list[float]]:
    """(wavelengths, levels) from a CSV written by this tool – or by anything else that puts
    two numbers per line (comma, semicolon, tab or space separated; headers and comment
    lines are skipped). Raises ValueError when no numeric pair is found."""
    wavelengths, levels = [], []
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith(("#", "//", ";;")):
                continue
            nums = _NUM.findall(s.replace(";", " ").replace(",", " ").replace("\t", " "))
            if len(nums) < 2:
                continue
            try:
                w, lv = float(nums[0]), float(nums[1])
            except ValueError:
                continue
            wavelengths.append(w)
            levels.append(lv)
    if not wavelengths:
        raise ValueError(f"{Path(path).name}: no numeric wavelength/level pairs found.")
    return wavelengths, levels


def write_analysis_csv(path, results: dict) -> Optional[Path]:
    """Metric/value rows; nothing is written (and None returned) for an empty result."""
    if not results:
        return None
    path = Path(path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(ANALYSIS_HEADER)
        for k, v in results.items():
            writer.writerow([k, v])
    return path


def read_analysis_csv(path) -> dict:
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0] != ANALYSIS_HEADER[0]:
                try:
                    out[row[0]] = float(row[1])
                except ValueError:
                    out[row[0]] = row[1]
    return out


def append_csv_row(path, row: dict, columns=SUMMARY_COLUMNS) -> Path:
    """One row of a running summary table; the header is written with the first row."""
    path = Path(path)
    new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(columns)
        writer.writerow(["" if row.get(c) is None else row.get(c) for c in columns])
    return path


# ---------------------------------------------------------------------- folders
def timestamp_dir(parent, prefix: str = "timelapse", when: Optional[datetime] = None) -> Path:
    """Create ``<parent>/<prefix>_YYYYmmdd_HHMMSS`` (``-2``, ``-3`` … when it exists)."""
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    base = Path(parent) / f"{prefix}_{stamp}"
    target, k = base, 2
    while target.exists() and any(target.iterdir()):
        target, k = Path(f"{base}-{k}"), k + 1
    target.mkdir(parents=True, exist_ok=True)
    return target


class QuickSaver:
    """Auto-numbered ``X0000``, ``X0001`` … bases inside one timestamped session folder."""

    def __init__(self):
        self.folder: Optional[Path] = None
        self.counter = 0

    @property
    def active(self) -> bool:
        return self.folder is not None

    def start(self, directory) -> Path:
        self.folder = timestamp_dir(directory, "quicksave")
        self.counter = 0
        return self.folder

    def next_base(self) -> Path:
        if self.folder is None:
            raise RuntimeError("quick save folder not chosen")
        while True:
            base = self.folder / f"X{self.counter:04d}"
            self.counter += 1
            if not base.with_suffix(".csv").exists():
                return base
