"""Split comma-separated keys and rotate away from a rate-limited key."""

from typing import Any, Optional

import pandas as pd

from darwin_collector import (
    AdapterAuthError,
    AdapterManager,
    AdapterRateLimitError,
    CollectRequest,
    KeyRotationPolicy,
    Policies,
)
from darwin_collector.adapters.base import BaseAdapter
from darwin_collector.policies import RateLimitPolicy


class MultiKeyAdapter(BaseAdapter):
    key_fields = ("token",)

    def get_source_name(self) -> str:
        return "multi-key"

    def ensure_ready(self, credentials: Optional[dict] = None) -> None:
        if self._initialized:
            return
        pool = self._init_key_pool(credentials)
        if pool is None or not pool.has_available():
            raise AdapterAuthError("no usable token", source="multi-key")
        self._initialized = True

    def collect_once(self, method: str, **kwargs: Any) -> pd.DataFrame:
        def invoke(key: Optional[str]) -> pd.DataFrame:
            if key == "bad-key":
                raise AdapterRateLimitError("simulated 429", source="multi-key")
            return pd.DataFrame({"key_used": [key], "value": [7]})

        return self._run_with_keys(invoke)


def main() -> None:
    manager = AdapterManager()
    manager.register("multi-key", MultiKeyAdapter)

    result = manager.collect(CollectRequest(
        source="multi-key",
        method="prices",
        credentials={"token": "bad-key, good-key"},
        policies=Policies(
            key_rotation=KeyRotationPolicy(cooldown_seconds=60, max_rotations=2),
            rate_limit=RateLimitPolicy(interval_ms=0),
        ),
    ))
    adapter = manager.get_adapter("multi-key")
    print(result.to_dataframe().to_string(index=False))
    print(f"key_hits={adapter._key_pool.hits()}")  # inspection only; not a public API
    manager.close()


if __name__ == "__main__":
    main()
