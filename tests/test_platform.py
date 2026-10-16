"""Update check and verified download, the build helpers, names that must agree."""
import hashlib
import os
import sys
import zipfile
from pathlib import Path

import pytest

from ando_osa import APP_SLUG, __version__
from ando_osa import updates as U

ROOT = Path(__file__).resolve().parent.parent


def test_update_assets_and_download(tmp_path, monkeypatch):
    assets = [{"name": "kayEi-SpectrumStudio-portable-9.0.0.zip", "url": "u0", "size": 5},
              {"name": "kayEi-SpectrumStudio-9.0.0-linux-x86_64.tar.gz", "url": "u4", "size": 5},
              {"name": "SHA256SUMS.txt", "url": "u5", "size": 5}]
    monkeypatch.setattr(U.sys, "platform", "win32")
    assert U.asset_for_platform(assets)["name"].endswith("portable-9.0.0.zip")
    assert U.asset_for_platform([{"name": "other-9.0.0.zip", "url": "u", "size": 1}]) is None
    monkeypatch.setattr(U.sys, "platform", "linux")
    assert U.asset_for_platform(assets)["name"].endswith(".tar.gz") and U.asset_for_platform([]) is None
    assert U.is_newer("1.7.0", "1.6.0") and not U.is_newer("1.6.0", "1.6.0") and not U.is_newer("garbage", "1.0")
    assert U.is_newer("v9.9.9") and "ando-osa" in U.RELEASES
    src = tmp_path / "pkg.bin"
    src.write_bytes(b"kayei" * 1000)
    good = hashlib.sha256(src.read_bytes()).hexdigest()
    seen = []
    out = U.download(src.as_uri(), tmp_path / "dl" / "pkg.bin", lambda d, t: seen.append(d), good)
    assert os.path.getsize(out) == 5000 and seen[-1] == 5000
    with pytest.raises(ValueError):
        U.download(src.as_uri(), tmp_path / "dl" / "pkg2.bin", None, "00" * 32)
    assert not (tmp_path / "dl" / "pkg2.bin").exists()


def test_portable_update_is_unpacked_beside_the_app(tmp_path, monkeypatch, home):
    import subprocess
    z = tmp_path / "kayEi-SpectrumStudio-portable-9.1.0.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(f"{APP_SLUG}.exe", b"MZ")
        zf.writestr("_internal/data.txt", b"x")
    opened = []
    monkeypatch.setattr(U.sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "Popen", lambda args, **k: opened.append(args))
    folder = U.launch(str(z))
    assert folder == str(home / "updates" / "kayEi-SpectrumStudio-9.1.0")
    assert (Path(folder) / "_internal" / "data.txt").read_bytes() == b"x" and opened == [["xdg-open", folder]]
    assert U.unpack(str(z), "9.1.0").endswith("kayEi-SpectrumStudio-9.1.0-2")
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../escape.txt", b"no")
    with pytest.raises(ValueError):
        U.unpack(str(bad))
    assert not (tmp_path / "escape.txt").exists()


def test_checksums_merge_every_sums_file(monkeypatch):
    import io
    files = {"https://x/u5": "aa11 *kayEi-SpectrumStudio-portable-9.0.0.zip\n",
             "https://x/u6": "bb22  dist/kayEi-SpectrumStudio-9.0.0-linux-x86_64.tar.gz\n"}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open(req, timeout=0):
        url = req.full_url
        if url.endswith("u7"):
            raise OSError("unreachable")
        return _Resp(files[url].encode())
    monkeypatch.setattr(U.urllib.request, "urlopen", fake_open)
    assets = [{"name": "SHA256SUMS.txt", "url": "https://x/u5", "size": 1},
              {"name": "SHA256SUMS-linux.txt", "url": "https://x/u6", "size": 1},
              {"name": "SHA256SUMS-mac.txt", "url": "https://x/u7", "size": 1}, {"name": "x.zip", "url": "https://x/u1", "size": 1}]
    assert U.checksums(assets) == {"kayEi-SpectrumStudio-portable-9.0.0.zip": "aa11",
                                   "kayEi-SpectrumStudio-9.0.0-linux-x86_64.tar.gz": "bb22"}


def test_build_script_helpers_and_names():
    sys.path.insert(0, str(ROOT / "packaging"))
    import build_exe
    assert build_exe.version() == __version__ and build_exe.NAME == APP_SLUG == "kayei_spectrumstudio"
    assert build_exe.arch() in ("arm64", "x86_64") and callable(build_exe.sign_app)
    entry = (ROOT / "packaging" / "osa_desktop.py").read_text(encoding="utf-8")
    assert "osa_qt.app" in entry and "ando_osa.cli" in entry
    for wf in ("build-windows.yml", "tests.yml", "build-linux.yml", "cleanup-artifacts.yml"):
        text = (ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8")
        assert "RiskStudio" not in text and "TwinStudio" not in text and "twin" not in text.lower(), wf
    win = (ROOT / ".github" / "workflows" / "build-windows.yml").read_text(encoding="utf-8")
    assert "kayEi-SpectrumStudio-portable-" in win and "--smoke" in win and "KAYEI_OSA_HOME" in win
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "kayEi SpectrumStudio" in readme and "portable" in readme
    assert (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").startswith("# Changelog")
    assert (ROOT / "assets" / "logo.png").exists() and (ROOT / "assets" / "check.png").exists()
