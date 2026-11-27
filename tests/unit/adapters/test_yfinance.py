"""Behavior-lock tests for the yfinance adapter using a fake SDK.

Frozen behaviors:
  - no API key / login is required; an optional caller-supplied session is passed through
  - ``history`` / ``download`` / Ticker method aliases dispatch by name
  - framework chunk keys (``start_date`` / millis) map to yfinance ``start`` / ``end``
  - yfinance exception types map to rate-limit / data / network errors
  - instances are reusable and ``close`` clears the SDK reference
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
from darwin_collector.adapters.yfinance import YfinanceAdapter


class YFRateLimitError(Exception):
    pass


class YFPricesMissingError(Exception):
    pass


class FakeTicker:
    instances = []
    error = None

    def __init__(self, ticker, session=None):
        self.ticker = ticker
        self.session = session
        self.history_calls = []
        self.financials_calls = []
        self.info = {"longName": "Fake Corp", "currency": "USD"}
        FakeTicker.instances.append(self)

    def history(self, **kwargs):
        self.history_calls.append(kwargs)
        if self.error:
            raise self.error
        return pd.DataFrame({"Date": ["2025-01-02"], "Close": [11.0]})

    def financials(self, **kwargs):
        self.financials_calls.append(kwargs)
        if self.error:
            raise self.error
        return pd.DataFrame({"2025-01-01": [100.0]}, index=["Total Revenue"])


def fake_download(tickers, **kwargs):
    symbols = [tickers] if isinstance(tickers, str) else list(tickers)
    fake_download.calls.append((symbols, kwargs))
    if fake_download.error:
        raise fake_download.error
    return pd.DataFrame({"ticker": symbols, "close": [1.0] * len(symbols)})


fake_download.calls = []
fake_download.error = None


def inject_fake_sdk(monkeypatch):
    FakeTicker.instances = []
    FakeTicker.error = None
    fake_download.calls = []
    fake_download.error = None
    module = SimpleNamespace(Ticker=FakeTicker, download=fake_download)
    monkeypatch.setitem(sys.modules, "yfinance", module)
    return module


# ----------------------------------------------------------------------
# Lifecycle
# ----------------------------------------------------------------------


def test_no_credentials_needed(monkeypatch):
    inject_fake_sdk(monkeypatch)
    monkeypatch.delenv("YFINANCE_API_KEY", raising=False)

    adapter = YfinanceAdapter()
    adapter.ensure_ready(None)

    assert adapter.is_available()
    assert adapter._sdk is not None


def test_session_from_credentials_is_reused(monkeypatch):
    inject_fake_sdk(monkeypatch)
    session = object()

    adapter = YfinanceAdapter()
    adapter.ensure_ready({"session": session})
    adapter.collect_once("history", symbol="MSFT", period="1mo")

    assert FakeTicker.instances[0].session is session

    adapter.reauth()
    assert adapter._sdk is not None
    adapter.collect_once("history", symbol="MSFT", period="1mo")
    assert FakeTicker.instances[1].session is session

    adapter.close()
    assert adapter._sdk is None
    assert adapter._session is None


# ----------------------------------------------------------------------
# Dispatch
# ----------------------------------------------------------------------


def test_history_alias_maps_chunk_keys(monkeypatch):
    inject_fake_sdk(monkeypatch)
    adapter = YfinanceAdapter()
    adapter.ensure_ready()

    frame = adapter.collect_once(
        "ticker.history",
        ticker="msft",
        start_date="2025-01-01",
        end_date="2025-01-31",
        auto_adjust=False,
    )

    assert frame["Close"].tolist() == [11.0]
    assert FakeTicker.instances[0].ticker == "msft"
    assert FakeTicker.instances[0].history_calls[0] == {
        "start": "2025-01-01",
        "end": "2025-01-31",
        "auto_adjust": False,
    }


def test_millis_chunk_keys_map_to_start_end(monkeypatch):
    inject_fake_sdk(monkeypatch)
    adapter = YfinanceAdapter()
    adapter.ensure_ready()

    adapter.collect_once(
        "history",
        symbol="MSFT",
        since_ts_millis=1735689600000,  # 2025-01-01Z
        until_ts_millis=1738368000000,  # 2025-02-01Z
    )

    assert FakeTicker.instances[0].history_calls[0] == {
        "start": "2025-01-01",
        "end": "2025-02-01",
    }


def test_download_accepts_symbols_alias_and_session(monkeypatch):
    inject_fake_sdk(monkeypatch)
    session = object()
    adapter = YfinanceAdapter()
    adapter.ensure_ready({"session": session})

    frame = adapter.collect_once("download", symbols=["MSFT", "AAPL"], period="1y")

    assert frame["ticker"].tolist() == ["MSFT", "AAPL"]
    symbols, kwargs = fake_download.calls[0]
    assert symbols == ["MSFT", "AAPL"]
    assert kwargs["period"] == "1y"
    assert kwargs["session"] is session


def test_ticker_property_becomes_dataframe(monkeypatch):
    inject_fake_sdk(monkeypatch)
    adapter = YfinanceAdapter()
    adapter.ensure_ready()

    frame = adapter.collect_once("ticker.info", symbol="MSFT")

    assert frame.to_dict(orient="records") == [
        {"longName": "Fake Corp", "currency": "USD"}
    ]


def test_get_method_alias_calls_ticker_method(monkeypatch):
    inject_fake_sdk(monkeypatch)
    adapter = YfinanceAdapter()
    adapter.ensure_ready()

    frame = adapter.collect_once("get_financials", symbol="MSFT")

    assert frame.index.tolist() == ["Total Revenue"]
    assert FakeTicker.instances[0].financials_calls == [{}]


def test_unknown_method_raises_data_error(monkeypatch):
    inject_fake_sdk(monkeypatch)
    adapter = YfinanceAdapter()
    adapter.ensure_ready()

    with pytest.raises(AdapterDataError) as exc:
        adapter.collect_once("not_a_method", symbol="MSFT")
    assert exc.value.method == "not_a_method"


# ----------------------------------------------------------------------
# Error classification
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "error,expected",
    [
        (YFRateLimitError("Too Many Requests. Rate limited."), AdapterRateLimitError),
        (YFPricesMissingError("$MSFT: no price data found"), AdapterDataError),
        (ConnectionError("connection reset"), AdapterNetworkError),
        (RuntimeError("401 unauthorized"), AdapterAuthError),
        (RuntimeError("timed out"), AdapterNetworkError),
        (RuntimeError("something else"), AdapterDataError),
    ],
)
def test_error_classification(monkeypatch, error, expected):
    inject_fake_sdk(monkeypatch)
    adapter = YfinanceAdapter()
    adapter.ensure_ready()
    FakeTicker.error = error

    with pytest.raises(expected) as exc:
        adapter.collect_once("history", symbol="MSFT")

    assert exc.value.source == "yfinance"
    assert exc.value.method == "history"


def test_installed_sdk_surface():
    """Optional: when the yfinance extra is installed, verify its real surface."""
    yf = pytest.importorskip("yfinance")
    assert hasattr(yf, "Ticker")
    assert hasattr(yf, "download")
    assert hasattr(yf.Ticker, "history")
    version = tuple(int(part) for part in importlib.metadata.version("yfinance").split(".")[:3])
    assert version >= (1, 8, 0)
