"""fake=True skips collect_once; ensure_ready still runs."""

from typing import Any

import pandas as pd

from darwin_collector import AdapterManager, CollectRequest
from darwin_collector.adapters.base import BaseAdapter


class DemoAdapter(BaseAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def get_source_name(self) -> str:
        return "demo"

    def collect_once(self, method: str, **kwargs: Any) -> pd.DataFrame:
        self.calls += 1
        return pd.DataFrame({"value": [1]})


def main() -> None:
    manager = AdapterManager()
    manager.register("demo", DemoAdapter)

    result = manager.collect(CollectRequest(
        source="demo", method="daily", params={"symbol": "AAPL"}, fake=True,
    ))
    adapter = manager.get_adapter("demo")

    print(f"fake={result.fake} rows={result.row_count} calls={adapter.calls}")
    print(result.to_dataframe().empty)
    manager.close()


if __name__ == "__main__":
    main()
