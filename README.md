# darwin-collector

[English](https://github.com/darwinalpha/darwin-collector/blob/main/README.md) · [简体中文](https://github.com/darwinalpha/darwin-collector/blob/main/README.cn.md)

A library that does **data collection only**: register data-source adapters, run one collection task to completion, and return a unified result object.

It does not read configuration files, write files, clean data, or perform cross-source routing / failover. Scheduling, config parsing, and persistence belong to the caller.

- **Stable, small surface** — one `collect()` entry point, one request and one result contract
- **Configuration-free** — credentials and parameters are passed in; the library never reads env vars or `adapter.json`
- **Policy injection** — retry, rate limiting, pagination and API-key rotation are explicit `Policies`
- **Unified errors** — typed exceptions carry source, method and attempt context
- **SDKs are optional** — only `pandas` is a hard dependency; each data source is an extra

Python >= 3.10.

```bash
pip install darwin-collector                       # core (pandas only)
pip install 'darwin-collector[tushare]'            # one SDK
pip install 'darwin-collector[finzdata,yfinance]'  # several SDKs
pip install 'darwin-collector[all]'                # every SDK
pip install 'darwin-collector[test]'               # with pytest
```

---

## 1. Scope

| In scope | Out of scope |
| --- | --- |
| Adapter registration and lookup | Reading `adapter.json` or any config file |
| Initialization / login | Writer persistence |
| One SDK call through `collect_once()` | Cleaning / deduplication |
| Retry, rate-limit and pagination policies | Cross-source routing / failover |
| Multi API-key splitting and rotation | Worker process management (extension point only) |
| Typed exceptions and `CollectResult` | Environment variable loading |

Built-in defaults are code constants in `defaults.py`; all other values are supplied by the caller. See [the development guide](docs/development-guide.md) for the execution chain and adapter contract.

---

## 2. Quick start

```python
from darwin_collector import AdapterManager, CollectRequest
from darwin_collector.adapters.tushare import TushareAdapter

manager = AdapterManager()
manager.register("tushare", TushareAdapter)

request = CollectRequest(
    source="tushare",
    method="daily",
    params={"ts_code": "000001.SZ", "start_date": "20240101", "end_date": "20240131"},
    credentials={"token": "<your token>"},  # parsed by the caller
)
result = manager.collect(request)
df = result.to_dataframe()
print(result.row_count, result.chunk_count, result.elapsed_ms)
manager.close()
```

`fake=True` skips `collect_once()` and returns an empty frame, but `ensure_ready()` still runs. For a fully offline dry run, use a small custom adapter:

```python
from darwin_collector import AdapterManager, CollectRequest
from darwin_collector.adapters.base import BaseAdapter

class DemoAdapter(BaseAdapter):
    def get_source_name(self):
        return "demo"

    def collect_once(self, method, **kwargs):
        raise AssertionError("not called in fake mode")

manager = AdapterManager()
manager.register("demo", DemoAdapter)
result = manager.collect(CollectRequest(source="demo", method="daily", fake=True))
assert result.fake and result.row_count == 0
```

An unregistered source raises `AdapterNotRegisteredError`; an unsupported SDK method raises `MethodNotSupportedError`.

---

## 3. Core contracts

| Object | Responsibility |
| --- | --- |
| `AdapterManager` | Register factories, cache adapter instances, expose `collect()` and `close()` |
| `CollectRequest` | `source`, `method`, `params`, `options`, `credentials`, `policies`, `fake` |
| `CollectResult` | `frames`, `attempts`, `elapsed_ms`, `fake`, plus `to_dataframe()`, `to_records()`, `row_count`, `chunk_count` |
| `Policies` | Optional `RetryPolicy`, `RateLimitPolicy`, `Paginator`, `pagination_mode`, `KeyRotationPolicy` |
| `BaseAdapter` | Implement `get_source_name()` and `collect_once(method, **kwargs)`; optional `ensure_ready()`, `reauth()`, `close()` |

`CollectResult` has no file path, writer state or cleaning metadata: the caller decides what to do with the DataFrame.

Execution chain:

```text
AdapterManager.collect(request)
  -> resolve_backend(source)             # currently always direct
  -> get_adapter(source)                 # cached instance
  -> Executor.execute(adapter, request)
       -> configure(policies)
       -> ensure_ready(credentials)
       -> select paginator by pagination_mode
       -> rate_limit.before_call() + retry.run(collect_once)
       -> paginate, if framework mode
       -> CollectResult
```

Adapter instances are cached per manager and reused across `collect()` calls. `close()` releases all sessions and is the host's responsibility. `resolve_backend()` is the single backend selection point; it currently returns `direct` (in-process) and reserves the worker branch.

---

## 4. Supported sources

| Source | Import path | Credentials (passed by caller) | Pagination mode |
| --- | --- | --- | --- |
| tushare | `darwin_collector.adapters.tushare.TushareAdapter` | `{"token": ...}` | framework (reverse date) |
| ftshare | `darwin_collector.adapters.ftshare.FtshareAdapter` | `{"api_keys": [...]}` or `{"api_key": ...}` | adapter (SDK paginates internally); opt into framework chunking |
| tickflow | `darwin_collector.adapters.tickflow.TickflowAdapter` | `{"token": ...}` | framework (millisecond chunks) |
| baostock | `darwin_collector.adapters.baostock.BaostockAdapter` | none | none |
| ohlcvault | `darwin_collector.adapters.ohlcvault.OhlcvaultAdapter` | optional `{"mirrors": [...], "snapshot": ...}` | none |
| finzdata | `darwin_collector.adapters.finzdata.FinzdataAdapter` | `{"api_key": ...}` (`token` also accepted) | none; opt into framework chunking |
| yfinance | `darwin_collector.adapters.yfinance.YfinanceAdapter` | none; optional `{"session": ...}` | none; opt into framework chunking |

Registration is identical for every source:

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

FinzData uses the official `finzdata.Client` method names (`prices`, `minutes`, `cot`, `futures`, `macro`, `gex`, `fundamentals`, `valuation`, `datasets`, `me`, ...) plus yfinance-style aliases (`history`, `download`):

```python
from darwin_collector.adapters.finzdata import FinzdataAdapter

manager.register("finzdata", FinzdataAdapter)
result = manager.collect(CollectRequest(
    source="finzdata",
    method="prices",
    params={"symbol": "MSFT", "start": "2025-01-01", "end": "2025-01-31"},
    credentials={"api_key": "<your key>"},  # FINZDATA_API_KEY is never read
))
```

yfinance needs no API key. `download`, `history`, `info`, `financials`, `dividends` and other Ticker members map to the official SDK; an empty DataFrame is a normal result, not an error.

---

## 5. Policies and defaults

Pass a `Policies` object in `CollectRequest`; `None` fields use the constants from `defaults.py`.

| Policy | Defaults |
| --- | --- |
| `RetryPolicy` | 3 attempts, 500 ms base delay, 2.0 backoff, one re-login on auth error |
| `RateLimitPolicy` | 500 ms between calls, 5000 ms cooldown (the paginators never sleep themselves) |
| Pagination | 100 iterations / pages, page size 500, date field `trade_date`, stop after 3 empty chunks |
| `KeyRotationPolicy` | 30 s rate-limit cooldown, 300 s auth cooldown, max 3 rotations, both error types trigger rotation |

Only rate-limit and network errors are retried. Authentication errors call `reauth()` once and are then raised immediately; data errors are never retried.

```python
from darwin_collector import CollectRequest, Policies
from darwin_collector.policies import RateLimitPolicy, RetryPolicy

request = CollectRequest(
    source="tushare", method="daily",
    params={"ts_code": "000001.SZ"},
    policies=Policies(
        retry=RetryPolicy(max_attempts=5, base_delay_ms=200, backoff=1.5),
        rate_limit=RateLimitPolicy(interval_ms=100, cooldown_ms=2000),
    ),
)
```

`pagination_mode` controls who handles paging:

| Mode | Behavior |
| --- | --- |
| `none` | One `collect_once()` call, no pagination |
| `adapter` | The SDK already returns the complete result; executor calls it once |
| `framework` | `collect_once()` returns one page / chunk; the paginator loops |

For `framework` mode, the trigger key in `CollectRequest.options` selects the strategy (checked in this order):

| Option | Strategy |
| --- | --- |
| `max_lines` | Reverse-date pagination, replacing `start_date` / `end_date` |
| `chunk_months` | Calendar-month chunks, replacing `since_ts_millis` / `until_ts_millis` |
| `chunk_ms` | Day-sized millisecond chunks, replacing `start_time` / `end_time` |
| `paginate` | Forward page-number pagination, replacing `page` |
| `chunk_days` | Day-sized chunks, replacing `start_date` / `end_date` |

All chunk strategies are bounded by `max_iterations` / `max_pages` and stop after `max_empty_chunks` consecutive empty results.

---

## 6. Multiple API keys and rotation

Keyed sources (tushare, ftshare, tickflow, finzdata) share a library-level pool. A credential value containing commas is split automatically; lists work too:

```python
credentials={"token": "key1, key2, key3"}     # three keys
credentials={"api_keys": ["k1", "k2"]}        # equivalent
```

- On a rate-limit or authentication failure the pool rotates to the next key; the failed key cools down and becomes eligible again automatically — it is never permanently blacklisted.
- Rotation state lives on the adapter instance, so a resident process reuses the same pool across `collect()` calls. Cooldowns use a monotonic clock and need no external coordination.
- With a single key the legacy path is preserved: no internal rotation, and the framework retry layer handles the error.
- Customize the behavior with `KeyRotationPolicy` through `Policies`:

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

Error mapping is part of the adapter contract: FinzData maps `401` to auth error, `429` to rate limit, `5xx` to network error, and `403` to a data error that is not retried. yfinance maps `YFRateLimitError` to rate limit, missing / invalid data to data errors, and connection / timeout errors to network errors.

---

## 7. Documentation and examples

- [Development guide](docs/development-guide.md) — execution chain, adding a source, policy and key-pool internals
- [Examples](examples/README.md) — six runnable scripts that need no real SDK or network

| Example | What it shows |
| --- | --- |
| `01_custom_adapter.py` | Implementing `BaseAdapter` and collecting from an in-memory source |
| `02_fake_mode.py` | Validating a request with `fake=True` and no SDK installed |
| `03_policies.py` | Injecting retry and rate-limit policies for a flaky source |
| `04_key_rotation.py` | Splitting multiple keys and rotating on a simulated 429 |
| `05_framework_pagination.py` | Forward page-number pagination driven by `options` |
| `06_multi_source.py` | Registering several sources and reusing adapter instances |

---

## 8. Tests

```bash
uv run --extra test python -m pytest tests -q
# or: python -m pytest tests -q
```

The suite covers units, end-to-end collection, adapter behavior, executed examples, public exports and bilingual documentation.

---

## 9. License

MIT. See [LICENSE](LICENSE).
