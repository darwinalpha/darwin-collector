import pytest

from darwin_collector import (
    AdapterAuthError,
    AdapterNetworkError,
    AdapterRateLimitError,
)
from darwin_collector.policies import RetryPolicy, RateLimitPolicy
from darwin_collector.policies.pagination import DefaultPaginator


def test_retry_is_bounded_on_rate_limit():
    calls = []

    def fn():
        calls.append(1)
        raise AdapterRateLimitError("slow down")

    policy = RetryPolicy(max_attempts=3, base_delay_ms=0)
    with pytest.raises(AdapterRateLimitError):
        policy.run(fn)
    assert len(calls) == 3


def test_retry_does_not_retry_auth_error_without_reauth():
    calls = []

    def fn():
        calls.append(1)
        raise AdapterAuthError("bad token")

    policy = RetryPolicy(max_attempts=3, base_delay_ms=0)
    with pytest.raises(AdapterAuthError):
        policy.run(fn)
    assert len(calls) == 1


def test_retry_reauths_once_then_raises():
    calls = []
    reauths = []

    def fn():
        calls.append(1)
        raise AdapterAuthError("bad token")

    policy = RetryPolicy(max_attempts=5, base_delay_ms=0, reauth_once=True)
    with pytest.raises(AdapterAuthError):
        policy.run(fn, reauth=lambda: reauths.append(1))
    assert len(calls) == 2
    assert len(reauths) == 1


def test_retry_data_error_is_not_retried():
    from darwin_collector import AdapterDataError

    calls = []

    def fn():
        calls.append(1)
        raise AdapterDataError("bad")

    with pytest.raises(AdapterDataError):
        RetryPolicy(max_attempts=3, base_delay_ms=0).run(fn)
    assert len(calls) == 1


def test_rate_limit_defaults():
    p = RateLimitPolicy(interval_ms=0, cooldown_ms=0)
    p.before_call()
    p.on_rate_limit()  # no sleeping when disabled


def test_paginator_single_call_fallback():
    seen = []

    def call(kwargs):
        seen.append(kwargs)
        import pandas as pd
        return pd.DataFrame({"a": [1]})

    frame = DefaultPaginator().paginate(call, "m", {"x": 1}, {})
    assert frame["a"].tolist() == [1]
    assert seen == [{"x": 1}]
