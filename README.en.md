# darwin-collector

A library that does **data collection only**: register data-source adapters, run one collection task to completion, and return a unified result.

It does not read configuration files, write files, clean data, or perform routing / failover. Scheduling, config parsing, and persistence belong to the caller.

## Scope

| In scope | Out of scope |
| --- | --- |
| Adapter registration and lookup | Reading `adapter.json` or any config file |
| Initialization / login | Writer persistence |
| Single SDK call `collect_once()` | Cleaning / deduplication |
| Retry, rate-limit and pagination policies | Cross-source routing / failover |
| Multi API-key splitting and rotation | Worker process management (extension point only) |
| Unified exceptions and `CollectResult` | |

The only hard dependency is `pandas`; data-source SDKs are optional extras. Built-in defaults are code constants — all other settings are passed in by the caller after parsing.

## Installation

```bash
pip install -e .
pip install -e '.[tushare]'       # install a single SDK as needed
pip install -e '.[ftshare,tickflow,baostock,ohlcvault,finzdata,yfinance]'
pip install -e '.[finzdata]'      # FinzData official SDK
pip install -e '.[yfinance]'      # yfinance (Yahoo Finance data)
pip install -e '.[all]'           # install every SDK at once
```

## Minimal usage

```python
from darwin_collector import AdapterManager, CollectRequest
from darwin_collector.adapters.tushare import TushareAdapter

manager = AdapterManager()
manager.register("tushare", TushareAdapter)

request = CollectRequest(
    source="tushare",
    method="daily",
    params={"ts_code": "000001.SZ", "start_date": "20240101", "end_date": "20240131"},
    credentials={"token": "..."},   # parsed by the caller; the library reads no env vars
)
result = manager.collect(request)
df = result.to_dataframe()
```

With `fake=True` adapters skip the real SDK and return an empty DataFrame, useful for verifying the call chain.

## Layering

```
shell scheduler → fetch.py (facade) → fetcher.py (invoke / collect / call Writer) → darwin-collector → SDK
```

A worker is an optional execution backend selected by `resolve_backend(source)`. It currently always returns `direct` (in-process); the branch is reserved but no worker is implemented.

## Sources

| Source | Import path | Credentials (passed in by caller) | Pagination mode |
| --- | --- | --- | --- |
| tushare | `adapters.tushare.TushareAdapter` | `{"token": ...}` | framework (reverse date) |
| ftshare | `adapters.ftshare.FtshareAdapter` | `{"api_keys": [...]}` or `{"api_key": ...}` | adapter (SDK paginates internally); opt into framework chunking |
| tickflow | `adapters.tickflow.TickflowAdapter` | `{"token": ...}` | framework (millisecond chunks) |
| baostock | `adapters.baostock.BaostockAdapter` | none | none |
| ohlcvault | `adapters.ohlcvault.OhlcvaultAdapter` | optional `{"mirrors": [...], "snapshot": ...}` | none |
| finzdata | `adapters.finzdata.FinzdataAdapter` | `{"api_key": ...}` (`token` also accepted) | none; opt into framework chunking |
| yfinance | `adapters.yfinance.YfinanceAdapter` | none; optional `{"session": ...}` | none; opt into framework chunking |

Registration is the same for every source:

```python
from darwin_collector.adapters.baostock import BaostockAdapter
manager.register("baostock", BaostockAdapter)
result = manager.collect(CollectRequest(
    source="baostock",
    method="query_history_k_data_plus",
    params={"code": "sh.000001", "start_date": "20240101", "end_date": "20240131",
            "fields": "date,code,close", "frequency": "d"},
))
```

FinzData uses the official `finzdata.Client` method names and also accepts yfinance-style aliases:

```python
from darwin_collector.adapters.finzdata import FinzdataAdapter
manager.register("finzdata", FinzdataAdapter)

result = manager.collect(CollectRequest(
    source="finzdata",
    method="prices",  # or "history" / "download" / "cot" / "minutes" / "gex" ...
    params={"symbol": "MSFT", "start": "2025-01-01", "end": "2025-01-31"},
    credentials={"api_key": "fz_..."},  # FINZDATA_API_KEY is never read
))
```

yfinance needs no API key; `history` and `download` map directly to the official SDK:

```python
from darwin_collector.adapters.yfinance import YfinanceAdapter
manager.register("yfinance", YfinanceAdapter)

result = manager.collect(CollectRequest(
    source="yfinance",
    method="history",  # or "download" / "financials" / "info" / "dividends" ...
    params={"symbol": "MSFT", "start": "2025-01-01", "end": "2025-01-31"},
))
```

## Multi API-key and rotation

All keyed sources (tushare / ftshare / tickflow / finzdata) share the library-level key pool. A credential value containing commas is automatically split into multiple keys; list values work too:

```python
credentials={"token": "key1, key2, key3"}       # split into 3 keys
credentials={"api_keys": ["k1", "k2"]}          # equivalent
```

- On a **rate-limit** or **authentication** failure the pool rotates to the next key; a failed key is cooled down and becomes eligible again after the cooldown (never permanently blacklisted).
- Rotation state lives on the adapter instance, so a resident worker reuses the same pool across `collect()` calls. Cooldowns use a monotonic clock, requiring no external coordination.
- With a single key the legacy path is preserved (no internal rotation; the framework retry layer handles it).
- Customize behavior with `KeyRotationPolicy`, injected through `Policies` like the other policies:

```python
from darwin_collector import KeyRotationPolicy, Policies

request = CollectRequest(
    source="tushare", method="daily",
    credentials={"token": "key1, key2"},
    policies=Policies(key_rotation=KeyRotationPolicy(
        cooldown_seconds=30,
        auth_cooldown_seconds=300,
        max_rotations=3,
    )),
)
```

- `fake=True` skips SDK instantiation entirely; the executor returns an empty DataFrame.
- Adapters' `close()` is called once by the host at shutdown; instances are reusable across `collect()` calls, so the Baostock login session is established only once.
- FinzData maps `401` to auth error, `429` to rate limit, and `5xx` to network error; `403` means the plan excludes that dataset and maps to a data error without retrying.
- yfinance has no login step; `YFRateLimitError` maps to rate limit, missing-data / invalid-parameter errors to data errors, and connection / timeout errors to network errors. An empty DataFrame is a normal result, not an exception.

## Documentation

- [Development guide](docs/development-guide.md)
