"""Behavior-lock tests for the Baostock adapter (fake SDK, no network)."""

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
from darwin_collector.adapters.baostock import BaostockAdapter


class FakeResult:
    def __init__(self, code="0", msg="", fields=None, rows=None):
        self.error_code = code
        self.error_msg = msg
        self.fields = fields or []
        self._rows = rows or []
        self._index = -1

    def next(self):
        self._index += 1
        return self._index < len(self._rows)

    def get_row_data(self):
        return self._rows[self._index]


class FakeBs:
    def __init__(self, login_code="0", query_error=None):
        self.login_code = login_code
        self.query_error = query_error
        self.login_count = 0
        self.logout_count = 0
        self.calls = []

    def login(self):
        self.login_count += 1
        return FakeResult(code=self.login_code)

    def logout(self):
        self.logout_count += 1
        return FakeResult()

    def query_history_k_data_plus(self, **kwargs):
        self.calls.append(kwargs)
        if self.query_error:
            raise self.query_error
        return FakeResult(
            fields=["date", "close", "volume"],
            rows=[["2024-01-02", "10.5", "100"], ["2024-01-03", "11.0", "200"]],
        )


def inject(monkeypatch, fake_bs):
    monkeypatch.setitem(sys.modules, "baostock", fake_bs)
    return fake_bs


def test_login_once_and_reuse_across_calls(monkeypatch):
    bs = inject(monkeypatch, FakeBs())
    adapter = BaostockAdapter()
    adapter.ensure_ready({})
    adapter.collect_once("query_history_k_data_plus", code="sh.000001", blank=None)
    adapter.collect_once("query_history_k_data_plus", code="sh.000001")
    assert bs.login_count == 1
    assert bs.logout_count == 0
    assert "blank" not in bs.calls[0]
    adapter.close()
    assert bs.logout_count == 1


def test_login_failure_raises_auth_error(monkeypatch):
    inject(monkeypatch, FakeBs(login_code="1001"))
    adapter = BaostockAdapter()
    with pytest.raises(AdapterAuthError):
        adapter.ensure_ready({})


def test_numeric_conversion(monkeypatch):
    inject(monkeypatch, FakeBs())
    adapter = BaostockAdapter()
    adapter.ensure_ready({})
    frame = adapter.collect_once("query_history_k_data_plus")
    assert pd.api.types.is_numeric_dtype(frame["close"])
    assert frame["volume"].tolist() == [100, 200]


def test_query_error_code_is_data_error(monkeypatch):
    bs = inject(monkeypatch, FakeBs())
    bs.query_history_k_data_plus = lambda **kwargs: FakeResult(code="1", msg="bad")
    adapter = BaostockAdapter()
    adapter.ensure_ready({})
    with pytest.raises(AdapterDataError):
        adapter.collect_once("query_history_k_data_plus")


@pytest.mark.parametrize(
    "error,expected",
    [
        (RuntimeError("too many requests"), AdapterRateLimitError),
        (RuntimeError("connection timeout"), AdapterNetworkError),
        (RuntimeError("other"), AdapterDataError),
    ],
)
def test_error_classification(monkeypatch, error, expected):
    inject(monkeypatch, FakeBs(query_error=error))
    adapter = BaostockAdapter()
    adapter.ensure_ready({})
    with pytest.raises(expected):
        adapter.collect_once("query_history_k_data_plus")


def test_none_mode_declared():
    from darwin_collector.types import PaginationMode

    assert BaostockAdapter.pagination_mode == PaginationMode.NONE
