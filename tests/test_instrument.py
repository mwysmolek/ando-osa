"""The VISA driver against a fake resource manager: commands, parsing, scanning, fallback."""
import pytest

from ando_osa import instrument as I
from tests.fakes import ANDO_IDN, FakeResource, FakeRM, ando_rm


def test_validate_sweep_range():
    I.validate_sweep_range(1000, 1500)
    with pytest.raises(ValueError):
        I.validate_sweep_range(100, 1500)
    with pytest.raises(ValueError):
        I.validate_sweep_range(1000, 1800)
    with pytest.raises(ValueError):
        I.validate_sweep_range(1500, 1500)


def test_probe_lists_everything_and_closes_sessions():
    rm = ando_rm()
    found = dict(I.probe_resources(rm))
    assert found == {"GPIB0::1::INSTR": ANDO_IDN, "GPIB0::7::INSTR": "KEYSIGHT,N7744A,1,1", "ASRL3::INSTR": "",
                     "USB0::BAD::INSTR": ""}
    for name, r in rm.resources.items():
        if not r.fail_open:
            assert r.closed == r.opens == 1, name
    assert I.is_ando(ANDO_IDN) and not I.is_ando("") and I.is_ando("ando,aq6315")
    assert I.probe_resources(rm, stop=lambda: True) == []


def test_find_and_open():
    rm = ando_rm()
    osa = I.AndoOSA.find(rm)
    assert isinstance(osa, I.AndoOSA) and osa.idn == ANDO_IDN and osa.name == "GPIB0::1::INSTR"
    assert rm.resources["GPIB0::1::INSTR"].timeout == I.DEFAULT_TIMEOUT_MS and not osa.is_simulated
    with pytest.raises(ValueError):
        I.AndoOSA.open(rm, "GPIB0::7::INSTR")
    assert rm.resources["GPIB0::7::INSTR"].closed >= 1
    assert I.AndoOSA.find(FakeRM({"GPIB0::7::INSTR": FakeResource({"*IDN?": "KEYSIGHT"})})) is None
    assert I.AndoOSA.open(rm, "GPIB0::7::INSTR", require_ando=False).idn.startswith("KEYSIGHT")


def test_commands_sent():
    rm = ando_rm()
    osa = I.AndoOSA.find(rm)
    res = rm.resources["GPIB0::1::INSTR"]
    res.writes.clear()
    osa.initialize()
    assert res.writes == ["CLMES", "WRTA", "DSPA", "ACTV0", "FIXB", "BLKB", "FIXC", "BLKC"]
    res.writes.clear()
    osa.configure_sweep(1000, 1500.5, "0.1", "SHI1")
    osa.start_single_sweep()
    assert osa.sweep_in_progress() is False
    osa.abort_sweep()
    osa.set_reference_to_peak()
    osa.set_active_trace("C")
    osa.set_trace_mode("MAXA")
    osa.set_trace_display("B", False)
    osa.set_trace_display("C", True)
    osa.set_cw_mode()
    osa.set_pulsed_mode(250)
    assert res.writes == ["STAWL1000.00", "STPWL1500.50", "RESLN0.1", "SHI1", "SGL", "SWEEP?", "STP", "REF=P", "ACTV2",
                          "MAXA", "BLKB", "DSPC", "CLMES", "PLMES", "PKHLD250"]
    with pytest.raises(ValueError):
        osa.set_pulsed_mode(0)
    with pytest.raises(ValueError):
        osa.configure_sweep(1500, 1000, "0.1", "SMID")
    res.answers["SWEEP?"] = "1"
    assert osa.sweep_in_progress() is True
    osa.close()
    assert res.closed >= 1


def test_read_trace_truncates_and_restores_timeout():
    rm = ando_rm()
    osa = I.AndoOSA.find(rm)
    res = rm.resources["GPIB0::1::INSTR"]
    w, lv = osa.read_trace("A")
    assert w == [1000.0, 1000.1, 1000.2, 1000.3] and lv == [-10.0, -5.5, -5.0, -20.0]
    w, lv = osa.read_trace("B")
    assert (w, lv) == ([1500.0, 1500.5], [-1.0, -2.0])
    assert res.timeout == I.DEFAULT_TIMEOUT_MS
    assert I._parse_trace_block("3, 1, 2, 3,") == [1.0, 2.0, 3.0] and I._parse_trace_block("0") == []
    assert I.trace_mode_label("RAVB") == "RAVB – rolling average"


def test_open_resource_manager_falls_back_to_pyvisa_py(monkeypatch):
    import pyvisa
    calls = []

    class RM:
        def __init__(self, backend=""):
            calls.append(backend)
            if backend != "@py":
                raise OSError("no system VISA")
    monkeypatch.setattr(pyvisa, "ResourceManager", RM)
    assert isinstance(I.open_resource_manager(), RM) and calls == ["", "@py"]
    monkeypatch.setattr(pyvisa, "ResourceManager", lambda *a, **k: (_ for _ in ()).throw(OSError("none")))
    with pytest.raises(RuntimeError):
        I.open_resource_manager()
