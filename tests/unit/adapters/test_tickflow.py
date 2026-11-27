"""Behavior-lock tests for the Tickflow adapter (fake SDK, no network)."""

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
from darwin_collector.adapters.tickflow import TickflowAdapter


class FakeKlines:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return pd.DataFrame({"close": [2.0]})


class FakeTickFlow:
    def __init__(self, api_key, error=None):
        self.api_key = api_key
        self.klines = FakeKlines(error)
        self.universes = SimpleNamespace(
            get=lambda: {"id": "u", "name": "all", "symbols": ["A", "B"]}
        )


def inject(monkeypatch, klines_error=None):
    created = []

    def TickFlow(api_key):
        client = FakeTickFlow(api_key, klines_error)
        created.append(client)
        return client

    monkeypatch.setitem(sys.modules, "tickflow", SimpleNamespace(TickFlow=TickFlow))
    return created


def test_requires_token():
    adapter = TickflowAdapter()
    with pytest.raises(AdapterAuthError):
        adapter.ensure_ready(None)


def test_dotted_method_and_symbol_positional(monkeypatch):
    created = inject(monkeypatch)
    adapter = TickflowAdapter()
    adapter.ensure_ready({"token": "tok"})
    frame = adapter.collect_once("klines.get", symbol="000001.SZ", period="1d", blank=None)
    assert frame["close"].tolist() == [2.0]
    args, kwargs = created[0].klines.calls[0]
    assert args == ("000001.SZ",)
    assert kwargs == {"period": "1d"}


def test_unknown_method_raises_data_error(monkeypatch):
    inject(monkeypatch)
    adapter = TickflowAdapter()
    adapter.ensure_ready({"token": "tok"})
    with pytest.raises(AdapterDataError):
        adapter.collect_once("no.such.method")


def test_dict_symbols_conversion(monkeypatch):
    inject(monkeypatch)
    adapter = TickflowAdapter()
    adapter.ensure_ready({"token": "tok"})
    frame = adapter.collect_once("universes.get")
    assert frame["symbol"].tolist() == ["A", "B"]


@pytest.mark.parametrize(
    "error,expected",
    [
        (RuntimeError("invalid api_key"), AdapterAuthError),
        (RuntimeError("throttle rate limit"), AdapterRateLimitError),
        (RuntimeError("connection timeout"), AdapterNetworkError),
        (RuntimeError("other"), AdapterDataError),
    ],
)
def test_error_classification(monkeypatch, error, expected):
    inject(monkeypatch, klines_error=error)
    adapter = TickflowAdapter()
    adapter.ensure_ready({"token": "tok"})
    with pytest.raises(expected):
        adapter.collect_once("klines.get")


def test_framework_mode_declared():
    from darwin_collector.types import PaginationMode

    assert TickflowAdapter.pagination_mode == PaginationMode.FRAMEWORK
