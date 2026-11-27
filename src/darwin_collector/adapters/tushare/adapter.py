"""Tushare adapter.

Credentials are passed in by the caller via ``ensure_ready(credentials)`` — the
library never reads environment variables or config files. Authentication is
lazy and the instance is reusable across collections.

A token value containing commas is split into multiple keys by the base class;
rate-limit / auth failures rotate to the next key.
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

__all__ = ["TushareAdapter"]


class TushareAdapter(BaseAdapter):
    pagination_mode = PaginationMode.FRAMEWORK
    key_fields = ("token",)

    def __init__(self) -> None:
        super().__init__()
        self._sdk: Optional[Any] = None
        self._pro: Optional[Any] = None
        self._token: Optional[str] = None

    def get_source_name(self) -> str:
        return "tushare"

    def ensure_ready(self, credentials: Optional[Dict[str, Any]] = None) -> None:
        if self._initialized:
            return

        pool = self._init_key_pool(credentials)
        if pool is None or pool.size == 0:
            raise AdapterAuthError(
                "Tushare 需要 credentials['token']；库不读环境变量",
                source="tushare",
            )

        try:
            import tushare as ts  # type: ignore
        except ImportError as exc:
            raise AdapterDataError(
                "tushare SDK 未安装，请安装 .[tushare] extra",
                source="tushare",
                context={"error": str(exc)},
            ) from exc

        self._sdk = ts
        self._token = (credentials or {}).get("token")
        self._warm_client(lambda key: self._sdk.pro_api(key))
        self._initialized = True
        self._available = True

    def reauth(self) -> None:
        self._initialized = False
        self._reset_key_state()
        if self._token:
            self.ensure_ready({"token": self._token})

    def close(self) -> None:
        self._pro = None
        self._sdk = None
        self._token = None
        self._initialized = False
        self._reset_key_state()

    def collect_once(self, method: str, **kwargs: Any) -> pd.DataFrame:
        if not self._initialized or self._sdk is None:
            raise AdapterAuthError("Tushare 未初始化", source="tushare", method=method)

        cleaned = {k: v for k, v in kwargs.items() if v not in (None, "", [])}

        def invoke(key: Optional[str]) -> pd.DataFrame:
            self._pro = self._cached_client(key, lambda k: self._sdk.pro_api(k))
            try:
                api_method = getattr(self._pro, method)
            except AttributeError as exc:
                raise AdapterDataError(
                    f"Tushare API 方法不存在: {method}",
                    source="tushare",
                    method=method,
                ) from exc
            try:
                return self._to_dataframe(api_method(**cleaned))
            except Exception as exc:
                raise self._to_adapter_error(method, exc) from exc

        return self._run_with_keys(invoke)

    def _to_adapter_error(self, method: str, exc: Exception) -> Exception:
        text = str(exc).lower()
        if any(k in text for k in ["token", "invalid", "权限", "permission", "denied"]):
            self.mark_unavailable()
            return AdapterAuthError(
                f"Tushare 认证失败: {exc}", source="tushare", method=method
            )
        if any(k in text for k in ["频率", "限流", "rate", "limit", "too many", "频繁"]):
            return AdapterRateLimitError(
                f"Tushare 限流: {exc}", source="tushare", method=method
            )
        if any(k in text for k in ["timeout", "超时", "connection", "连接", "network"]):
            return AdapterNetworkError(
                f"Tushare 网络异常: {exc}", source="tushare", method=method
            )
        return AdapterDataError(
            f"Tushare 数据异常 ({method}): {exc}", source="tushare", method=method
        )
