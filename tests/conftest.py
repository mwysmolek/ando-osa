import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A private data folder for every test."""
    h = tmp_path / "home"
    monkeypatch.setenv("KAYEI_OSA_HOME", str(h))
    return h
