"""Self-contained pagination / chunk helpers.

No dependency on any data source SDK, config loader or logger. Callers pass a
``call_fn`` that performs a single SDK call; these helpers only replace values
of keys that already exist in ``kwargs`` (never add or drop keys) and merge the
resulting DataFrames. Merging never deduplicates — that belongs to downstream
layers.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from .defaults import (
    DEFAULT_DATE_FIELD,
    DEFAULT_INTERVAL_MS,
    DEFAULT_MAX_EMPTY_CHUNKS,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_PAGES,
    DEFAULT_PAGE_SIZE,
)

CallFn = Callable[[Dict[str, Any]], pd.DataFrame]
CST = timezone(timedelta(hours=8))


def _require_keys(kwargs: Dict[str, Any], keys: List[str], func_name: str) -> None:
    missing = [k for k in keys if k not in kwargs]
    if missing:
        raise ValueError(f"{func_name}: kwargs 缺少必需键 {missing}")


def normalize_date(date_str: str) -> str:
    """Normalize a date to ``YYYY-MM-DD`` (accepts ``YYYYMMDD``)."""
    if not date_str:
        raise ValueError("日期字符串为空")
    s = str(date_str).strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    raise ValueError(f"无法解析日期: {s}")


def compact_date(date_str: str) -> str:
    return str(date_str).replace("-", "")


def normalize_date_input(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    since_ts_millis: Optional[int] = None,
    until_ts_millis: Optional[int] = None,
) -> tuple[str, str]:
    """Return ``(start, end)`` in ``YYYYMMDD`` form."""
    if start_date and end_date:
        return compact_date(normalize_date(start_date)), compact_date(normalize_date(end_date))
    if since_ts_millis is not None and until_ts_millis is not None:
        start_dt = datetime.fromtimestamp(int(since_ts_millis) / 1000, CST)
        end_dt = datetime.fromtimestamp(int(until_ts_millis) / 1000, CST)
        return start_dt.strftime("%Y%m%d"), end_dt.strftime("%Y%m%d")
    raise ValueError(
        f"无法归一化日期: start_date={start_date}, end_date={end_date}, "
        f"since_ts_millis={since_ts_millis}, until_ts_millis={until_ts_millis}"
    )


def _prev_date(date_str: str) -> str:
    """Previous calendar day of a ``YYYYMMDD`` string."""
    return (datetime.strptime(date_str, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")


def merge_chunks(
    all_dfs: List[pd.DataFrame],
    dedup_keys: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Concatenate frames. Deduplication is opt-in and off by default."""
    if not all_dfs:
        return pd.DataFrame()
    result = pd.concat(all_dfs, ignore_index=True)
    if dedup_keys:
        result = result.drop_duplicates(subset=dedup_keys)
    return result


def fetch_paginated(
    call_fn: CallFn,
    max_lines: int,
    interval_ms: int = DEFAULT_INTERVAL_MS,
    date_field: str = DEFAULT_DATE_FIELD,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    fake: bool = False,
    **kwargs: Any,
) -> pd.DataFrame:
    """Reverse date pagination driven by ``min(date_field)`` of each page.

    Contract: ``kwargs`` must already contain ``start_date`` and ``end_date``;
    only their values are replaced between calls. Stops when a page is short,
    empty, lacks ``date_field``, reaches the start boundary, or hits the
    iteration cap.
    """
    if fake:
        return pd.DataFrame()

    _require_keys(kwargs, ["start_date", "end_date"], "fetch_paginated")
    start_str, end_str = normalize_date_input(
        start_date=kwargs.get("start_date"), end_date=kwargs.get("end_date")
    )

    interval_s = interval_ms / 1000.0
    all_dfs: List[pd.DataFrame] = []
    cur_end = end_str

    for iteration in range(max_iterations):
        call_kwargs = dict(kwargs)
        call_kwargs["start_date"] = start_str
        call_kwargs["end_date"] = cur_end

        df = call_fn(call_kwargs)
        if df.empty:
            break

        all_dfs.append(df)
        if len(df) < max_lines:
            break
        if date_field not in df.columns:
            break

        oldest = str(df[date_field].min())
        if oldest <= start_str:
            break
        cur_end = _prev_date(oldest)

        if iteration < max_iterations - 1 and interval_s > 0:
            time.sleep(interval_s)

    return merge_chunks(all_dfs, dedup_keys=None)


def fetch_all_pages(
    call_fn: CallFn,
    interval_ms: int = DEFAULT_INTERVAL_MS,
    max_pages: int = DEFAULT_MAX_PAGES,
    fake: bool = False,
    **kwargs: Any,
) -> pd.DataFrame:
    """Forward page-number pagination (1, 2, 3, ... until empty or short)."""
    if fake:
        return pd.DataFrame()

    # page / page_size are controlled by this helper; seed them if absent.
    page_size = kwargs.get("page_size") or DEFAULT_PAGE_SIZE
    interval_s = interval_ms / 1000.0
    all_dfs: List[pd.DataFrame] = []
    page = 1

    while page <= max_pages:
        call_kwargs = dict(kwargs)
        call_kwargs["page"] = page
        call_kwargs["page_size"] = page_size

        df = call_fn(call_kwargs)
        if df.empty:
            break

        all_dfs.append(df)
        if len(df) < page_size:
            break

        page += 1
        if page <= max_pages and interval_s > 0:
            time.sleep(interval_s)

    return merge_chunks(all_dfs, dedup_keys=None)


def fetch_chunked_days(
    call_fn: CallFn,
    chunk_days: int,
    interval_ms: int = DEFAULT_INTERVAL_MS,
    fake: bool = False,
    max_empty_chunks: int = DEFAULT_MAX_EMPTY_CHUNKS,
    **kwargs: Any,
) -> pd.DataFrame:
    """Split ``[start_date, end_date]`` into day windows, newest first."""
    if fake:
        return pd.DataFrame()

    _require_keys(kwargs, ["start_date", "end_date"], "fetch_chunked_days")
    start_str, end_str = normalize_date_input(
        start_date=kwargs.get("start_date"), end_date=kwargs.get("end_date")
    )

    chunks: List[tuple[str, str]] = []
    current = datetime.strptime(start_str, "%Y%m%d")
    end = datetime.strptime(end_str, "%Y%m%d")
    while current <= end:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end)
        chunks.append((current.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
        current = chunk_end + timedelta(days=1)

    chunks.reverse()
    interval_s = interval_ms / 1000.0
    all_dfs: List[pd.DataFrame] = []
    empty_count = 0

    for idx, (cur_start, cur_end) in enumerate(chunks, 1):
        call_kwargs = dict(kwargs)
        call_kwargs["start_date"] = cur_start
        call_kwargs["end_date"] = cur_end
        df = call_fn(call_kwargs)

        if df.empty:
            empty_count += 1
            if empty_count >= max_empty_chunks:
                break
        else:
            empty_count = 0
            all_dfs.append(df)

        if idx < len(chunks) and interval_s > 0:
            time.sleep(interval_s)

    return merge_chunks(all_dfs, dedup_keys=None)


def date_to_millis_start(date_str: str) -> int:
    """YYYYMMDD -> milliseconds at 00:00:00.000 CST."""
    dt = datetime.strptime(compact_date(date_str), "%Y%m%d").replace(tzinfo=CST)
    return int(dt.timestamp() * 1000)


def date_to_millis_end(date_str: str) -> int:
    """YYYYMMDD -> milliseconds at 23:59:59.999 CST."""
    dt = datetime.strptime(compact_date(date_str), "%Y%m%d").replace(
        hour=23, minute=59, second=59, microsecond=999000, tzinfo=CST
    )
    return int(dt.timestamp() * 1000)


def _add_months(year: int, month: int, count: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + count
    return index // 12, index % 12 + 1


def _month_chunks(
    start_str: str, end_str: str, chunk_months: int
) -> list[tuple[datetime, datetime]]:
    """Split [start, end] into calendar-aligned month blocks."""
    start = datetime.strptime(compact_date(start_str), "%Y%m%d")
    end = datetime.strptime(compact_date(end_str), "%Y%m%d")
    if start > end:
        raise ValueError(f"start_date ({start_str}) 晚于 end_date ({end_str})")
    if chunk_months < 1:
        raise ValueError("chunk_months 必须 >= 1")

    chunks: list[tuple[datetime, datetime]] = []
    current = start
    while current <= end:
        if chunk_months == 12:
            block_end = datetime(current.year, 12, 31)
        elif chunk_months == 1:
            next_y, next_m = _add_months(current.year, current.month, 1)
            block_end = datetime(next_y, next_m, 1) - timedelta(days=1)
        else:
            end_y, end_m = _add_months(current.year, current.month, chunk_months)
            block_end = datetime(end_y, end_m, 1) - timedelta(days=1)
        chunk_end = min(block_end, end)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


def fetch_chunked_months(
    call_fn: CallFn,
    chunk_months: int,
    interval_ms: int = DEFAULT_INTERVAL_MS,
    fake: bool = False,
    max_empty_chunks: int = DEFAULT_MAX_EMPTY_CHUNKS,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    **kwargs: Any,
) -> pd.DataFrame:
    """Split a timestamp range into month blocks, newest block first.

    Replaces ``since_ts_millis`` / ``until_ts_millis`` in each call. Accepts
    ``start_date`` / ``end_date`` as an alternative input. Stops after
    ``max_empty_chunks`` consecutive empty blocks or ``max_iterations``.
    """
    if fake:
        return pd.DataFrame()

    _require_keys(kwargs, ["since_ts_millis", "until_ts_millis"], "fetch_chunked_months")
    start_str, end_str = normalize_date_input(
        start_date=kwargs.get("start_date"),
        end_date=kwargs.get("end_date"),
        since_ts_millis=kwargs.get("since_ts_millis"),
        until_ts_millis=kwargs.get("until_ts_millis"),
    )
    blocks = _month_chunks(start_str, end_str, chunk_months)
    blocks = list(reversed(blocks))[:max_iterations]
    interval_s = interval_ms / 1000.0
    all_dfs: list[pd.DataFrame] = []
    empty_count = 0

    for idx, (block_start, block_end) in enumerate(blocks, 1):
        call_kwargs = dict(kwargs)
        call_kwargs["since_ts_millis"] = date_to_millis_start(block_start.strftime("%Y%m%d"))
        call_kwargs["until_ts_millis"] = date_to_millis_end(block_end.strftime("%Y%m%d"))
        df = call_fn(call_kwargs)
        if df.empty:
            empty_count += 1
            if empty_count >= max_empty_chunks:
                break
        else:
            empty_count = 0
            all_dfs.append(df)
        if idx < len(blocks) and interval_s > 0:
            time.sleep(interval_s)

    return merge_chunks(all_dfs, dedup_keys=None)


def fetch_chunked_millis(
    call_fn: CallFn,
    chunk_days: int,
    interval_ms: int = DEFAULT_INTERVAL_MS,
    fake: bool = False,
    max_empty_chunks: int = DEFAULT_MAX_EMPTY_CHUNKS,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    **kwargs: Any,
) -> pd.DataFrame:
    """Split ``[start_time, end_time]`` (millisecond timestamps) into windows.

    Replaces ``start_time`` / ``end_time`` in each call, newest window first.
    Stops after ``max_empty_chunks`` consecutive empty windows, so wide ranges
    with no data do not scan every window.
    """
    if fake:
        return pd.DataFrame()

    _require_keys(kwargs, ["start_time", "end_time"], "fetch_chunked_millis")
    start_ms = int(kwargs["start_time"])
    end_ms = int(kwargs["end_time"])
    if start_ms > end_ms:
        raise ValueError("start_time 晚于 end_time")
    if chunk_days < 1:
        raise ValueError("chunk_days 必须 >= 1")

    window_ms = int(chunk_days) * 24 * 3600 * 1000
    windows: list[tuple[int, int]] = []
    cursor = start_ms
    while cursor < end_ms and len(windows) < max_iterations:
        windows.append((cursor, min(cursor + window_ms, end_ms)))
        cursor += window_ms
    windows = list(reversed(windows))

    interval_s = interval_ms / 1000.0
    all_dfs: list[pd.DataFrame] = []
    empty_count = 0

    for idx, (window_start, window_end) in enumerate(windows, 1):
        call_kwargs = dict(kwargs)
        call_kwargs["start_time"] = window_start
        call_kwargs["end_time"] = window_end
        df = call_fn(call_kwargs)
        if df.empty:
            empty_count += 1
            if empty_count >= max_empty_chunks:
                break
        else:
            empty_count = 0
            all_dfs.append(df)
        if idx < len(windows) and interval_s > 0:
            time.sleep(interval_s)

    return merge_chunks(all_dfs, dedup_keys=None)


__all__ = [
    "CallFn",
    "CST",
    "normalize_date",
    "compact_date",
    "normalize_date_input",
    "date_to_millis_start",
    "date_to_millis_end",
    "merge_chunks",
    "fetch_paginated",
    "fetch_all_pages",
    "fetch_chunked_days",
    "fetch_chunked_months",
    "fetch_chunked_millis",
]
