"""End-to-end: request → collect → result, without any Writer / config."""

import pandas as pd
import pytest

from darwin_collector import (
    AdapterManager,
    AdapterNotRegisteredError,
    CollectRequest,
)
from tests.conftest import FakeAdapter


def test_full_direct_chain():
    m = AdapterManager()
    m.register("fake", lambda: FakeAdapter(rows=2))
    result = m.collect(CollectRequest(source="fake", method="daily"))
    assert isinstance(result.to_dataframe(), pd.DataFrame)
    assert result.row_count == 2


def test_unregistered_source_raises():
    m = AdapterManager()
    with pytest.raises(AdapterNotRegisteredError):
        m.collect(CollectRequest(source="missing", method="daily"))


def test_result_has_no_write_metadata():
    m = AdapterManager()
    m.register("fake", lambda: FakeAdapter())
    result = m.collect(CollectRequest(source="fake", method="daily"))
    assert not hasattr(result, "path")
    assert not hasattr(result, "filename")
