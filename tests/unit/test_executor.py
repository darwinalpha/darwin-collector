import pandas as pd
import pytest

from darwin_collector import AdapterManager, CollectRequest
from darwin_collector.types import PaginationMode
from tests.conftest import FakeAdapter


def make_manager(adapter):
    m = AdapterManager()
    m.register("fake", lambda: adapter)
    return m


def test_direct_collect_returns_result():
    adapter = FakeAdapter(rows=2)
    m = make_manager(adapter)
    req = CollectRequest(source="fake", method="daily", params={"code": "000001"})
    result = m.collect(req)

    assert isinstance(result.to_dataframe(), pd.DataFrame)
    assert result.row_count == 2
    assert result.source == "fake"
    assert result.method == "daily"
    assert adapter.calls[0]["code"] == "000001"


def test_fake_mode_skips_call():
    adapter = FakeAdapter()
    m = make_manager(adapter)
    result = m.collect(CollectRequest(source="fake", method="daily", fake=True))
    assert result.to_dataframe().empty
    assert adapter.calls == []


def test_adapter_instance_is_reused():
    adapter = FakeAdapter()
    m = make_manager(adapter)
    m.collect(CollectRequest(source="fake", method="a"))
    m.collect(CollectRequest(source="fake", method="b"))
    assert m.get_adapter("fake") is adapter


def test_close_releases_instances():
    adapter = FakeAdapter()
    m = make_manager(adapter)
    m.collect(CollectRequest(source="fake", method="a"))
    m.close()
    assert adapter.closed


def test_framework_pagination_loops_over_pages():
    class PagedAdapter(FakeAdapter):
        def __init__(self):
            super().__init__(mode=PaginationMode.FRAMEWORK)
            self.n = 0

        def collect_once(self, method, **kwargs):
            self.n += 1
            # First page is full (size 2), second is short -> stop.
            size = 2 if self.n == 1 else 1
            return pd.DataFrame({"start_date": ["20240101"] * size, "v": [self.n] * size})

    adapter = PagedAdapter()
    m = make_manager(adapter)
    req = CollectRequest(
        source="fake",
        method="daily",
        params={"start_date": "20240101", "end_date": "20240131"},
        options={"paginate": True, "page_size": 2},
    )
    result = m.collect(req)
    assert adapter.n >= 2
    assert result.row_count >= 3
