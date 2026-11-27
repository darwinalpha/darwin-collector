"""Behavior-lock tests for the OHLCVault adapter (fake SDK, no network)."""

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from darwin_collector import (
    AdapterAuthError,
    AdapterDataError,
    AdapterNetworkError,
    AdapterRateLimitError,
)
from darwin_collector.adapters.ohlcvault import OhlcvaultAdapter


class FakeBars:
    def to_pandas(self):
        frame = pd.DataFrame({"close": [3.0]}, index=pd.Index(["2024-01-02"], name="date"))
        return frame


class FakeOhlcvault:
    def __init__(self, error=None):
        self.error = error
        self.connect_calls = []
        self.cross_section_calls = []

    def connect(self, **kwargs):
        self.connect_calls.append(kwargs)
        return SimpleNamespace(snapshot="snap-1")

    def cross_section(self, *args, **kwargs):
        self.cross_section_calls.append((args, kwargs))
        if self.error:
            raise self.error
        return FakeBars()


def inject(monkeypatch, fake_ov):
    monkeypatch.setitem(sys.modules, "ohlcvault", fake_ov)
    return fake_ov


def test_positional_args_and_reset_index(monkeypatch):
    ov = inject(monkeypatch, FakeOhlcvault())
    adapter = OhlcvaultAdapter()
    adapter.ensure_ready({"mirrors": ["m1"], "snapshot": "snap-0"})
    assert ov.connect_calls[0] == {"mirrors": ["m1"], "snapshot": "snap-0"}
    frame = adapter.collect_once("cross_section", _market="cn", _date="20240101", limit=6000, blank="")
    assert "date" in frame.columns
    assert frame["close"].tolist() == [3.0]
    args, kwargs = ov.cross_section_calls[0]
    assert args == ("cn", "20240101")
    assert kwargs == {"limit": 6000}
    adapter.close()


def test_unknown_method_raises_data_error(monkeypatch):
    inject(monkeypatch, FakeOhlcvault())
    adapter = OhlcvaultAdapter()
    adapter.ensure_ready({})
    with pytest.raises(AdapterDataError):
        adapter.collect_once("no_such")


@pytest.mark.parametrize(
    "error,expected",
    [
        (RuntimeError("snapshot not found 410"), AdapterDataError),
        (RuntimeError("429 too many"), AdapterRateLimitError),
        (RuntimeError("connection timeout"), AdapterNetworkError),
        (RuntimeError("401 unauthorized"), AdapterAuthError),
        (RuntimeError("other"), AdapterDataError),
    ],
)
def test_error_classification(monkeypatch, error, expected):
    inject(monkeypatch, FakeOhlcvault(error=error))
    adapter = OhlcvaultAdapter()
    adapter.ensure_ready({})
    with pytest.raises(expected):
        adapter.collect_once("cross_section")


def test_reuse_and_close(monkeypatch):
    ov = inject(monkeypatch, FakeOhlcvault())
    adapter = OhlcvaultAdapter()
    adapter.ensure_ready({})
    adapter.collect_once("cross_section")
    adapter.collect_once("cross_section")
    assert len(ov.cross_section_calls) == 2
    assert len(ov.connect_calls) == 1
    adapter.close()
    assert adapter._ov is None
