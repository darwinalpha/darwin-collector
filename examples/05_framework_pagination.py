"""Framework pagination: options select a forward page-number strategy."""

from typing import Any

import pandas as pd

from darwin_collector import AdapterManager, CollectRequest, PaginationMode, Policies
from darwin_collector.adapters.base import BaseAdapter
from darwin_collector.policies import RateLimitPolicy


class PageAdapter(BaseAdapter):
    pagination_mode = PaginationMode.FRAMEWORK

    def __init__(self) -> None:
        super().__init__()
        self.pages: list[int] = []

    def get_source_name(self) -> str:
        return "pages"

    def collect_once(self, method: str, **kwargs: Any) -> pd.DataFrame:
        page = int(kwargs.get("page", 1))
        size = int(kwargs.get("page_size", 2))
        self.pages.append(page)
        return pd.DataFrame({
            "page": [page] * size,
            "id": [f"p{page}-{index}" for index in range(size)],
        })


def main() -> None:
    manager = AdapterManager()
    manager.register("pages", PageAdapter)

    result = manager.collect(CollectRequest(
        source="pages",
        method="list",
        params={"symbol": "AAPL"},
        options={"paginate": True, "page_size": 2, "max_pages": 2},
        policies=Policies(rate_limit=RateLimitPolicy(interval_ms=0)),
    ))
    adapter = manager.get_adapter("pages")
    print(f"pages_fetched={adapter.pages} rows={result.row_count}")
    print(result.to_dataframe().to_string(index=False))
    manager.close()


if __name__ == "__main__":
    main()
