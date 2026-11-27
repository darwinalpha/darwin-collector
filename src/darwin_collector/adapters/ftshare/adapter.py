"""FTShare adapter.

API keys are supplied by the caller via ``ensure_ready(credentials)``. The
library never reads environment variables or config files. Multiple keys are
supported by the library-level key pool (comma-separated or list credentials)
with bounded rotation and cooldown; this adapter holds no private rotation
state.

Pagination: the SDK's own ``fetch_all`` / ``get_paginated`` methods paginate
internally, so the default ``ADAPTER`` mode calls ``collect_once`` once. A
caller can opt into framework chunking by passing ``pagination_mode=FRAMEWORK``
together with ``chunk_months`` / ``chunk_days`` / ``paginate`` options.
"""

from typing import Any, Dict, Optional

import pandas as pd

from ...defaults import (
    DEFAULT_FTSHARE_BASE_URL,
    DEFAULT_FTSHARE_TIMEOUT,
)
from ...exceptions import (
    AdapterAuthError,
    AdapterDataError,
    AdapterNetworkError,
    AdapterRateLimitError,
)
from ...types import PaginationMode
from ..base import BaseAdapter

__all__ = ["FtshareAdapter"]

# HTTP 400 with this text means "no records" -> an empty page, not a failure.
_EMPTY_DATA_KEYWORDS = ("数据文件没有可用记录", "http 400")


def _is_empty_data_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(keyword in text for keyword in _EMPTY_DATA_KEYWORDS)


class FtshareAdapter(BaseAdapter):
    pagination_mode = PaginationMode.ADAPTER
    key_fields = ("api_keys", "keys", "api_key")

    def __init__(self) -> None:
        super().__init__()
        self._sdk: Optional[Any] = None
        self._base_url: str = DEFAULT_FTSHARE_BASE_URL
        self._timeout: int = DEFAULT_FTSHARE_TIMEOUT
        self._credentials: Dict[str, Any] = {}

    def get_source_name(self) -> str:
        return "ftshare"

    # ------------------------------------------------------------------
    # Auth / init
    # ------------------------------------------------------------------

    def ensure_ready(self, credentials: Optional[Dict[str, Any]] = None) -> None:
        if self._initialized:
            return

        pool = self._init_key_pool(credentials)
        if pool is None or pool.size == 0:
            raise AdapterAuthError(
                "FTShare 需要 credentials['api_keys'] 或 ['api_key']；库不读环境变量",
                source="ftshare",
            )

        try:
            import ftshare as ft  # type: ignore
        except ImportError as exc:
            raise AdapterDataError(
                "ftshare SDK 未安装，请安装 .[ftshare] extra",
                source="ftshare",
                context={"error": str(exc)},
            ) from exc

        data = dict(credentials or {})
        self._sdk = ft
        self._credentials = data
        self._base_url = data.get("base_url", DEFAULT_FTSHARE_BASE_URL)
        self._timeout = data.get("timeout", DEFAULT_FTSHARE_TIMEOUT)
        self._warm_client(self._build_client)
        self._initialized = True
        self._available = True

    def reauth(self) -> None:
        self._initialized = False
        self._reset_key_state()
        self.ensure_ready(self._credentials)

    def close(self) -> None:
        self._sdk = None
        self._credentials = {}
        self._initialized = False
        self._reset_key_state()

    def _build_client(self, key: str) -> Any:
        return self._sdk.market_api(
            api_key=key, base_url=self._base_url, timeout=self._timeout
        )

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def collect_once(self, method: str, **kwargs: Any) -> pd.DataFrame:
        if not self._initialized or self._sdk is None:
            raise AdapterAuthError("FTShare 未初始化", source="ftshare", method=method)

        cleaned = {key: value for key, value in kwargs.items() if value not in (None, "", [])}

        def invoke(key: Optional[str]) -> pd.DataFrame:
            client = self._cached_client(key, self._build_client)
            try:
                api_method = getattr(client, method)
            except AttributeError as exc:
                raise AdapterDataError(
                    f"FTShare SDK 方法不存在: {method}", source="ftshare", method=method
                ) from exc

            try:
                return self._to_dataframe(api_method(as_dataframe=True, **cleaned))
            except (AdapterAuthError, AdapterRateLimitError, AdapterNetworkError, AdapterDataError):
                raise
            except Exception as exc:
                if _is_empty_data_error(exc):
                    # Let the paginator's empty-count logic decide when to stop.
                    return pd.DataFrame()
                raise self._to_adapter_error(method, exc) from exc

        return self._run_with_keys(invoke)

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------

    def _to_adapter_error(self, method: str, exc: Exception) -> Exception:
        text = str(exc).lower()
        error_type = type(exc).__name__

        if error_type == "FtshareHTTPError" and any(
            key in text for key in ("401", "403", "unauthorized", "forbidden")
        ):
            self.mark_unavailable()
            return AdapterAuthError(f"FTShare 认证失败: {exc}", source="ftshare", method=method)

        if any(
            key in text
            for key in (
                "token", "invalid", "权限", "permission", "denied", "apikey",
                "unauthorized", "forbidden", "401", "403",
            )
        ):
            self.mark_unavailable()
            return AdapterAuthError(f"FTShare 认证失败: {exc}", source="ftshare", method=method)

        if error_type == "FtshareHTTPError" and "429" in text:
            return AdapterRateLimitError(f"FTShare 限流: {exc}", source="ftshare", method=method)

        if any(key in text for key in ("频率", "限流", "rate", "limit", "too many", "频繁")):
            return AdapterRateLimitError(f"FTShare 限流: {exc}", source="ftshare", method=method)

        if error_type == "FtshareDecodeError":
            return AdapterNetworkError(
                f"FTShare 响应解析失败: {exc}", source="ftshare", method=method
            )

        if any(key in text for key in ("timeout", "超时", "connection", "连接", "network")):
            return AdapterNetworkError(f"FTShare 网络异常: {exc}", source="ftshare", method=method)

        if error_type == "FtshareAPIError":
            return AdapterDataError(
                f"FTShare 业务错误 ({method}): {exc}", source="ftshare", method=method
            )
        return AdapterDataError(f"FTShare 数据异常 ({method}): {exc}", source="ftshare", method=method)
