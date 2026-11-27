"""Executes one collection request: initialize → collect_once → retry / rate
limit → pagination → result. All policy decisions happen here, never inside a
config file or a global setting.
"""

from time import perf_counter
from typing import Any, Dict

import pandas as pd

from .adapters.base import BaseAdapter
from .models import CollectRequest, CollectResult, Policies
from .types import PaginationMode
from .policies import Paginator, RateLimitPolicy, RetryPolicy
from .policies.pagination import paginator_for

__all__ = ["Executor"]


class Executor:
    def execute(self, adapter: BaseAdapter, request: CollectRequest) -> CollectResult:
        started = perf_counter()
        policies = request.policies or Policies()
        retry: RetryPolicy = policies.retry or RetryPolicy()
        rate_limit: RateLimitPolicy = policies.rate_limit or RateLimitPolicy()

        adapter.configure(policies)
        adapter.ensure_ready(request.credentials)

        mode = policies.pagination_mode or adapter.pagination_mode
        paginator: Paginator = policies.paginator or paginator_for(mode)

        def call_once(kwargs: Dict[str, Any]) -> pd.DataFrame:
            """One SDK call wrapped with rate limiting and retry policies."""
            if request.fake:
                return pd.DataFrame()

            def invoke() -> pd.DataFrame:
                rate_limit.before_call()
                return adapter.collect_once(request.method, **kwargs)

            return retry.run(invoke, reauth=adapter.reauth)

        # Framework mode: single-call adapter + paginator loop. In adapter/none
        # mode a single call already returns the complete result.
        if mode == PaginationMode.FRAMEWORK:
            frame = paginator.paginate(
                call_once, request.method, request.params, request.options
            )
        else:
            frame = call_once(dict(request.params))

        elapsed = (perf_counter() - started) * 1000.0
        return CollectResult(
            source=request.source,
            method=request.method,
            frames=[frame],
            attempts=1,
            elapsed_ms=elapsed,
            fake=request.fake,
        )
