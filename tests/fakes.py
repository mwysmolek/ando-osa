"""A fake VISA resource manager for the driver and the connect worker."""
from __future__ import annotations


class FakeResource:
    def __init__(self, answers: dict | None = None, fail_open: bool = False):
        self.answers = dict(answers or {})
        self.writes: list[str] = []
        self.timeout = 0
        self.closed = 0
        self.opens = 0
        self.fail_open = fail_open
        self._last = ""

    def write(self, cmd: str) -> None:
        self.writes.append(cmd)
        self._last = cmd

    def read(self) -> str:
        if self._last not in self.answers:
            raise OSError(f"timeout waiting for an answer to {self._last!r}")
        return self.answers[self._last]

    def close(self) -> None:
        self.closed += 1


class FakeRM:
    def __init__(self, resources: dict[str, FakeResource]):
        self.resources = resources

    def list_resources(self):
        return tuple(self.resources)

    def open_resource(self, name: str):
        r = self.resources[name]
        if r.fail_open:
            raise OSError(f"cannot open {name}")
        r.opens += 1
        return r


ANDO_IDN = "ANDO,AQ6317B,12345678,1.02"
TRACE_ANSWERS = {"*IDN?": ANDO_IDN, "SWEEP?": "0",
                 "WDATA": "4, 1000.00, 1000.10, 1000.20, 1000.30", "LDATA": "4, -10.0, -5.5, -5.0, -20.0",
                 "WDATB": "2, 1500.0, 1500.5", "LDATB": "3, -1.0, -2.0, -3.0"}


def ando_rm(extra: dict | None = None) -> FakeRM:
    res = {"GPIB0::1::INSTR": FakeResource(TRACE_ANSWERS),
           "GPIB0::7::INSTR": FakeResource({"*IDN?": "KEYSIGHT,N7744A,1,1"}),
           "ASRL3::INSTR": FakeResource({}),
           "USB0::BAD::INSTR": FakeResource({}, fail_open=True)}
    res.update(extra or {})
    return FakeRM(res)
