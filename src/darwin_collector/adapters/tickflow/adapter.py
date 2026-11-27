"""Tickflow adapter.

The token is supplied by the caller via ``ensure_ready(credentials)`` — the
library never reads environment variables. Method paths may be dotted
(``klines.get``) and ``symbol`` is passed as a positional argument.

Pagination is framework-driven: pass ``chunk_ms`` (or ``chunk_days``) in
options together with ``start_time`` / ``end_time`` millisecond parameters.
Every chunk calls ``collect_once`` once; empty chunks stop early.
"""

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

__all__ = ["TickflowAdapter"]


class TickflowAdapter(BaseAdapter):
    pagination_mode = PaginationMode.FRAMEWORK
    key_fields = ("token",)

    def __init__(self) -> None:
        super().__init__()
        self._client: Optional[Any] = None
        self._sdk: Optional[Any] = None
        self._token: Optional[str] = None

    def get_source_name(self) -> str:
        return "tickflow"

    def ensure_ready(self, credentials: Optional[Dict[str, Any]] = None) -> None:
        if self._initialized:
            return

        pool = self._init_key_pool(credentials)
        if pool is None or pool.size == 0:
            raise AdapterAuthError(
                "Tickflow 需要 credentials['token']；库不读环境变量", source="tickflow"
            )

        try:
            from tickflow import TickFlow  # type: ignore
        except ImportError as exc:
            raise AdapterDataError(
                "tickflow SDK 未安装，请安装 .[tickflow] extra",
                source="tickflow",
                context={"error": str(exc)},
            ) from exc

        self._sdk = TickFlow
        self._token = (credentials or {}).get("token")
        self._warm_client(self._build_client)
        self._initialized = True
        self._available = True

    def _build_client(self, key: str) -> Any:
        return self._sdk(api_key=key)

    def reauth(self) -> None:
        self._initialized = False
        self._sdk = None
        self._reset_key_state()
        if self._token:
            self.ensure_ready({"token": self._token})

    def close(self) -> None:
        self._client = None
        self._sdk = None
        self._token = None
        self._initialized = False
        self._reset_key_state()

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def _resolve_method(self, method: str) -> Any:
        obj = self._client
        for part in method.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                break
        if obj is None or not callable(obj):
            raise AdapterDataError(
                f"Tickflow API 方法不存在: {method}", source="tickflow", method=method
            )
        return obj

    def collect_once(self, method: str, **kwargs: Any) -> pd.DataFrame:
        if not self._initialized or self._sdk is None:
            raise AdapterAuthError("Tickflow 未初始化", source="tickflow", method=method)

        cleaned = {key: value for key, value in kwargs.items() if value not in (None, "", [])}
        symbol = cleaned.pop("symbol", None)

        def invoke(key: Optional[str]) -> pd.DataFrame:
            self._client = self._cached_client(key, self._build_client)
            api_method = self._resolve_method(method)
            try:
                if symbol is not None:
                    result = api_method(symbol, **cleaned)
                else:
                    result = api_method(**cleaned)
                return self._to_dataframe(result)
            except Exception as exc:
                raise self._to_adapter_error(method, exc) from exc

        return self._run_with_keys(invoke)

    # ------------------------------------------------------------------
    # Result conversion
    # ------------------------------------------------------------------

    def _to_dataframe(self, data: Any) -> pd.DataFrame:
        if data is None:
            return pd.DataFrame()
        if isinstance(data, pd.DataFrame):
            return data
        if isinstance(data, dict):
            # universes.get -> {'id': ..., 'name': ..., 'symbols': [...]}
            if "symbols" in data and isinstance(data["symbols"], list):
                return pd.DataFrame({"symbol": data["symbols"]})
            if "data" in data:
                payload = data["data"]
                if isinstance(payload, pd.DataFrame):
                    return payload
                if isinstance(payload, list):
                    return pd.DataFrame(payload)
            return pd.DataFrame(data)
        if isinstance(data, list):
            return pd.DataFrame(data)
        try:
            return pd.DataFrame(data)
        except Exception:
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------

    def _to_adapter_error(self, method: str, exc: Exception) -> Exception:
        text = str(exc).lower()
        if any(
            key in text
            for key in ("token", "invalid", "权限", "permission", "拒绝", "denied", "auth", "api_key")
        ):
            self.mark_unavailable()
            return AdapterAuthError(f"Tickflow 认证失败: {exc}", source="tickflow", method=method)
        if any(
            key in text
            for key in ("频率", "限流", "rate", "limit", "too many", "频繁", "throttle")
        ):
            self.mark_unavailable()
            return AdapterRateLimitError(f"Tickflow 限流: {exc}", source="tickflow", method=method)
        if any(
            key in text
            for key in ("timeout", "超时", "connection", "连接", "network", "网络")
        ):
            return AdapterNetworkError(f"Tickflow 网络异常: {exc}", source="tickflow", method=method)
        return AdapterDataError(f"Tickflow 数据异常: {exc}", source="tickflow", method=method)
