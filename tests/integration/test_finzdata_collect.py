"""End-to-end FinzData collection through AdapterManager with a fake SDK."""

import sys
from types import SimpleNamespace

import pandas as pd

from darwin_collector import AdapterManager, CollectRequest
from darwin_collector.adapters.finzdata import FinzdataAdapter


class FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []

    def prices(self, **kwargs):
        self.calls.append(kwargs)
        return pd.DataFrame({"date": ["2025-01-02"], "close": [42.0]})


def test_manager_collect_finzdata(monkeypatch):
    client = FakeClient()
    monkeypatch.setitem(
        sys.modules,
        "finzdata",
        SimpleNamespace(Client=lambda **kwargs: client, Ticker=object, download=lambda *a, **k: pd.DataFrame()),
    )

    manager = AdapterManager()
    manager.register("finzdata", FinzdataAdapter)
    request = CollectRequest(
        source="finzdata",
        method="prices",
        params={"symbol": "MSFT", "start": "2025-01-01"},
        credentials={"api_key": "fz_test"},
    )

    result = manager.collect(request)

    assert result.source == "finzdata"
    assert result.method == "prices"
    assert result.to_dataframe()["close"].tolist() == [42.0]
    assert client.calls == [{"symbol": "MSFT", "start": "2025-01-01"}]
    manager.close()
