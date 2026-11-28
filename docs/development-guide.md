# darwin-collector development guide

[English](development-guide.md) · [简体中文](development-guide.cn.md)

Version: 0.1.1 · Python >= 3.10

---

## 1. Scope

`darwin-collector` performs **collection only**: register an adapter, initialize / log in, call the SDK, apply policies, and return a `CollectResult`. It never reads config, writes files, cleans data, or routes across sources.

The only hard dependency is `pandas`. Data-source SDKs are optional extras and are imported lazily inside the adapter methods that need them.

---

## 2. The execution chain of one collection

```text
AdapterManager.collect(request)
  -> resolve_backend(source)          # always direct for now; worker branch reserved
  -> get_adapter(source)              # registry lookup; instance is cached
  -> Executor.execute(adapter, request)
      -> adapter.configure(policies)
      -> adapter.ensure_ready(credentials)
      -> select Paginator by pagination_mode
      -> call_once = retry(RateLimit(adapter.collect_once))
      -> paginate(...) or single call
      -> CollectResult
```

`request.fake=True` short-circuits `call_once`: no SDK call is made and an empty DataFrame is returned. `ensure_ready()` still runs, so a fake request also exercises initialization.

---

## 3. Adding a data source

1. Create `src/darwin_collector/adapters/<source>/` with `adapter.py` and `__init__.py`.
2. Subclass `BaseAdapter` and implement `get_source_name()` and `collect_once(method, **kwargs)`.
3. In `ensure_ready(credentials)`, initialize the SDK with the **passed-in** credentials. Never read environment variables or config files.
4. Declare `pagination_mode`:
   - `NONE`: a single call;
   - `FRAMEWORK`: `collect_once()` returns one page; the Paginator loops (tushare belongs here);
   - `ADAPTER`: the SDK returns the complete result and the framework does not paginate.
   If the source needs an API key, declare `key_fields = ("token",)` in priority order.
5. Map SDK exceptions to `AdapterAuthError`, `AdapterRateLimitError`, `AdapterNetworkError` or `AdapterDataError`.
6. Add behavior-lock tests (fake mode) at `tests/unit/adapters/test_<source>.py`.
7. The caller registers the class: `manager.register("source", SourceAdapter)`.

`collect_once()` must return a DataFrame. `_to_dataframe()` accepts a DataFrame, a list of records or `None`, but an explicit DataFrame is preferred.

---

## 4. Policy injection

The caller passes `Policies(retry=..., rate_limit=..., paginator=..., pagination_mode=..., key_rotation=...)` in `CollectRequest`. Unset fields use the constants in `defaults.py`. The library reads no global configuration.

- `RetryPolicy`: retries only rate-limit / network errors. An authentication error calls `reauth()` once, then raises `AdapterAuthError` if it still fails.
- `RateLimitPolicy`: `before_call()` spaces out SDK calls; `on_rate_limit()` controls cooldown. The current Executor uses `before_call`, while retry waiting provides the effective cooldown.
- `KeyRotationPolicy`: controls multi-key rotation — `cooldown_seconds` / `auth_cooldown_seconds` set the cooldown for rate-limit and auth failures, `max_rotations` bounds rotations per call, and `rotate_on_auth` / `rotate_on_rate_limit` decide which errors trigger rotation.
- `Paginator`: in `framework` mode, trigger keys in `options` select a strategy, checked in this order:
  - `max_lines`: reverse-date pagination (tushare);
  - `chunk_months`: calendar-month chunks replacing `since_ts_millis` / `until_ts_millis` (optional for ftshare);
  - `chunk_ms`: day-sized millisecond chunks replacing `start_time` / `end_time` (tickflow);
  - `paginate`: forward page-number pagination replacing `page`;
  - `chunk_days`: day-sized chunks replacing `start_date` / `end_date`.

  Every chunk strategy is bounded by `max_iterations` / `max_pages` and stops after `max_empty_chunks` consecutive empty results. The paginator itself never sleeps: spacing is the `RateLimitPolicy`'s job, so chunk helpers receive `interval_ms=0` to avoid double waiting.

---

## 5. Multiple API keys and rotation

Rotation is a library capability, never implemented per adapter. A keyed adapter only needs to:

1. Declare `key_fields` (credential fields holding its keys, in priority order);
2. Call `self._init_key_pool(credentials)` in `ensure_ready()`; raise `AdapterAuthError` when the pool is empty, otherwise warm the first client with `self._warm_client(factory)`;
3. Write the single SDK call as a `def invoke(key): ...` closure, fetch the client for that key with `self._cached_client(key, factory)`, and return `self._run_with_keys(invoke)`;
4. Clear cached clients and cooldowns with `self._reset_key_state()` in `reauth()` / `close()`.

Library behavior:

- Comma-separated credential values (strings or list elements) are split into keys;
- Rate-limit and auth failures rotate to the next key; the failed key cools down and becomes eligible again automatically;
- With a single key there is no internal rotation, preserving the legacy behavior delegated to the framework retry layer;
- Rotation state lives on the adapter instance, so a resident worker keeps cooldowns across `collect()` calls with no shared storage;
- Customize via `Policies(key_rotation=...)`; `Executor.execute()` calls `adapter.configure(policies)` before `ensure_ready()`.

---

## 6. Sessions and worker

Adapter instances are cached by `AdapterManager` and reusable across `collect()` calls. The host calls `close()` at shutdown. `resolve_backend(source)` is the only backend selection point; it currently always returns `direct`, so switching to a worker later requires no changes in callers or adapters.

Stateful sources follow this contract so a reused worker does not log in for every request:

- `ensure_ready()`: idempotent initialization; baostock logs in here, ohlcvault connects here;
- `close()`: logout / release connections at host shutdown;
- `reauth()`: rebuild the session after an auth error (baostock logs in again; ftshare / tickflow / finzdata / yfinance rebuild their SDK reference or client; tushare resets its token). Keyed adapters also clear cached clients and cooldowns.

---

## 7. FinzData method mapping

FinzData needs only an API key and has no login round trip. `ensure_ready()` builds a `finzdata.Client` from the passed-in `api_key` (or `token`); `FINZDATA_API_KEY` is never read.

Supported methods fall into three groups:

- `Client` dataset methods called by their original names: `prices`, `minutes`, `cot`, `futures`, `macro`, `gex`, `fundamentals`, `valuation`, `datasets`, `me`, and others. The full allow-list is in `adapters/finzdata/adapter.py`;
- yfinance-style aliases: `history` / `ticker_history` map to `Ticker(symbol).history()`, `download` maps to `finzdata.download()`;
- `Ticker` helpers: `ticker.info`, `ticker.actions`, `ticker.facts`, `ticker.dividends`, `ticker.splits`.

Two conventions:

1. `start_date` / `end_date` and `since_ts_millis` / `until_ts_millis` are converted to the SDK's `start` / `end`, so optional `FRAMEWORK` chunking reuses the existing Paginator;
2. `FinzError.status` is classified semantically: `401` auth (key marked unusable), `403` plan excludes the dataset (data error, no retry), `429` rate limit, `5xx` network error. `403` is deliberately not treated as auth failure because the same key may still access other datasets.

---

## 8. yfinance method mapping

yfinance has no API key or login round trip. `ensure_ready()` only imports the SDK and keeps an optional caller-supplied `session` (`credentials={"session": ...}`). No environment variable is read.

Supported methods fall into three groups:

- `download` maps to `yf.download()`; `tickers`, `symbols` and `symbol` all work as symbol arguments;
- `history` / `ticker_history` map to `Ticker(symbol).history()`;
- A Ticker allow-list including `info`, `fast_info`, `financials`, `income_stmt`, `balance_sheet`, `cash_flow`, `earnings`, `earnings_dates`, `actions`, `dividends`, `splits`, `recommendations`, `institutional_holders`, `option_chain`, `news`; `ticker.<name>`, `<name>` and `get_<name>` spellings are all accepted.

Two conventions:

1. `start_date` / `end_date` and `since_ts_millis` / `until_ts_millis` are converted to `start` / `end`, so optional `FRAMEWORK` chunking reuses the existing Paginator; reverse-date pagination based on an index column needs `options={"date_field": "Date"}` from the caller;
2. `YFRateLimitError` maps to rate limit; `YFPricesMissingError` / `YFTickerMissingError` / `YFInvalidPeriodError` / `YFDataException` map to data errors; connection / timeout / DNS errors map to network errors. An empty DataFrame is a normal result, not an exception.

---

## 9. Prohibited dependencies

- Do not import `darwin_config`, `darwin_logger`, writer, cleaner or loader code;
- Do not read `adapter.json`, `adapter_clean.json` or `mapping.json`;
- Do not implement deduplication, persistence or cross-source failover inside the library.
