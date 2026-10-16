"""Is a newer kayEi SpectrumStudio released? Asked once per app start, in the background.

Only the public release list on GitHub is read; nothing about the user or their
measurements is sent. On by default in the packaged app, off when run from source;
Preferences has the switch. The portable zip is downloaded, checked against the
published SHA-256 and unpacked next to the folder the app runs from.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.request

from . import APP_NAME, REPO, __version__

RELEASES = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOADS = f"https://github.com/{REPO}/releases/latest"
FOLDER_PREFIX = "kayEi-SpectrumStudio"
_UA = f"kayei-spectrumstudio/{__version__}"

_found: dict = {}
_started = False


def default_enabled() -> bool:
    return bool(getattr(sys, "frozen", False))


def _parse(v: str) -> tuple[int, ...]:
    out = []
    for part in v.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits or 0))
    return tuple(out)


def is_newer(candidate: str, current: str = __version__) -> bool:
    try:
        return _parse(candidate) > _parse(current)
    except ValueError:
        return False


def _check() -> None:
    try:
        req = urllib.request.Request(RELEASES, headers={"Accept": "application/vnd.github+json", "User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=6) as r:
            d = json.load(r)
        tag = str(d.get("tag_name", ""))
        if not d.get("draft") and not d.get("prerelease") and is_newer(tag):
            assets = [{"name": a.get("name", ""), "url": a.get("browser_download_url", ""),
                       "size": int(a.get("size") or 0)} for a in d.get("assets") or []]
            _found.update(version=tag.lstrip("vV"), url=d.get("html_url") or DOWNLOADS, assets=assets,
                          notes=str(d.get("body") or ""))
    except Exception:  # noqa: BLE001 - offline, proxy, rate limit: just stay quiet
        pass


def start() -> None:
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_check, name="update-check", daemon=True).start()


def available() -> dict | None:
    return dict(_found) or None


# ---- in-app update: download the right file, verify it, unpack it ----------------------
def asset_for_platform(assets: list[dict]) -> dict | None:
    """The portable zip (Windows) or archive (Linux) for this machine, or None."""
    want = {"win32": (".zip",), "darwin": (".dmg",)}.get(sys.platform, (".tar.gz", ".AppImage"))
    cands = [a for a in assets if a["name"].endswith(want)]
    if want == (".zip",):
        cands = [a for a in cands if "portable" in a["name"].lower()]
    return cands[0] if cands else None


def checksums(assets: list[dict]) -> dict[str, str]:
    """name -> sha256 from every ``SHA256SUMS*`` file of the release; a file that is not
    listed has no published checksum and must not be installed."""
    out: dict[str, str] = {}
    for a in assets:
        if not a["name"].upper().startswith("SHA256SUMS"):
            continue
        try:
            req = urllib.request.Request(a["url"], headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                text = r.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - one unreachable file must not hide the others
            continue
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                out[parts[-1].lstrip("*").rsplit("/", 1)[-1]] = parts[0].lower()
    return out


def download(url: str, dest, progress=None, expected_sha256: str | None = None) -> str:
    """Download to ``dest`` with ``progress(done, total)``; verify the SHA-256 when given.
    Returns the path; raises ValueError on a checksum mismatch."""
    import hashlib
    from pathlib import Path
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 18)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress is not None:
                progress(done, total)
    if expected_sha256 and h.hexdigest().lower() != expected_sha256.lower():
        tmp.unlink(missing_ok=True)
        raise ValueError("the downloaded file does not match the published checksum – not installed")
    tmp.replace(dest)
    return str(dest)


def unpack(path: str, version: str | None = None) -> str:
    """Unzip a portable build into a fresh folder ``kayEi-SpectrumStudio-<version>`` next to
    the folder this app runs from – or, when that is not writable (or the app is not
    frozen), under the data folder's ``updates/``. Nothing of the running copy is touched:
    the user closes it and starts the new one. Returns the new folder."""
    import re
    import shutil
    import zipfile
    from pathlib import Path

    from .storage import home_dir
    p = Path(path)
    m = re.search(r"-portable-(\d[\w.]*?)\.zip$", p.name)
    ver = version or (m.group(1) if m else p.stem)
    name = f"{FOLDER_PREFIX}-{ver}"
    bases = []
    if getattr(sys, "frozen", False):
        bases.append(Path(sys.executable).resolve().parent.parent)
    bases.append(home_dir() / "updates")
    with zipfile.ZipFile(p) as z:
        for member in z.namelist():
            q = Path(member)
            if q.is_absolute() or ".." in q.parts:
                raise ValueError(f"refusing to unpack {member!r} – not a {APP_NAME} zip")
        for base in bases:
            target, k = base / name, 2
            while target.exists() and any(target.iterdir()):
                target, k = base / f"{name}-{k}", k + 1
            try:
                target.mkdir(parents=True, exist_ok=True)
                z.extractall(target)
                return str(target)
            except OSError:
                shutil.rmtree(target, ignore_errors=True)
    raise OSError("could not unpack the update next to the app or in the data folder")


def launch(path: str, version: str | None = None) -> str:
    """Hand the downloaded file to the OS: unpack a portable zip and open its folder, else
    reveal the archive. Returns the folder or file opened."""
    import os
    import subprocess
    if path.lower().endswith(".zip"):
        folder = unpack(path, version)
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
        return folder
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - the file we just verified
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])
    return path
