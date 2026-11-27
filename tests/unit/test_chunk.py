"""Tests for month-based and millisecond-based chunk helpers."""

import pandas as pd

from darwin_collector.chunk import (
    date_to_millis_end,
    date_to_millis_start,
    fetch_chunked_millis,
    fetch_chunked_months,
)


def test_millis_boundaries_are_cst_day_edges():
    start = date_to_millis_start("20240101")
    end = date_to_millis_end("20240101")
    assert end - start == 86_399_999


def test_month_chunks_newest_first_and_stop_on_empty():
    since = date_to_millis_start("20240101")
    until = date_to_millis_end("20240430")
    seen = []

    def call(kwargs):
        seen.append((kwargs["since_ts_millis"], kwargs["until_ts_millis"]))
        # Only April has data; older months are empty and should stop early.
        if kwargs["since_ts_millis"] >= date_to_millis_start("20240401"):
            return pd.DataFrame({"v": [1]})
        return pd.DataFrame()

    frame = fetch_chunked_months(
        call, chunk_months=1, interval_ms=0, max_empty_chunks=1,
        since_ts_millis=since, until_ts_millis=until,
    )
    assert len(seen) == 2  # April (data) + March (empty -> stop)
    assert frame["v"].tolist() == [1]
    # Newest first: first call is April.
    assert seen[0][0] == date_to_millis_start("20240401")


def test_millis_chunks_newest_first_and_bounded():
    start = date_to_millis_start("20240101")
    end = date_to_millis_end("20240110")
    seen = []

    def call(kwargs):
        seen.append((kwargs["start_time"], kwargs["end_time"]))
        return pd.DataFrame({"v": [1]})

    frame = fetch_chunked_millis(
        call, chunk_days=3, interval_ms=0, max_iterations=2,
        start_time=start, end_time=end,
    )
    assert len(seen) == 2  # capped by max_iterations
    assert len(frame) > 0


def test_millis_chunks_stop_after_consecutive_empty():
    start = date_to_millis_start("20240101")
    end = date_to_millis_end("20240130")
    seen = []

    def call(kwargs):
        seen.append(kwargs["start_time"])
        return pd.DataFrame()  # all empty

    frame = fetch_chunked_millis(
        call, chunk_days=2, interval_ms=0, max_empty_chunks=2,
        max_iterations=15, start_time=start, end_time=end,
    )
    assert len(seen) == 2
    assert frame.empty
