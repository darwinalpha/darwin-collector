"""End-to-end yfinance collection through AdapterManager with a fake SDK."""

import sys
from types import SimpleNamespace

import pandas as pd

from darwin_collector import AdapterManager, CollectRequest
from darwin_collector.adapters.yfinance import YfinanceAdapter


class FakeTicker:
    def __init__(self, ticker, session=None):
        self.ticker = ticker
        self.session = session

    def history(self, **kwargs):
        return pd.DataFrame({"Date": ["2025-01-02"], "Close": [77.0]})


def test_manager_collect_yfinance(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(Ticker=FakeTicker, download=lambda *a, **k: pd.DataFrame()),
    )

    manager = AdapterManager()
    manager.register("yfinance", YfinanceAdapter)
    request = CollectRequest(
        source="yfinance",
        method="history",
        params={"symbol": "MSFT", "period": "1mo"},
    )

    result = manager.collect(request)

    assert result.source == "yfinance"
    assert result.method == "history"
    assert result.to_dataframe()["Close"].tolist() == [77.0]
    manager.close()
