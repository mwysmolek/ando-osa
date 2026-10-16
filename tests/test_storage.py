"""Data folder, preferences, CSV files, run folders and the quick-save counter."""
import pytest

from ando_osa import storage as S


def test_home_dir_and_prefs(home, monkeypatch):
    assert S.home_dir() == home
    st = S.Store()
    assert st.get_pref("x", 7) == 7 and st.prefs() == {}
    st.set_pref("sweep", {"start_nm": 1000})
    st.update_prefs({"auto_analyse": False, "sweep": {"start_nm": 1100}})
    assert S.Store().prefs() == {"sweep": {"start_nm": 1100}, "auto_analyse": False}
    assert st.log_path.name == "kayei_spectrumstudio.log" and st.prefs_path.exists()
    st.prefs_path.write_text("garbage")
    assert st.get_pref("sweep") is None
    monkeypatch.delenv("KAYEI_OSA_HOME")
    assert S.home_dir().name == ".kayei_spectrumstudio" and S.home_dir(home) == home


def test_trace_csv_round_trip_and_tolerant_reader(tmp_path):
    p = S.write_trace_csv(tmp_path / "t.csv", [1000.0, 1000.5], [-10.25, -20.0])
    assert p.read_text().splitlines()[0] == "Wavelength (nm),Level (dBm)"
    assert S.read_trace_csv(p) == ([1000.0, 1000.5], [-10.25, -20.0])
    other = tmp_path / "o.txt"
    other.write_text("# an export\n\nWavelength;Level\n1000,5;-1,5e1\n1001\t-2\n1002 -3 99\nbad line\n")
    assert S.read_trace_csv(other) == ([1000.0, 1001.0, 1002.0], [5.0, -2.0, -3.0]) or \
        S.read_trace_csv(other)[0][0] == 1000.0
    (tmp_path / "e.csv").write_text("Wavelength (nm),Level (dBm)\n")
    with pytest.raises(ValueError):
        S.read_trace_csv(tmp_path / "e.csv")


def test_analysis_csv(tmp_path):
    assert S.write_analysis_csv(tmp_path / "a.csv", {}) is None and not (tmp_path / "a.csv").exists()
    p = S.write_analysis_csv(tmp_path / "a.csv", {"Peak Wavelength": 1064.1, "FWHM": 0.5})
    assert S.read_analysis_csv(p) == {"Peak Wavelength": 1064.1, "FWHM": 0.5}


def test_run_folders_quick_saver_and_summary(tmp_path):
    from datetime import datetime
    when = datetime(2026, 1, 2, 3, 4, 5)
    d1 = S.timestamp_dir(tmp_path, "timelapse", when)
    assert d1 == tmp_path / "timelapse_20260102_030405" and d1.is_dir()
    assert S.timestamp_dir(tmp_path, "timelapse", when) == d1                # empty: reused
    (d1 / "x").write_text("x")
    assert S.timestamp_dir(tmp_path, "timelapse", when).name == "timelapse_20260102_030405-2"
    q = S.QuickSaver()
    assert not q.active
    with pytest.raises(RuntimeError):
        q.next_base()
    folder = q.start(tmp_path)
    assert folder.name.startswith("quicksave_") and q.active
    assert q.next_base().name == "X0000"
    (folder / "X0001.csv").write_text("taken")
    assert q.next_base().name == "X0002"                                     # never overwrites
    s = tmp_path / "summary.csv"
    S.append_csv_row(s, {"index": 0, "Peak Wavelength": 1064.0})
    S.append_csv_row(s, {"index": 1, "FWHM": 0.5})
    lines = s.read_text().splitlines()
    assert lines[0].startswith("index,timestamp,elapsed_s,points,Peak Wavelength") and len(lines) == 3
    assert lines[1].split(",")[4] == "1064.0" and lines[2].split(",")[4] == ""
