"""The headless commands with the simulator, and the GUI dispatch."""
import json

import pytest

from ando_osa import APP_NAME, cli
from ando_osa.storage import read_analysis_csv, write_trace_csv


def test_sweep_with_the_simulator_writes_csv_analysis_and_png(tmp_path, capsys):
    out, png = tmp_path / "demo.csv", tmp_path / "demo.png"
    rc = cli.main(["sweep", "--simulate", "--start", "1000", "--stop", "1100", "--res", "0.1", "--out", str(out),
                   "--png", str(png), "--snr", "--srs", "--range", "1060:1070"])
    assert rc == 0 and out.exists() and png.stat().st_size > 1000
    anal = read_analysis_csv(tmp_path / "demo_anal.csv")
    assert abs(anal["Peak Wavelength"] - 1064.0) < 0.2 and anal["Power Content 1"] > 90 and "SNR" in anal and "SRS" in anal
    text = capsys.readouterr().out
    assert "points ->" in text and "Peak Wavelength" in text


def test_analyze_prints_json(tmp_path, capsys):
    p = write_trace_csv(tmp_path / "t.csv", [1000, 1001, 1002, 1003], [-30, -5, -4, -30])
    assert cli.main(["analyze", str(p), "--json", "--no-total", "--out", str(tmp_path / "a.csv")]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["Peak Wavelength"] == 1002.0 and "Total Power" not in d and (tmp_path / "a.csv").exists()
    assert cli.main(["analyze", str(p)]) == 0
    assert "Peak Wavelength" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["analyze", str(p), "--range", "oops"])


def test_version_and_bad_range(capsys):
    assert cli.main(["version"]) == 0 and APP_NAME in capsys.readouterr().out
    assert cli.main(["sweep", "--simulate", "--start", "1500", "--stop", "1000", "--out", "x.csv"]) == 2
    assert "error:" in capsys.readouterr().err


def test_scan_without_a_visa_backend(monkeypatch, capsys):
    from ando_osa import instrument
    monkeypatch.setattr(instrument, "open_resource_manager", lambda backend=None: (_ for _ in ()).throw(RuntimeError("no VISA")))
    assert cli.main(["scan"]) == 2 and "no VISA" in capsys.readouterr().err
    from tests.fakes import ando_rm
    monkeypatch.setattr(instrument, "open_resource_manager", lambda backend=None: ando_rm())
    assert cli.main(["scan"]) == 0
    out = capsys.readouterr().out
    assert "GPIB0::1::INSTR" in out and "<- Ando OSA" in out and "no *IDN? answer" in out


def test_no_command_starts_the_app(monkeypatch):
    import osa_qt.app
    seen = []
    monkeypatch.setattr(osa_qt.app, "main", lambda argv: seen.append(argv) or 0)
    assert cli.main([]) == 0 and cli.main(["app", "--simulate", "x.csv"]) == 0 and cli.main(["--simulate"]) == 0
    assert seen[1][1:] == ["--simulate", "x.csv"] and seen[2][1:] == ["--simulate"]
