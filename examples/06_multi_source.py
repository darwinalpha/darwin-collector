"""Register several sources and reuse cached adapter instances."""

from typing import Any

import pandas as pd

from darwin_collector import AdapterManager, CollectRequest
from darwin_collector.adapters.base import BaseAdapter


class EchoAdapter(BaseAdapter):
    def __init__(self, source: str) -> None:
        super().__init__()
        self._source = source

    def get_source_name(self) -> str:
        return self._source

    def collect_once(self, method: str, **kwargs: Any) -> pd.DataFrame:
        return pd.DataFrame({"source": [self._source], "method": [method]})


def main() -> None:
    manager = AdapterManager()
    for source in ("alpha", "beta"):
        manager.register(source, lambda source=source: EchoAdapter(source))

    print(f"registered={manager.sources}")
    for source in ("alpha", "beta", "alpha"):
        result = manager.collect(CollectRequest(source=source, method="prices"))
        print(f"{source}: rows={result.row_count} method={result.method}")

    print(f"instance_reused={manager.get_adapter('alpha') is manager.get_adapter('alpha')}")
    manager.close()


if __name__ == "__main__":
    main()
