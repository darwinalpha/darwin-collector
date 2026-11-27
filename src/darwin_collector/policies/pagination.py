"""Pagination policy.

The adapter declares ``pagination_mode``:
  - ``none``     : one call, no pagination.
  - ``adapter``  : the adapter / SDK already returns the complete result; the
                   executor calls it once and does not paginate.
  - ``framework``: the adapter offers a single-call ``collect_once`` and the
                   paginator loops over pages / chunks.

The paginator chooses a concrete strategy from the options dict. It never
sleeps itself: throttling is the RateLimitPolicy's job, so ``interval_ms`` is
passed as 0 to the chunk helpers to avoid double waiting.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict

import pandas as pd

from ..chunk import (
    CallFn,
    fetch_all_pages,
    fetch_chunked_days,
    fetch_chunked_millis,
    fetch_chunked_months,
    fetch_paginated,
)
from ..defaults import (
    DEFAULT_DATE_FIELD,
    DEFAULT_MAX_EMPTY_CHUNKS,
    DEFAULT_MAX_ITERATIONS,
)
from ..types import PaginationMode


class Paginator(ABC):
    @abstractmethod
    def paginate(
        self,
        call_fn: CallFn,
        method: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> pd.DataFrame:
        """Run ``call_fn`` one or more times and return the collected frames."""
        raise NotImplementedError


class DefaultPaginator(Paginator):
    """Select a pagination strategy from ``options``.

    Trigger keys (checked in this order):
        ``max_lines``    -> reverse date pagination
        ``chunk_months`` -> calendar-month chunks, newest first
        ``chunk_ms``     -> millisecond timestamp chunks (start_time/end_time)
        ``paginate``     -> forward page-number pagination
        ``chunk_days``   -> fixed-width day chunks, newest first
        other            -> single call

    All chunk strategies stop after ``max_empty_chunks`` consecutive empty
    results and are bounded by ``max_iterations`` / ``max_pages``.
    """

    def paginate(
        self,
        call_fn: CallFn,
        method: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> pd.DataFrame:
        kwargs = dict(params)

        if "max_lines" in options:
            return fetch_paginated(
                call_fn,
                max_lines=int(options["max_lines"]),
                interval_ms=0,
                date_field=str(options.get("date_field", DEFAULT_DATE_FIELD)),
                max_iterations=int(options.get("max_iterations", DEFAULT_MAX_ITERATIONS)),
                **kwargs,
            )

        if "chunk_months" in options:
            return fetch_chunked_months(
                call_fn,
                chunk_months=int(options["chunk_months"]),
                interval_ms=0,
                max_empty_chunks=int(options.get("max_empty_chunks", DEFAULT_MAX_EMPTY_CHUNKS)),
                max_iterations=int(options.get("max_iterations", DEFAULT_MAX_ITERATIONS)),
                **kwargs,
            )

        if "chunk_ms" in options:
            return fetch_chunked_millis(
                call_fn,
                chunk_days=int(options["chunk_ms"]),
                interval_ms=0,
                max_empty_chunks=int(options.get("max_empty_chunks", DEFAULT_MAX_EMPTY_CHUNKS)),
                max_iterations=int(options.get("max_iterations", DEFAULT_MAX_ITERATIONS)),
                **kwargs,
            )

        if options.get("paginate"):
            if "page_size" in options:
                kwargs["page_size"] = options["page_size"]
            return fetch_all_pages(
                call_fn,
                interval_ms=0,
                max_pages=int(options.get("max_pages", DEFAULT_MAX_ITERATIONS)),
                **kwargs,
            )

        if "chunk_days" in options:
            return fetch_chunked_days(
                call_fn,
                chunk_days=int(options["chunk_days"]),
                interval_ms=0,
                max_empty_chunks=int(options.get("max_empty_chunks", DEFAULT_MAX_EMPTY_CHUNKS)),
                **kwargs,
            )

        return call_fn(kwargs)


class NoPagination(Paginator):
    """Single-call paginator used for ``none`` and ``adapter`` modes."""

    def paginate(
        self,
        call_fn: CallFn,
        method: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> pd.DataFrame:
        return call_fn(dict(params))


def paginator_for(mode: PaginationMode) -> Paginator:
    if mode == PaginationMode.FRAMEWORK:
        return DefaultPaginator()
    return NoPagination()


__all__ = ["Paginator", "DefaultPaginator", "NoPagination", "paginator_for"]
