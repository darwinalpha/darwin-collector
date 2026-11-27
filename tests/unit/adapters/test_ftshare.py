"""Behavior-lock tests for the FTShare adapter (fake SDK, no network)."""

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
from darwin_collector.adapters.ftshare import FtshareAdapter


class FakeClient:
    def __init__(self, key, behavior):
        self.key = key
        self.behavior = behavior
        self.calls = []

    def market_data(self, **kwargs):
        self.calls.append(kwargs)
        error = self.behavior.get("error")
        if error:
            raise error
        return pd.DataFrame({"close": [1.0]})


def inject(monkeypatch, clients):
    made = []

    def market_api(api_key, base_url, timeout):
        client = clients[len(made)]
        made.append((api_key, base_url, timeout))
        return client

    monkeypatch.setitem(sys.modules, "ftshare", SimpleNamespace(market_api=market_api))
    return made


def test_requires_credentials():
    adapter = FtshareAdapter()
    with pytest.raises(AdapterAuthError):
        adapter.ensure_ready(None)
    with pytest.raises(AdapterAuthError):
        adapter.ensure_ready({"api_key": ""})


def test_multi_key_init_and_single_call(monkeypatch):
    clients = [FakeClient("k1", {}), FakeClient("k2", {})]
    made = inject(monkeypatch, clients)
    adapter = FtshareAdapter()
    adapter.ensure_ready({"api_keys": ["k1", "k2"]})
    assert adapter._key_pool.size == 2
    assert len(made) == 1  # first client warmed; others created lazily on rotation
    frame = adapter.collect_once("market_data", symbol="x", empty=None)
    assert frame["close"].tolist() == [1.0]
    all_calls = [call for client in clients for call in client.calls]
    assert len(all_calls) == 1
    assert "empty" not in all_calls[0]  # empty values stripped
    assert all_calls[0]["symbol"] == "x"


def test_429_rotates_token_and_is_bounded(monkeypatch):
    clients = [
        FakeClient("k1", {"error": RuntimeError("HTTP 429 rate limit")}),
        FakeClient("k2", {"error": RuntimeError("HTTP 429 rate limit")}),
    ]
    inject(monkeypatch, clients)
    adapter = FtshareAdapter()
    adapter.ensure_ready({"api_keys": ["k1", "k2"]})
    with pytest.raises(AdapterRateLimitError):
        adapter.collect_once("market_data")
    # Both keys went into cooldown via the shared pool; no unbounded loop.
    assert adapter._key_pool.size == 2
    assert not adapter._key_pool.has_available()


def test_empty_data_error_becomes_empty_frame(monkeypatch):
    clients = [FakeClient("k1", {"error": RuntimeError("http 400 数据文件没有可用记录")})]
    inject(monkeypatch, clients)
    adapter = FtshareAdapter()
    adapter.ensure_ready({"api_key": "k1"})
    assert adapter.collect_once("market_data").empty


@pytest.mark.parametrize(
    "error,expected",
    [
        (RuntimeError("401 unauthorized"), AdapterAuthError),
        (RuntimeError("frequency too many"), AdapterRateLimitError),
        (RuntimeError("connection timeout"), AdapterNetworkError),
        (RuntimeError("something else"), AdapterDataError),
    ],
)
def test_error_classification(monkeypatch, error, expected):
    clients = [FakeClient("k1", {"error": error})]
    inject(monkeypatch, clients)
    adapter = FtshareAdapter()
    adapter.ensure_ready({"api_key": "k1"})
    with pytest.raises(expected):
        adapter.collect_once("market_data")


def test_reuse_and_close(monkeypatch):
    clients = [FakeClient("k1", {})]
    inject(monkeypatch, clients)
    adapter = FtshareAdapter()
    adapter.ensure_ready({"api_key": "k1"})
    adapter.collect_once("market_data")
    adapter.collect_once("market_data")
    assert len(clients[0].calls) == 2
    adapter.close()
    assert adapter._key_clients == {}
