"""OHLCVault adapter.

``connect()`` is called once in ``ensure_ready`` and produces a state object;
the instance is reusable across collections. Keys in kwargs prefixed with
``_`` are passed as positional arguments in insertion order; other keys are
keyword arguments. Stdout produced by the SDK is suppressed locally.

Field mapping / index conversion / type changes belong to the clean layer —
the only exception is preserving a named index via ``reset_index()`` when a
``Bars.to_pandas()`` result is converted to a DataFrame.
"""

import contextlib
import io
from typing import Any, Dict, List, Optional

import pandas as pd

from ...exceptions import (
    AdapterAuthError,
    AdapterDataError,
    AdapterNetworkError,
    AdapterRateLimitError,
)
from ...types import PaginationMode
from ..base import BaseAdapter

__all__ = ["OhlcvaultAdapter"]


class OhlcvaultAdapter(BaseAdapter):
    pagination_mode = PaginationMode.NONE

    def __init__(self) -> None:
        super().__init__()
        self._ov: Optional[Any] = None
        self._state: Optional[Any] = None

    def get_source_name(self) -> str:
        return "ohlcvault"

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def ensure_ready(self, credentials: Optional[Dict[str, Any]] = None) -> None:
        if self._initialized:
            return

        try:
            import ohlcvault as ov  # type: ignore
        except ImportError as exc:
            raise AdapterDataError(
                "ohlcvault SDK 未安装，请安装 .[ohlcvault] extra",
                source="ohlcvault",
                context={"error": str(exc)},
            ) from exc

        data = credentials or {}
        connect_kwargs: Dict[str, Any] = {}
        if data.get("mirrors"):
            connect_kwargs["mirrors"] = data["mirrors"]
        if data.get("snapshot"):
            connect_kwargs["snapshot"] = data["snapshot"]

        try:
            self._ov = ov
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                self._state = ov.connect(**connect_kwargs)
            self._initialized = True
            self._available = True
        except Exception as exc:
            raise self._to_adapter_error("connect", exc) from exc

    def reauth(self) -> None:
        self._initialized = False
        self._state = None
        self.ensure_ready()

    def close(self) -> None:
        self._state = None
        self._ov = None
        self._initialized = False

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def collect_once(self, method: str, **kwargs: Any) -> pd.DataFrame:
        if not self._initialized or self._ov is None:
            raise AdapterAuthError("OHLCVault 未初始化", source="ohlcvault", method=method)

        positional: List[Any] = []
        named: Dict[str, Any] = {}
        for key, value in kwargs.items():
            if value in (None, "", []):
                continue
            if key.startswith("_") and len(key) > 1:
                positional.append(value)
            else:
                named[key] = value

        try:
            api_method = getattr(self._ov, method)
        except AttributeError as exc:
            raise AdapterDataError(
                f"OHLCVault API 方法不存在: {method}", source="ohlcvault", method=method
            ) from exc

        capture = io.StringIO()
        try:
            with contextlib.redirect_stdout(capture):
                result = api_method(*positional, **named)
            return self._to_dataframe(result)
        except Exception as exc:
            raise self._to_adapter_error(method, exc) from exc

    # ------------------------------------------------------------------
    # Result conversion
    # ------------------------------------------------------------------

    def _to_dataframe(self, data: Any) -> pd.DataFrame:
        if data is None:
            return pd.DataFrame()
        if hasattr(data, "to_pandas"):
            return self._reset_index(data.to_pandas())
        return self._reset_index(super()._to_dataframe(data))

    @staticmethod
    def _reset_index(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty or frame.index.name is None:
            return frame
        return frame.reset_index()

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------

    def _to_adapter_error(self, method: str, exc: Exception) -> Exception:
        text = str(exc).lower()
        error_type = type(exc).__name__

        if any(
            key in text
            for key in ("snapshot", "not found", "410", "gone", "integrity", "校验")
        ):
            return AdapterDataError(
                f"OHLCVault 数据异常 ({method}): {exc}", source="ohlcvault", method=method
            )
        if any(key in text for key in ("429", "rate", "limit", "too many", "频繁")):
            return AdapterRateLimitError(
                f"OHLCVault 限流: {exc}", source="ohlcvault", method=method
            )
        if any(
            key in text
            for key in ("timeout", "超时", "connection", "连接", "network", "网络", "dns")
        ) or error_type in ("TimeoutError", "ConnectionError", "OSError"):
            return AdapterNetworkError(
                f"OHLCVault 网络异常: {exc}", source="ohlcvault", method=method
            )
        if any(key in text for key in ("401", "403", "unauthorized", "forbidden", "auth")):
            self.mark_unavailable()
            return AdapterAuthError(
                f"OHLCVault 认证失败: {exc}", source="ohlcvault", method=method
            )
        return AdapterDataError(
            f"OHLCVault 数据异常 ({method}): {exc}", source="ohlcvault", method=method
        )
