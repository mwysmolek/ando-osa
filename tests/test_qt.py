"""The desktop app, offscreen: theme and widgets, the window with the simulator (sweep,
continuous sweep, time-lapse, import, quick save, save as), dialogs, the panel's memory,
the connect worker against a fake VISA bus, the log page."""
import logging
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from ando_osa.simulator import SimulatedOSA  # noqa: E402
from ando_osa.storage import Store, write_trace_csv  # noqa: E402


@pytest.fixture(scope="session")
def app():
    from osa_qt import theme
    a = QApplication.instance() or QApplication(["test"])
    theme.apply_theme(a)
    return a


@pytest.fixture
def store(app, home):
    st = Store(home)
    st.update_prefs({"update_check": False, "auto_connect": False})
    return st


@pytest.fixture
def win(store, monkeypatch):
    from osa_qt.mainwindow import MainWindow
    QSettings("kayEi", "SpectrumStudio").clear()
    no_dialogs(monkeypatch)
    w = MainWindow(store)
    w.show()
    w.start()
    yield w
    w.close()
    pump(0.05)


def pump(seconds=0.05):
    end = time.time() + seconds
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)


def wait_until(pred, seconds=30.0):
    t0 = time.time()
    while time.time() - t0 < seconds:
        QCoreApplication.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    return False


def no_dialogs(monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))


def fast_sim(win, **kw):
    sim = SimulatedOSA(seed=1, sweep_seconds=0.05, drift=False, **kw)
    win._adopt(sim)
    return sim


def test_theme_widgets_and_table(app):
    from PySide6.QtGui import QGuiApplication
    from osa_qt.widgets import Kpi, Notice, Table, pill
    assert "Fusion" in app.style().objectName().title() or app.styleSheet()
    k = Kpi("Peak", "tip")
    k.set("1064.000 nm", "centre", "#fff")
    assert k.v.text() == "1064.000 nm" and k.d.text() == "centre"
    n = Notice("")
    assert n.isHidden() or not n.isVisible()
    n.set("hello")
    assert n.lab.text() == "hello"
    assert pill("x", "#ff0000").text() == "x"
    t = Table()
    t.set_rows([{"trace": "A", "points": 12000, "p": 0.5}, {"trace": "B", "points": 3, "p": None}], ["trace", "points", "p"],
               fmt={"p": lambda v: f"{v:.1%}"}, titles={"p": "Share"})
    m = t.model()
    assert m.rowCount() == 2 and m.columnCount() == 3 and m.headerData(2, Qt.Horizontal) == "Share"
    assert t._model.text(0, 1) == "12,000" and t._model.text(0, 2) == "50.0%" and t._model.text(1, 2) == "–"
    t.sortByColumn(1, Qt.AscendingOrder)
    assert [m.data(m.index(r, 1)) for r in range(2)] == ["3", "12,000"]
    t.copy_table()
    lines = QGuiApplication.clipboard().text().splitlines()
    assert lines[0] == "trace\tpoints\tShare" and lines[1].startswith("B\t3")


def test_window_sweeps_with_the_simulator(win):
    assert win.osa is None and win.busy_mode is None and not win.panel.b_sweep.isEnabled()
    win.start_sweep()                                               # nothing connected: a flash, no crash
    win.use_simulator()
    assert win.osa.is_simulated and win.panel.b_sweep.isEnabled() and "Simulator" in win.panel.conn.text()
    win.panel.start.setValue(1000)
    win.panel.stop.setValue(1200)
    win.start_sweep()
    assert win.busy_mode == "sweep" and not win.panel.b_sweep.isEnabled() and win.panel.b_stop.isEnabled()
    assert wait_until(lambda: "A" in win.traces and win.busy_mode is None), "no sweep result"
    r = win.results["A"]
    assert abs(r["Peak Wavelength"] - 1064.0) < 0.2 and "FWHM" in r and "Total Power" in r and "SNR" not in r
    assert "1064" in win.page_spectrum.kpis.tiles["Peak wavelength"].v.text()
    assert win.page_spectrum.kpis.tiles["SNR"].v.text() == "–"
    assert win.page_spectrum.table.model().rowCount() == 1 and len(win.page_spectrum.canvas.ax.lines) >= 1
    assert "points" in win.info_lab.text() and win.store.get_pref("sweep")["stop_nm"] == 1200
    # analysis switches recompute at once; markers follow the switch
    win.panel.flags["SNR"].setChecked(True)
    assert "SNR" in win.results["A"] and "snr" in win.overlays["A"]
    win.panel.overlays.setChecked(False)
    assert win.a_overlays.isChecked() is False
    # trace B is hidden until it gets data; the active trace drives the KPIs
    win.panel.active.setCurrentIndex(1)
    assert win.panel.active_trace == "B" and win.page_spectrum.kpis.tiles["Peak wavelength"].v.text() == "–"
    win.start_sweep()
    assert wait_until(lambda: "B" in win.traces and win.busy_mode is None)
    assert win.visible["B"] and win.page_spectrum.trace_buttons["B"].isChecked()
    win.page_spectrum.trace_buttons["B"].setChecked(False)
    assert win.visible["B"] is False and "BLKB" in win.osa.commands
    win.page_spectrum.mode_boxes["A"].setCurrentIndex(2)
    assert win.osa.modes["A"] == "MAX"
    win.clear_traces()
    assert not win.traces and win.page_spectrum.table.model().rowCount() == 0


def test_continuous_sweep_follows_settings_and_stops(win):
    sim = fast_sim(win)
    win.panel.continuous.setChecked(True)
    assert win.a_continuous.isChecked()
    win.start_sweep()
    assert wait_until(lambda: win.sweep_worker is not None and win.sweep_worker.count >= 3), "no continuous sweeps"
    win.panel.start.setValue(1050)                                   # live change: the next sweep uses it
    assert wait_until(lambda: sim.start_nm == 1050.0 and win.traces["A"].wavelengths[0] == 1050.0)
    win.stop()
    assert wait_until(lambda: win.busy_mode is None)
    assert "STP" in sim.commands or sim.sweeps >= 3
    assert win.traces["A"].wavelengths[0] == 1050.0


def test_timelapse_writes_files_and_shows_the_trend(win, tmp_path):
    fast_sim(win)
    page = win.page_timelapse
    page.interval.setValue(0.0)
    page.count.setValue(3)
    page.directory.setText(str(tmp_path))
    win.panel.flags["SNR"].setChecked(True)
    win.start_timelapse()
    assert win.busy_mode == "timelapse" and page.b_stop.isEnabled() and win.tabs.currentWidget() is page
    assert wait_until(lambda: win.busy_mode is None and len(page.rows) == 3, 60), "time-lapse did not finish"
    run = page.folder
    assert run.parent == tmp_path and run.name.startswith("timelapse_")
    for i in range(3):
        assert (run / f"measurement_{i:03d}.csv").exists() and (run / f"measurement_{i:03d}.png").stat().st_size > 1000
        assert (run / f"measurement_{i:03d}_anal.csv").exists()
    lines = (run / "summary.csv").read_text().splitlines()
    assert len(lines) == 4 and "SNR" in lines[0]
    assert page.table.model().rowCount() == 3 and page.bar.value() == 3 and "Finished" in page.status.text()
    assert len(page.canvas.ax_trend.lines) >= 1 and len(page.canvas.ax_env.lines) >= 2
    assert win.traces["A"].source == "timelapse" and "SNR" in win.results["A"]
    assert win.store.get_pref("timelapse")["count"] == 3
    page.directory.setText(str(tmp_path / "missing"))
    win.start_timelapse()
    assert win.busy_mode is None                                     # refused with a dialog


def test_import_quick_save_and_save_as(win, tmp_path, monkeypatch):
    p = write_trace_csv(tmp_path / "old.csv", [1000, 1001, 1002, 1003, 1004], [-40, -20, -3, -20, -40])
    label = win.import_csv(str(p))
    assert label == "Import 1" and win.results[label]["Peak Wavelength"] == 1002.0
    assert win.page_spectrum.table.model().rowCount() == 1 and win.page_spectrum.b_clear_imports.isEnabled()
    assert win.import_csv(str(p)) == "Import 2" and win.store.get_pref("import_dir") == str(tmp_path)
    assert win.import_csv(str(tmp_path / "nope.csv")) is None
    fast_sim(win)
    assert win.quick_save() is None                                  # trace A has no data yet
    win.start_sweep()
    assert wait_until(lambda: "A" in win.traces and win.busy_mode is None)
    win.store.set_pref("quick_save_dir", str(tmp_path / "qs"))
    (tmp_path / "qs").mkdir()
    base = win.quick_save()
    assert base.name == "X0000" and base.with_suffix(".csv").exists() and base.with_suffix(".png").exists()
    assert (base.parent / "X0000_anal.csv").exists() and (base.parent / "X0000_overlay.png").exists()
    assert win.quick_save().name == "X0001"
    out = tmp_path / "saved.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "CSV (*.csv)")))
    assert win.save_as() == str(out) and out.exists() and (tmp_path / "saved_anal.csv").exists()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(tmp_path / "pic"), "PNG (*.png)")))
    assert win.save_as().endswith("pic.png") and (tmp_path / "pic.png").stat().st_size > 1000
    assert len(win.page_spectrum.canvas.ax.lines) >= 3
    win.clear_imports()
    assert list(win.traces) == ["A"] and not win.page_spectrum.b_clear_imports.isEnabled()


def test_dialogs(app, store, monkeypatch):
    from osa_qt.dialogs import CommandConsole, PowerRangesDialog, PreferencesDialog, pref
    no_dialogs(monkeypatch)
    d = PowerRangesDialog([{"start": 1000.0, "stop": 1010.0}])
    assert d.rows[0][0].isChecked() and not d.rows[1][0].isChecked()
    d.rows[1][0].setChecked(True)
    d.rows[1][1].setValue(1100.0)
    d.rows[1][2].setValue(1050.0)
    d.accept()
    assert d.result() != 1 and d.ranges() == [{"start": 1000.0, "stop": 1010.0}]      # refused: stop < start
    d.rows[1][2].setValue(1150.0)
    d.accept()
    assert d.ranges() == [{"start": 1000.0, "stop": 1010.0}, {"start": 1100.0, "stop": 1150.0}]
    assert pref(store, "sweep_timeout_s") == 40.0 and pref(store, "update_check") is False
    pd = PreferencesDialog(store)
    pd.timeout.setValue(90)
    pd.ref_peak.setChecked(False)
    pd.accept()
    assert pref(store, "sweep_timeout_s") == 90.0 and pref(store, "ref_to_peak") is False
    sim = SimulatedOSA(sweep_seconds=0.0)
    c = CommandConsole(lambda: sim)
    c.cmd.setText("*IDN?")
    c.query()
    assert "ANDO" in c.out.toPlainText()
    c.cmd.setText("STAWL1234.00")
    c.send()
    assert sim.start_nm == 1234.0
    c = CommandConsole(lambda: None)
    c.cmd.setText("*IDN?")
    c.query()
    assert "not connected" in c.out.toPlainText()


def test_panel_remembers_settings_and_validates(app, store):
    from osa_qt.panel import InstrumentPanel
    from osa_qt.workers import SweepParams
    p = InstrumentPanel(store)
    assert p.sweep_params() == SweepParams(1000.0, 1500.0, "0.1", "SMID")
    p.start.setValue(1100.0)
    p.sens.setCurrentIndex(2)
    p.flags["SRS"].setChecked(True)
    p.set_power_ranges([{"start": 1, "stop": 2}])
    p.mode.setCurrentText("Pulsed")
    assert p.peak_hold.isVisibleTo(p) and p.measurement_mode() == ("Pulsed", 100)
    q = InstrumentPanel(store)
    assert q.sweep_params() == SweepParams(1100.0, 1500.0, "0.1", "SHI1") and q.analysis_options()["SRS"] is True
    assert q.power_ranges == [{"start": 1.0, "stop": 2.0}] and q.mode.currentText() == "Pulsed"
    q.stop.setValue(1000.0)
    with pytest.raises(ValueError):
        q.sweep_params()
    q.set_resources([("GPIB0::1::INSTR", "ANDO,X"), ("ASRL1::INSTR", "")])
    assert q.resource.count() == 3 and "no *IDN?" in q.resource.itemText(2)
    q.set_connection("connected", "ANDO,AQ6317B")
    assert q.b_disconnect.isEnabled() and not q.b_connect.isEnabled() and q.idn.text() == "ANDO,AQ6317B"


def test_connect_worker_against_a_fake_bus_and_no_visa(win, monkeypatch):
    from tests.fakes import ando_rm
    win.rm = ando_rm()
    win.connect_device("", silent=True)
    assert win.busy_mode == "connect"
    assert wait_until(lambda: win.osa is not None and win.busy_mode is None), "did not connect"
    assert win.osa.idn.startswith("ANDO") and win.panel.resource.count() == 5
    assert "Connected" in win.panel.conn.text() and win.panel.b_sweep.isEnabled()
    win.disconnect_device()
    assert win.osa is None and "Not connected" in win.panel.conn.text()
    win.connect_device("GPIB0::7::INSTR", silent=True)              # explicitly the wrong one: refused
    assert wait_until(lambda: win.busy_mode is None) and win.osa is None
    win.rm = None
    from ando_osa import instrument
    monkeypatch.setattr(instrument, "open_resource_manager", lambda backend=None: (_ for _ in ()).throw(RuntimeError("no VISA")))
    win.connect_device("", silent=True)
    assert "No VISA" in win.panel.conn.text() and win.page_spectrum.notice.isVisibleTo(win)


def test_log_page_menus_and_help(win, monkeypatch):
    logging.getLogger("ando_osa").info("hello-from-the-engine")
    logging.getLogger("matplotlib.font_manager").debug("findfont: noise")
    assert wait_until(lambda: "hello-from-the-engine" in win.page_log.view.toPlainText(), 5)
    assert "findfont" not in win.page_log.view.toPlainText()
    win.page_log.level.setCurrentIndex(1)
    assert logging.getLogger("ando_osa").level == logging.DEBUG
    win.page_log.clear()
    assert win.page_log.view.toPlainText() == ""
    titles = [a.text() for a in win.menuBar().actions()]
    assert titles == ["&File", "&Instrument", "&Sweep", "&Analysis", "&View", "&Help"]
    win.show_page("method")
    assert "anti-Stokes" in win.page_method.view.toPlainText()
    from PySide6.QtWidgets import QDialog
    monkeypatch.setattr(QDialog, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    win.whats_new()
    win.about()
    win.preferences()
    win.power_ranges()
    win.send_command()
    assert win.console is not None
    win.report_exception("Traceback\nValueError: boom")
    win.check_updates_now()
