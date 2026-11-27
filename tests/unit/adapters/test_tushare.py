"""Behavior-lock tests for the tushare adapter using a fake SDK.

Frozen behaviors from the original darwin-fetch adapter:
  - credentials required via ensure_ready (no env var read)
  - method name validated at call time
  - error classification: auth / rate / network / data
"""

from types import SimpleNamespace

import pandas as pd
import pytest

from darwin_collector import (
    AdapterAuthError,
    AdapterDataError,
    AdapterNetworkError,
    AdapterRateLimitError,
)
from darwin_collector.adapters.tushare import TushareAdapter


class FakePro:
    def __init__(self, token, error=None):
        self.token = token
        self.error = error
        self.calls = []

    def daily(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return pd.DataFrame({"trade_date": ["20240102"], "close": [10.0]})


def inject_fake_sdk(monkeypatch, fake_pro):
    # tushare may not be installed; inject a synthetic module without importing it.
    import sys

    module = sys.modules.get("tushare") or SimpleNamespace()
    module.pro_api = lambda token: fake_pro
    monkeypatch.setitem(sys.modules, "tushare", module)


def test_requires_credentials():
    a = TushareAdapter()
    with pytest.raises(AdapterAuthError):
        a.ensure_ready(None)
    with pytest.raises(AdapterAuthError):
        a.ensure_ready({})


def test_lazy_init_and_single_call(monkeypatch):
    pro = FakePro("tok")
    inject_fake_sdk(monkeypatch, pro)
    a = TushareAdapter()
    a.ensure_ready({"token": "tok"})
    df = a.collect_once("daily", ts_code="000001.SZ", end_date=None)
    assert df["close"].tolist() == [10.0]
    assert "end_date" not in pro.calls[0]  # empty values stripped


def test_unknown_method_raises_data_error(monkeypatch):
    pro = FakePro("tok")
    inject_fake_sdk(monkeypatch, pro)
    a = TushareAdapter()
    a.ensure_ready({"token": "tok"})
    with pytest.raises(AdapterDataError):
        a.collect_once("nonexistent")


@pytest.mark.parametrize(
    "error,expected",
    [
        (RuntimeError("invalid token"), AdapterAuthError),
        (RuntimeError("调用频率超限"), AdapterRateLimitError),
        (RuntimeError("connection timeout"), AdapterNetworkError),
        (RuntimeError("something else"), AdapterDataError),
    ],
)
def test_error_classification(monkeypatch, error, expected):
    pro = FakePro("tok", error=error)
    inject_fake_sdk(monkeypatch, pro)
    a = TushareAdapter()
    a.ensure_ready({"token": "tok"})
    with pytest.raises(expected):
        a.collect_once("daily", ts_code="000001.SZ")


def test_reuse_and_close(monkeypatch):
    pro = FakePro("tok")
    inject_fake_sdk(monkeypatch, pro)
    a = TushareAdapter()
    a.ensure_ready({"token": "tok"})
    a.collect_once("daily")
    a.collect_once("daily")
    assert len(pro.calls) == 2
    a.close()
    assert a._pro is None
