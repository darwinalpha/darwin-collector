"""Shared fixtures: a fake adapter that never touches a real SDK."""

from typing import Any, Dict

import pandas as pd
import pytest

from darwin_collector.adapters.base import BaseAdapter
from darwin_collector.models import PaginationMode
from darwin_collector.types import PaginationMode as Mode


class FakeAdapter(BaseAdapter):
    def __init__(self, rows: int = 2, mode: PaginationMode = Mode.NONE) -> None:
        super().__init__()
        self.rows = rows
        self.pagination_mode = mode
        self.calls: list[Dict[str, Any]] = []
        self.closed = False
        self.reauth_count = 0

    def get_source_name(self) -> str:
        return "fake"

    def ensure_ready(self, credentials: Dict[str, Any] | None = None) -> None:
        self._initialized = True

    def reauth(self) -> None:
        self.reauth_count += 1
        self._initialized = True

    def close(self) -> None:
        self.closed = True

    def collect_once(self, method: str, **kwargs: Any) -> pd.DataFrame:
        self.calls.append({"method": method, **kwargs})
        return pd.DataFrame({"trade_date": ["20240102", "20240101"][: self.rows], "v": [1, 2][: self.rows]})


@pytest.fixture
def fake_adapter() -> FakeAdapter:
    return FakeAdapter()
