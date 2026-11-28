"""Inject retry and rate-limit policies for a flaky source."""

from typing import Any

import pandas as pd

from darwin_collector import (
    AdapterManager,
    AdapterRateLimitError,
    CollectRequest,
    Policies,
)
from darwin_collector.adapters.base import BaseAdapter
from darwin_collector.policies import RateLimitPolicy, RetryPolicy


class FlakyAdapter(BaseAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def get_source_name(self) -> str:
        return "flaky"

    def collect_once(self, method: str, **kwargs: Any) -> pd.DataFrame:
        self.calls += 1
        if self.calls == 1:
            raise AdapterRateLimitError("simulated 429", source="flaky")
        return pd.DataFrame({"symbol": ["MSFT"], "price": [420.0]})


def main() -> None:
    manager = AdapterManager()
    manager.register("flaky", FlakyAdapter)

    result = manager.collect(CollectRequest(
        source="flaky",
        method="prices",
        policies=Policies(
            retry=RetryPolicy(max_attempts=3, base_delay_ms=0, backoff=1.0),
            rate_limit=RateLimitPolicy(interval_ms=0, cooldown_ms=0),
        ),
    ))
    adapter = manager.get_adapter("flaky")
    print(f"sdk_calls={adapter.calls} rows={result.row_count}")
    print(result.to_dataframe().to_string(index=False))
    manager.close()


if __name__ == "__main__":
    main()
