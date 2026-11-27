"""yfinance adapter.

yfinance has no API key or login step. ``ensure_ready`` only imports the SDK
and optionally keeps a caller-supplied ``session``; the library never reads
credentials from the environment or from config files.

The SDK returns complete datasets for a request, so the default pagination mode
is ``NONE``. Callers can opt into framework chunking with
``Policies(pagination_mode=FRAMEWORK)`` and ``chunk_days`` / ``chunk_months`` /
``max_lines`` options — framework date keys are mapped to yfinance's
``start`` / ``end`` parameters.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd

from ...exceptions import (
    AdapterAuthError,
    AdapterDataError,
    AdapterNetworkError,
    AdapterRateLimitError,
)
from ...types import PaginationMode
from ..base import BaseAdapter

__all__ = ["YfinanceAdapter"]

# Ticker methods / properties that return a DataFrame, Series, dict or list.
# ``get_*`` aliases are accepted and normalized to the bare name.
_TICKER_METHODS = frozenset(
    {
        "history",
        "info",
        "fast_info",
        "history_metadata",
        "actions",
        "dividends",
        "splits",
        "financials",
        "income_stmt",
        "incomestmt",
        "balance_sheet",
        "balancesheet",
        "cash_flow",
        "cashflow",
        "quarterly_financials",
        "quarterly_income_stmt",
        "quarterly_incomestmt",
        "quarterly_balance_sheet",
        "quarterly_balancesheet",
        "quarterly_cash_flow",
        "quarterly_cashflow",
        "ttm_financials",
        "ttm_income_stmt",
        "ttm_incomestmt",
        "ttm_cash_flow",
        "ttm_cashflow",
        "earnings",
        "quarterly_earnings",
        "earnings_dates",
        "calendar",
        "analyst_price_targets",
        "earnings_estimate",
        "revenue_estimate",
        "eps_trend",
        "eps_revisions",
        "growth_estimates",
        "recommendations",
        "recommendations_summary",
        "upgrades_downgrades",
        "institutional_holders",
        "major_holders",
        "mutualfund_holders",
        "insider_purchases",
        "insider_roster_holders",
        "insider_transactions",
        "sustainability",
        "sec_filings",
        "news",
        "option_chain",
        "options",
        "isin",
        "shares",
    }
)


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
    """Map framework chunk parameters onto yfinance's ``start`` / ``end``."""
    out = dict(kwargs)

    if "start_date" in out:
        out.setdefault("start", out.pop("start_date"))
    if "end_date" in out:
        out.setdefault("end", out.pop("end_date"))

    if "since_ts_millis" in out:
        converted = _millis_to_iso(out.pop("since_ts_millis"))
        if converted is not None:
            out.setdefault("start", converted)
    if "until_ts_millis" in out:
        converted = _millis_to_iso(out.pop("until_ts_millis"))
        if converted is not None:
            out.setdefault("end", converted)

    return out


class YfinanceAdapter(BaseAdapter):
    """Adapter for the community ``yfinance`` SDK (Yahoo Finance data)."""

    pagination_mode = PaginationMode.NONE

    def __init__(self) -> None:
        super().__init__()
        self._sdk: Any = None
        self._credentials: Dict[str, Any] = {}
        self._session: Any = None

    def get_source_name(self) -> str:
        return "yfinance"

    # ------------------------------------------------------------------
    # Lifecycle (no login)
    # ------------------------------------------------------------------

    def ensure_ready(self, credentials: Optional[Dict[str, Any]] = None) -> None:
        if self._initialized:
            return

        try:
            import yfinance as yf  # type: ignore
        except ImportError as exc:
            raise AdapterDataError(
                "yfinance SDK 未安装，请安装 .[yfinance] extra",
                source="yfinance",
                context={"error": str(exc)},
            ) from exc

        data = dict(credentials or {})
        self._sdk = yf
        self._credentials = data
        self._session = data.get("session")
        self._initialized = True
        self._available = True

    def reauth(self) -> None:
        credentials = dict(self._credentials)
        self._initialized = False
        self._sdk = None
        self._session = None
        self.ensure_ready(credentials)

    def close(self) -> None:
        self._sdk = None
        self._credentials = {}
        self._session = None
        self._initialized = False

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def collect_once(self, method: str, **kwargs: Any) -> pd.DataFrame:
        if not self._initialized or self._sdk is None:
            raise AdapterDataError(
                "yfinance 未初始化", source="yfinance", method=method
            )

        cleaned = _clean_kwargs(kwargs)
        try:
            return self._dispatch(method, cleaned)
        except (
            AdapterAuthError,
            AdapterRateLimitError,
            AdapterNetworkError,
            AdapterDataError,
        ):
            raise
        except Exception as exc:
            raise self._to_adapter_error(method, exc) from exc

    def _dispatch(self, method: str, kwargs: Dict[str, Any]) -> pd.DataFrame:
        key = str(method).strip().lower().replace("-", "_").replace(".", "_")
        if key.startswith("ticker_"):
            key = key[len("ticker_") :]
        elif key.startswith("get_"):
            key = key[len("get_") :]

        session = kwargs.pop("session", self._session)
        sdk_kwargs = _normalize_sdk_kwargs(kwargs)

        if key == "download":
            tickers = (
                sdk_kwargs.pop("tickers", None)
                or sdk_kwargs.pop("symbols", None)
                or sdk_kwargs.pop("symbol", None)
            )
            if not tickers:
                raise AdapterDataError(
                    "yfinance download 需要 tickers/symbols 参数",
                    source="yfinance",
                    method=method,
                )
            if session is not None:
                sdk_kwargs["session"] = session
            result = self._sdk.download(tickers, **sdk_kwargs)
            return self._to_dataframe(result)

        if key not in _TICKER_METHODS:
            raise AdapterDataError(
                f"yfinance 不支持的方法: {method}",
                source="yfinance",
                method=method,
            )

        symbol = sdk_kwargs.pop("symbol", None) or sdk_kwargs.pop("ticker", None)
        if not symbol:
            raise AdapterDataError(
                f"yfinance {key} 需要 symbol/ticker 参数",
                source="yfinance",
                method=method,
            )

        ticker = self._sdk.Ticker(symbol, session=session)
        target = getattr(ticker, key)
        result = target(**sdk_kwargs) if callable(target) else target
        return self._to_dataframe(result)

    def _to_dataframe(self, data: Any) -> pd.DataFrame:
        if data is None:
            return pd.DataFrame()
        if isinstance(data, pd.DataFrame):
            return data
        if isinstance(data, pd.Series):
            return data.to_frame()
        if isinstance(data, dict) or hasattr(data, "items"):
            try:
                return pd.DataFrame([dict(data.items())])
            except Exception:
                return pd.DataFrame()
        if isinstance(data, (list, tuple)):
            try:
                return pd.DataFrame(list(data))
            except Exception:
                return pd.DataFrame()
        try:
            return pd.DataFrame([{"value": data}])
        except Exception:
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------

    def _to_adapter_error(self, method: str, exc: Exception) -> Exception:
        name = type(exc).__name__
        text = str(exc).lower()
        context = {"error_type": name, "detail": str(exc)}

        if (
            name == "YFRateLimitError"
            or "too many requests" in text
            or "rate limited" in text
            or "429" in text
        ):
            return AdapterRateLimitError(
                f"yfinance 限流: {exc}",
                source="yfinance",
                method=method,
                context=context,
            )

        if name in {
            "YFPricesMissingError",
            "YFTickerMissingError",
            "YFTzMissingError",
            "YFDataException",
            "YFInvalidPeriodError",
            "YFNotImplementedError",
            "YFEarningsDateMissing",
        }:
            return AdapterDataError(
                f"yfinance 数据异常: {exc}",
                source="yfinance",
                method=method,
                context=context,
            )

        if name in {
            "Timeout",
            "ConnectTimeout",
            "ReadTimeout",
            "ConnectionError",
            "HTTPError",
            "RequestException",
            "SSLError",
            "CurlError",
        }:
            return AdapterNetworkError(
                f"yfinance 网络异常: {exc}",
                source="yfinance",
                method=method,
                context=context,
            )

        if any(key in text for key in ("401", "unauthorized")):
            return AdapterAuthError(
                f"yfinance 会话认证失败: {exc}",
                source="yfinance",
                method=method,
                context=context,
            )
        if any(
            key in text
            for key in ("timeout", "timed out", "connection", "network", "dns")
        ):
            return AdapterNetworkError(
                f"yfinance 网络异常: {exc}",
                source="yfinance",
                method=method,
                context=context,
            )
        return AdapterDataError(
            f"yfinance 数据异常 ({method}): {exc}",
            source="yfinance",
            method=method,
            context=context,
        )
