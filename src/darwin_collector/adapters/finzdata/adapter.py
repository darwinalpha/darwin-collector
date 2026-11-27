"""FinzData adapter.

Credentials are supplied by the caller via ``ensure_ready(credentials)``. The
library never reads ``FINZDATA_API_KEY`` or any other environment variable; if
the key is missing, collection fails with ``AdapterAuthError``.

The SDK client already returns complete datasets, so the default pagination
mode is ``NONE``. Callers can opt into framework chunking with
``Policies(pagination_mode=FRAMEWORK)`` and ``chunk_days`` / ``chunk_months``
options; ``start_date`` / ``end_date`` and millisecond chunk keys are mapped to
the SDK's ``start`` / ``end`` parameters.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd

from ...defaults import DEFAULT_FINZDATA_TIMEOUT
from ...exceptions import (
    AdapterAuthError,
    AdapterDataError,
    AdapterNetworkError,
    AdapterRateLimitError,
)
from ...types import PaginationMode
from ..base import BaseAdapter

__all__ = ["FinzdataAdapter"]

# DataFrame-returning methods exposed by finzdata.Client (v0.1.19).
_CLIENT_METHODS = frozenset(
    {
        "datasets",
        "futures",
        "futures_roots",
        "futures_contracts",
        "futures_rolls",
        "cot",
        "cot_markets",
        "prices",
        "minutes",
        "actions",
        "statements",
        "fund_holders",
        "fund_holdings",
        "earnings_dates",
        "valuation",
        "short_interest",
        "insider_transactions",
        "profile",
        "fundamentals",
        "macro",
        "macro_series",
        "macro_calendar",
        "licensed",
        "licensed_catalog",
        "vix_futures",
        "model",
        "liquidity",
        "liquidity_catalog",
        "tic",
        "institutional_ownership",
        "holders",
        "manager_holdings",
        "managers",
        "gex",
        "gex_strikes",
        "gex_tickers",
        "me",
    }
)

# Ticker helpers mirrored from yfinance. ``info`` returns a dict and is
# converted to a single-row DataFrame by ``_to_dataframe``.
_TICKER_ATTRS = frozenset({"history", "facts", "actions", "info", "dividends", "splits"})

_METHOD_ALIASES = {
    "history": "ticker.history",
    "ticker_history": "ticker.history",
    "tickerhistory": "ticker.history",
    "ticker_download": "download",
}


def _clean_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Drop empty markers while preserving valid false-y values (0, False)."""
    return {
        key: value
        for key, value in kwargs.items()
        if value is not None and value != "" and value != []
    }


def _millis_to_iso(value: Any) -> Optional[str]:
    try:
        moment = datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    return moment.date().isoformat()


def _normalize_sdk_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Map framework chunk parameters onto the SDK's ``start`` / ``end``."""
    out = dict(kwargs)

    if "start_date" in out:
        value = out.pop("start_date")
        out.setdefault("start", value)
    if "end_date" in out:
        value = out.pop("end_date")
        out.setdefault("end", value)

    if "since_ts_millis" in out:
        value = out.pop("since_ts_millis")
        converted = _millis_to_iso(value)
        if converted is not None:
            out.setdefault("start", converted)
    if "until_ts_millis" in out:
        value = out.pop("until_ts_millis")
        converted = _millis_to_iso(value)
        if converted is not None:
            out.setdefault("end", converted)

    return out


class FinzdataAdapter(BaseAdapter):
    """Adapter for the official ``finzdata`` Python client."""

    pagination_mode = PaginationMode.NONE
    key_fields = ("api_key", "token")

    def __init__(self) -> None:
        super().__init__()
        self._sdk: Any = None
        self._client: Any = None
        self._credentials: Dict[str, Any] = {}

    def get_source_name(self) -> str:
        return "finzdata"

    # ------------------------------------------------------------------
    # Auth / lifecycle
    # ------------------------------------------------------------------

    def ensure_ready(self, credentials: Optional[Dict[str, Any]] = None) -> None:
        if self._initialized:
            return

        pool = self._init_key_pool(credentials)
        if pool is None or pool.size == 0:
            raise AdapterAuthError(
                "FinzData 需要 credentials['api_key']；库不读环境变量",
                source="finzdata",
            )

        try:
            import finzdata as fz  # type: ignore
        except ImportError as exc:
            raise AdapterDataError(
                "finzdata SDK 未安装，请安装 .[finzdata] extra",
                source="finzdata",
                context={"error": str(exc)},
            ) from exc

        self._sdk = fz
        self._credentials = dict(credentials or {})
        self._warm_client(self._build_client)
        self._initialized = True
        self._available = True

    def _build_client(self, key: str) -> Any:
        return self._sdk.Client(
            api_key=key,
            base_url=self._credentials.get("base_url"),
            timeout=self._credentials.get("timeout", DEFAULT_FINZDATA_TIMEOUT),
        )

    def reauth(self) -> None:
        credentials = dict(self._credentials)
        self._initialized = False
        self._sdk = None
        self._reset_key_state()
        self.ensure_ready(credentials)

    def close(self) -> None:
        self._client = None
        self._sdk = None
        self._credentials = {}
        self._initialized = False
        self._reset_key_state()

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def collect_once(self, method: str, **kwargs: Any) -> pd.DataFrame:
        if not self._initialized or self._sdk is None:
            raise AdapterAuthError(
                "FinzData 未初始化", source="finzdata", method=method
            )

        cleaned = _clean_kwargs(kwargs)

        def invoke(key: Optional[str]) -> pd.DataFrame:
            self._client = self._cached_client(key, self._build_client)
            try:
                return self._dispatch(method, cleaned)
            except (AdapterAuthError, AdapterRateLimitError, AdapterNetworkError, AdapterDataError):
                raise
            except Exception as exc:
                raise self._to_adapter_error(method, exc) from exc

        return self._run_with_keys(invoke)

    def _dispatch(self, method: str, kwargs: Dict[str, Any]) -> pd.DataFrame:
        key = str(method).strip().lower().replace("-", "_")
        key = _METHOD_ALIASES.get(key, key)
        sdk = self._sdk

        if key == "download":
            tickers = (
                kwargs.pop("tickers", None)
                or kwargs.pop("symbols", None)
                or kwargs.pop("symbol", None)
            )
            if not tickers:
                raise AdapterDataError(
                    "FinzData download 需要 tickers/symbols 参数",
                    source="finzdata",
                    method=method,
                )
            result = sdk.download(tickers, client=self._client, **kwargs)
            return self._to_dataframe(result)

        if key == "ticker.history" or key.startswith("ticker."):
            attr = "history" if key == "ticker.history" else key.split(".", 1)[1]
            if attr not in _TICKER_ATTRS:
                raise AdapterDataError(
                    f"FinzData Ticker 不支持的方法: {attr}",
                    source="finzdata",
                    method=method,
                )
            symbol = kwargs.pop("symbol", None) or kwargs.pop("ticker", None)
            if not symbol:
                raise AdapterDataError(
                    f"FinzData Ticker.{attr} 需要 symbol/ticker 参数",
                    source="finzdata",
                    method=method,
                )
            ticker = sdk.Ticker(symbol, client=self._client)
            if attr == "history":
                result = ticker.history(**_normalize_sdk_kwargs(kwargs))
            elif attr == "facts":
                result = ticker.facts(**kwargs)
            else:
                result = getattr(ticker, attr)
            return self._to_dataframe(result)

        client_method = key.replace(".", "_")
        if client_method not in _CLIENT_METHODS:
            raise AdapterDataError(
                f"FinzData 不支持的方法: {method}",
                source="finzdata",
                method=method,
            )

        call_kwargs = _normalize_sdk_kwargs(kwargs)
        result = getattr(self._client, client_method)(**call_kwargs)
        return self._to_dataframe(result)

    def _to_dataframe(self, data: Any) -> pd.DataFrame:
        if isinstance(data, pd.Series):
            return data.to_frame()
        if isinstance(data, dict):
            try:
                return pd.DataFrame([data])
            except Exception:
                return pd.DataFrame()
        return super()._to_dataframe(data)

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------

    def _to_adapter_error(self, method: str, exc: Exception) -> Exception:
        status = getattr(exc, "status", None)
        try:
            status_code = int(status) if status is not None else None
        except (TypeError, ValueError):
            status_code = None
        detail = getattr(exc, "detail", None) or str(exc)
        context = {"status": status_code, "detail": str(detail)}

        if status_code == 401:
            self.mark_unavailable()
            return AdapterAuthError(
                f"FinzData 认证失败: {detail}",
                source="finzdata",
                method=method,
                context=context,
            )
        # 403 means the API key is valid but the plan excludes this dataset.
        # It is deterministic, so do not retry or mark the source unavailable.
        if status_code == 403:
            return AdapterDataError(
                f"FinzData 套餐无权访问: {detail}",
                source="finzdata",
                method=method,
                context=context,
            )
        if status_code == 429:
            return AdapterRateLimitError(
                f"FinzData 限流: {detail}",
                source="finzdata",
                method=method,
                context=context,
            )
        if status_code is not None and status_code >= 500:
            return AdapterNetworkError(
                f"FinzData 服务端错误: {detail}",
                source="finzdata",
                method=method,
                context=context,
            )

        error_type = type(exc).__name__
        text = str(exc).lower()
        if error_type in {
            "TimeoutException",
            "ConnectError",
            "ReadError",
            "WriteError",
            "NetworkError",
            "HTTPError",
        }:
            return AdapterNetworkError(
                f"FinzData 网络异常: {exc}",
                source="finzdata",
                method=method,
                context=context,
            )
        if any(key in text for key in ("401", "unauthorized", "invalid api key", "bad key")):
            self.mark_unavailable()
            return AdapterAuthError(
                f"FinzData 认证失败: {exc}",
                source="finzdata",
                method=method,
                context=context,
            )
        if any(key in text for key in ("429", "rate limit", "too many requests", "daily call limit")):
            return AdapterRateLimitError(
                f"FinzData 限流: {exc}",
                source="finzdata",
                method=method,
                context=context,
            )
        if any(key in text for key in ("timeout", "connection", "network", "timed out")):
            return AdapterNetworkError(
                f"FinzData 网络异常: {exc}",
                source="finzdata",
                method=method,
                context=context,
            )
        return AdapterDataError(
            f"FinzData 数据异常 ({method}): {exc}",
            source="finzdata",
            method=method,
            context=context,
        )
