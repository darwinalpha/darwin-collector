"""Collect from an in-memory adapter: no SDK, no network, no config file."""

from typing import Any

import pandas as pd

from darwin_collector import AdapterManager, CollectRequest
from darwin_collector.adapters.base import BaseAdapter


class MemoryAdapter(BaseAdapter):
    """The smallest complete adapter: declare a name and return one frame."""

    def get_source_name(self) -> str:
        return "memory"

    def collect_once(self, method: str, **kwargs: Any) -> pd.DataFrame:
        return pd.DataFrame({"symbol": ["AAPL"], "close": [123.45]})


def main() -> None:
    manager = AdapterManager()
    manager.register("memory", MemoryAdapter)

    result = manager.collect(CollectRequest(source="memory", method="prices"))
    print(result.to_dataframe().to_string(index=False))
    print(
        f"source={result.source} method={result.method} "
        f"rows={result.row_count} chunks={result.chunk_count}"
    )
    manager.close()


if __name__ == "__main__":
    main()
