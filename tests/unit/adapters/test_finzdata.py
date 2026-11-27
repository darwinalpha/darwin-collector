"""Behavior-lock tests for the FinzData adapter using a fake SDK.

Frozen behaviors:
  - API key must come from ``credentials``; the library never reads env vars.
  - ``Client`` dataset methods and yfinance-style helpers are dispatched by name.
  - Framework chunk keys (``start_date`` / millis) map to SDK ``start`` / ``end``.
  - ``FinzError.status`` maps 401 / 403 / 429 / 5xx to typed exceptions.
  - Instances are reusable; ``reauth`` rebuilds the client with stored credentials.
"""

import importlib.metadata
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
from darwin_collector.adapters.finzdata import FinzdataAdapter


class FakeFinzError(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail
        super().__init__(f"{status}: {detail}")


class FakeClient:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.error = None
        FakeClient.instances.append(self)

    def prices(self, **kwargs):
        self.calls.append(("prices", kwargs))
        if self.error:
            raise self.error
        return pd.DataFrame({"date": ["2025-01-02"], "close": [10.0]})

    def me(self):
        self.calls.append(("me", {}))
        if self.error:
            raise self.error
        return {"plan": "free", "calls_today": 3}


class FakeTicker:
    instances = []

    def __init__(self, symbol, client=None):
        self.symbol = symbol
        self.client = client
        self.history_calls = []
        FakeTicker.instances.append(self)

    def history(self, **kwargs):
        self.history_calls.append(kwargs)
        return pd.DataFrame({"Date": ["2025-01-02"], "Close": [11.0]})


def fake_download(tickers, **kwargs):
    symbols = [tickers] if isinstance(tickers, str) else list(tickers)
    return pd.DataFrame({"ticker": symbols, "close": [1.0] * len(symbols)})


def inject_fake_sdk(monkeypatch):
    FakeClient.instances = []
    FakeTicker.instances = []
    module = SimpleNamespace(
        Client=FakeClient,
        Ticker=FakeTicker,
        download=fake_download,
        FinzError=FakeFinzError,
    )
    monkeypatch.setitem(sys.modules, "finzdata", module)
    return module


# ----------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------


def test_requires_credentials_from_caller(monkeypatch):
    inject_fake_sdk(monkeypatch)
    monkeypatch.setenv("FINZDATA_API_KEY", "fz_env")

    adapter = FinzdataAdapter()

    with pytest.raises(AdapterAuthError) as exc:
        adapter.ensure_ready(None)
    assert exc.value.source == "finzdata"
    with pytest.raises(AdapterAuthError):
        adapter.ensure_ready({})

    assert not FakeClient.instances  # env var must never be used


def test_lazy_init_and_client_call(monkeypatch):
    inject_fake_sdk(monkeypatch)
    adapter = FinzdataAdapter()

    adapter.ensure_ready(
        {"api_key": "fz_test", "base_url": "https://example.test", "timeout": 7}
    )

    assert len(FakeClient.instances) == 1
    assert FakeClient.instances[0].kwargs == {
        "api_key": "fz_test",
        "base_url": "https://example.test",
        "timeout": 7,
    }

    frame = adapter.collect_once("prices", symbol="MSFT", start=None, end="2025-01-31")
    assert frame["close"].tolist() == [10.0]
    assert FakeClient.instances[0].calls[0][1] == {
        "symbol": "MSFT",
        "end": "2025-01-31",
    }


def test_reauth_and_close_reuse_stored_credentials(monkeypatch):
    inject_fake_sdk(monkeypatch)
    adapter = FinzdataAdapter()
    adapter.ensure_ready({"api_key": "fz_test", "timeout": 9})

    first = FakeClient.instances[0]
    adapter.reauth()
    assert len(FakeClient.instances) == 2
    assert FakeClient.instances[1].kwargs["api_key"] == "fz_test"
    assert FakeClient.instances[1].kwargs["timeout"] == 9
    assert adapter._client is not first

    adapter.close()
    assert adapter._client is None
    assert adapter._sdk is None


# ----------------------------------------------------------------------
# Dispatch
# ----------------------------------------------------------------------


def test_ticker_history_alias_maps_chunk_keys(monkeypatch):
    inject_fake_sdk(monkeypatch)
    adapter = FinzdataAdapter()
    adapter.ensure_ready({"api_key": "fz_test"})

    frame = adapter.collect_once(
        "history",
        ticker="msft",
        start_date="2025-01-01",
        end_date="2025-01-31",
        auto_adjust=False,
    )

    assert frame["Close"].tolist() == [11.0]
    ticker = FakeTicker.instances[0]
    assert ticker.symbol == "msft"
    assert ticker.client is adapter._client
    assert ticker.history_calls[0] == {
        "start": "2025-01-01",
        "end": "2025-01-31",
        "auto_adjust": False,
    }


def test_download_accepts_symbols_alias(monkeypatch):
    inject_fake_sdk(monkeypatch)
    adapter = FinzdataAdapter()
    adapter.ensure_ready({"api_key": "fz_test"})

    frame = adapter.collect_once("download", symbols=["MSFT", "AAPL"], period="1y")

    assert frame["ticker"].tolist() == ["MSFT", "AAPL"]


def test_client_method_accepts_millis_chunk_keys(monkeypatch):
    inject_fake_sdk(monkeypatch)
    adapter = FinzdataAdapter()
    adapter.ensure_ready({"api_key": "fz_test"})

    start_ms = 1735689600000  # 2025-01-01T00:00:00Z
    end_ms = 1738368000000  # 2025-02-01T00:00:00Z
    adapter.collect_once(
        "prices",
        symbol="MSFT",
        since_ts_millis=start_ms,
        until_ts_millis=end_ms,
    )

    assert FakeClient.instances[0].calls[0][1] == {
        "symbol": "MSFT",
        "start": "2025-01-01",
        "end": "2025-02-01",
    }


def test_dict_result_becomes_single_row_frame(monkeypatch):
    inject_fake_sdk(monkeypatch)
    adapter = FinzdataAdapter()
    adapter.ensure_ready({"api_key": "fz_test"})

    frame = adapter.collect_once("me")
    assert frame.to_dict(orient="records") == [{"plan": "free", "calls_today": 3}]


def test_unknown_method_raises_data_error(monkeypatch):
    inject_fake_sdk(monkeypatch)
    adapter = FinzdataAdapter()
    adapter.ensure_ready({"api_key": "fz_test"})

    with pytest.raises(AdapterDataError) as exc:
        adapter.collect_once("not_a_method")
    assert exc.value.method == "not_a_method"


# ----------------------------------------------------------------------
# Error classification
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "error,expected,available",
    [
        (FakeFinzError(401, "bad key"), AdapterAuthError, False),
        (FakeFinzError(403, "plan does not include"), AdapterDataError, True),
        (FakeFinzError(429, "daily call limit reached"), AdapterRateLimitError, True),
        (FakeFinzError(503, "down"), AdapterNetworkError, True),
        (RuntimeError("connection reset"), AdapterNetworkError, True),
        (RuntimeError("something else"), AdapterDataError, True),
    ],
)
def test_error_classification(monkeypatch, error, expected, available):
    inject_fake_sdk(monkeypatch)
    adapter = FinzdataAdapter()
    adapter.ensure_ready({"api_key": "fz_test"})
    FakeClient.instances[0].error = error

    with pytest.raises(expected) as exc:
        adapter.collect_once("prices", symbol="MSFT")

    assert exc.value.source == "finzdata"
    assert exc.value.method == "prices"
    assert adapter.is_available() is available


def test_installed_sdk_surface():
    """Optional: when the finzdata extra is installed, verify its real surface."""
    fz = pytest.importorskip("finzdata")
    assert hasattr(fz, "Client")
    assert hasattr(fz, "FinzError")
    assert hasattr(fz.Client, "prices")
    assert hasattr(fz, "download")
    version = tuple(int(part) for part in importlib.metadata.version("finzdata").split(".")[:3])
    assert version >= (0, 1, 19)
