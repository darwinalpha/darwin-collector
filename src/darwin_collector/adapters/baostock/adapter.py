"""Baostock adapter.

Baostock needs no token, but ``login()`` opens a process-level TCP socket.
The session is created once in ``ensure_ready`` and released in ``close``, so a
long-lived host (future worker) logs in once and reuses the connection across
collections. Stdout produced by the SDK is suppressed locally.
"""

import contextlib
import io
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

__all__ = ["BaostockAdapter"]

_NUMERIC_COLUMNS = (
    "open", "high", "low", "close", "preclose", "volume", "amount", "turn",
    "pctChg", "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM",
)


class BaostockAdapter(BaseAdapter):
    # Baostock does not paginate: one call returns the full result.
    pagination_mode = PaginationMode.NONE

    def __init__(self) -> None:
        super().__init__()
        self._bs: Optional[Any] = None
        self._logged_in = False

    def get_source_name(self) -> str:
        return "baostock"

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def ensure_ready(self, credentials: Optional[Dict[str, Any]] = None) -> None:
        if self._initialized:
            return

        try:
            import baostock as bs  # type: ignore
        except ImportError as exc:
            raise AdapterDataError(
                "baostock SDK 未安装，请安装 .[baostock] extra",
                source="baostock",
                context={"error": str(exc)},
            ) from exc

        self._bs = bs
        self._login()
        self._initialized = True

    def _login(self) -> None:
        assert self._bs is not None
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            result = self._bs.login()
        code = getattr(result, "error_code", None)
        if code is not None and str(code) != "0":
            self.mark_unavailable()
            raise AdapterAuthError(
                f"Baostock 登录失败: {getattr(result, 'error_msg', code)}",
                source="baostock",
            )
        self._logged_in = True
        self._available = True

    def _logout(self) -> None:
        if self._bs is not None and self._logged_in:
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                self._bs.logout()
        self._logged_in = False

    def reauth(self) -> None:
        self._logout()
        self._initialized = False
        self._login()
        self._initialized = True

    def close(self) -> None:
        self._logout()
        self._bs = None
        self._initialized = False

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def collect_once(self, method: str, **kwargs: Any) -> pd.DataFrame:
        if not self._initialized or self._bs is None or not self._logged_in:
            raise AdapterAuthError("Baostock 未登录", source="baostock", method=method)

        try:
            api_method = getattr(self._bs, method)
        except AttributeError as exc:
            raise AdapterDataError(
                f"Baostock API 方法不存在: {method}", source="baostock", method=method
            ) from exc

        cleaned = {key: value for key, value in kwargs.items() if value not in (None, "", [])}
        capture = io.StringIO()
        try:
            with contextlib.redirect_stdout(capture):
                result = api_method(**cleaned)
            return self._parse_result(result)
        except AdapterDataError:
            raise
        except Exception as exc:
            raise self._to_adapter_error(method, exc) from exc

    def _parse_result(self, result: Any) -> pd.DataFrame:
        if result is None:
            return pd.DataFrame()

        code = getattr(result, "error_code", None)
        message = getattr(result, "error_msg", None)
        if code is not None and str(code) != "0":
            raise AdapterDataError(
                f"Baostock 查询失败: {message}", source="baostock"
            )

        columns = getattr(result, "fields", None)
        rows = []
        try:
            while result.error_code == "0" and result.next():
                row = result.get_row_data()
                if row:
                    rows.append(row)
        except (AttributeError, TypeError):
            pass

        if not rows:
            return pd.DataFrame()
        if columns is None:
            columns = [f"col_{index}" for index in range(len(rows[0]))]

        frame = pd.DataFrame(rows, columns=columns)
        for column in _NUMERIC_COLUMNS:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------

    def _to_adapter_error(self, method: str, exc: Exception) -> Exception:
        text = str(exc).lower()
        if any(key in text for key in ("频率", "limit", "too many", "频繁", "throttle")):
            self.mark_unavailable()
            return AdapterRateLimitError(
                f"Baostock 限流: {exc}", source="baostock", method=method
            )
        if any(
            key in text
            for key in ("timeout", "超时", "connection", "连接", "network", "网络")
        ):
            return AdapterNetworkError(
                f"Baostock 网络异常: {exc}", source="baostock", method=method
            )
        return AdapterDataError(
            f"Baostock 数据异常: {exc}", source="baostock", method=method
        )
