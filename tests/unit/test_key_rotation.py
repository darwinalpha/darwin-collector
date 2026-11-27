"""Behavior-lock tests for library-level key rotation across adapters.

Covers the requirements:
  - any credential containing a comma is split into multiple keys
  - both auth and rate-limit errors rotate to the next key
  - rotation policy is injectable via Policies and behaves like other policies
  - adapter instances can be reused across collections (worker scenario):
    cooldown state persists in the instance between collect calls
"""

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from darwin_collector import (
    AdapterAuthError,
    AdapterManager,
    AdapterRateLimitError,
    CollectRequest,
    KeyRotationPolicy,
    Policies,
)
from darwin_collector.executor import Executor
from darwin_collector.adapters.ftshare import FtshareAdapter
from darwin_collector.adapters.tushare import TushareAdapter


class FakePro:
    def __init__(self, token, fail=None):
        self.token = token
        self.fail = fail
        self.calls = []

    def daily(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise self.fail
        return pd.DataFrame({"close": [1.0]})


def make_pro_by_token(tokens, fails=None):
    fails = fails or {}
    made = {}

    def pro_api(token):
        made[token] = FakePro(token, fail=fails.get(token))
        return made[token]

    return pro_api, made


def inject_tushare(monkeypatch, pro_api):
    module = sys.modules.get("tushare") or SimpleNamespace()
    module.pro_api = pro_api
    monkeypatch.setitem(sys.modules, "tushare", module)


def test_comma_separated_token_is_split_into_pool(monkeypatch):
    pro_api, made = make_pro_by_token(["t1", "t2"])
    inject_tushare(monkeypatch, pro_api)
    adapter = TushareAdapter()
    adapter.ensure_ready({"token": "t1, t2"})
    assert adapter._key_pool.size == 2
    assert adapter._key_pool.keys() == ["t1", "t2"]
    # first key's client warmed at init
    assert "t1" in made


def test_rate_limit_rotates_to_next_key(monkeypatch):
    pro_api, made = make_pro_by_token(["t1", "t2"], fails={"t1": RuntimeError("频率超限")})
    inject_tushare(monkeypatch, pro_api)
    adapter = TushareAdapter()
    adapter.ensure_ready({"token": "t1,t2"})
    frame = adapter.collect_once("daily")
    assert not frame.empty  # t2 succeeded after t1 rate-limited
    assert len(made["t1"].calls) == 1
    assert len(made["t2"].calls) == 1


def test_auth_error_rotates_to_next_key(monkeypatch):
    pro_api, made = make_pro_by_token(["t1", "t2"], fails={"t1": RuntimeError("invalid token")})
    inject_tushare(monkeypatch, pro_api)
    adapter = TushareAdapter()
    adapter.ensure_ready({"token": "t1,t2"})
    frame = adapter.collect_once("daily")
    assert not frame.empty
    assert adapter.is_available()  # one bad key does not disable the source
    assert len(made["t2"].calls) == 1


def test_both_keys_fail_raises_rate_limit(monkeypatch):
    pro_api, _ = make_pro_by_token(
        ["t1", "t2"],
        fails={"t1": RuntimeError("频率超限"), "t2": RuntimeError("频率超限")},
    )
    inject_tushare(monkeypatch, pro_api)
    adapter = TushareAdapter()
    adapter.ensure_ready({"token": "t1,t2"})
    with pytest.raises(AdapterRateLimitError):
        adapter.collect_once("daily")


def test_single_key_preserves_legacy_behavior(monkeypatch):
    """A single key raises auth immediately; framework reauth handles it."""
    pro_api, made = make_pro_by_token(["t1"], fails={"t1": RuntimeError("invalid token")})
    inject_tushare(monkeypatch, pro_api)
    adapter = TushareAdapter()
    adapter.ensure_ready({"token": "t1"})
    with pytest.raises(AdapterAuthError):
        adapter.collect_once("daily")
    assert len(made["t1"].calls) == 1  # no internal rotation attempts


def test_policy_injected_via_executor(monkeypatch):
    """KeyRotationPolicy flows from Policies -> Executor -> adapter pool."""
    custom = KeyRotationPolicy(cooldown_seconds=999, max_rotations=1, rotate_on_auth=False)
    pro_api, _ = make_pro_by_token(["t1", "t2"], fails={"t1": RuntimeError("invalid token")})
    inject_tushare(monkeypatch, pro_api)

    adapter = TushareAdapter()
    # rotate_on_auth=False => no internal rotation; the auth error propagates
    # through Executor's reauth-once policy and is raised.
    with pytest.raises(AdapterAuthError):
        Executor().execute(
            adapter,
            CollectRequest(
                source="tushare",
                method="daily",
                credentials={"token": "t1,t2"},
                policies=Policies(key_rotation=custom),
            ),
        )
    # The custom policy still reached both the adapter and its key pool.
    assert adapter._key_policy is custom
    assert adapter._key_pool._policy is custom


def test_manager_reuses_instance_and_pool_across_collections(monkeypatch):
    """Worker-style reuse: cooldown state survives between collect() calls."""
    pro_api, made = make_pro_by_token(
        ["t1", "t2"], fails={"t1": RuntimeError("频率超限")}
    )
    inject_tushare(monkeypatch, pro_api)

    manager = AdapterManager()
    manager.register("tushare", TushareAdapter)
    request = CollectRequest(
        source="tushare", method="daily", credentials={"token": "t1,t2"}
    )
    first = manager.collect(request)
    assert not first.to_dataframe().empty

    adapter = manager.get_adapter("tushare")
    assert adapter._key_pool.hits()[0] == 1  # t1 cooled from first request
    cursor_after_first = adapter._key_pool.cursor

    second = manager.collect(request)
    assert not second.to_dataframe().empty
    assert manager.get_adapter("tushare") is adapter  # same reused instance
    # t1 still in cooldown on the second request (clock has not advanced 30s),
    # so the pool skips it and keeps using t2.
    assert adapter._key_pool.hits()[0] == 1
    assert adapter._key_pool.cursor == cursor_after_first
