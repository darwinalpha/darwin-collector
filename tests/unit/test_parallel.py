import pandas as pd
import pytest

from darwin_collector import AdapterManager, CollectRequest
from darwin_collector.adapters.base import BaseAdapter


class KeyedAdapter(BaseAdapter):
    key_fields = ("token",)

    def __init__(self, log):
        super().__init__()
        self.log = log
        self.closed = False

    def get_source_name(self):
        return "keyed"

    def ensure_ready(self, credentials=None):
        self._init_key_pool(credentials)
        self._initialized = True

    def collect_once(self, method, **kwargs):
        def invoke(key):
            self.log.append(key)
            if key == "bad":
                raise RuntimeError("boom")
            return pd.DataFrame({"v": [1]})

        return self._run_with_keys(invoke)

    def close(self):
        self.closed = True
        super().close()


class KeylessAdapter(KeyedAdapter):
    key_fields = ()


def make_manager(log):
    manager = AdapterManager()
    manager.register("keyed", lambda: KeyedAdapter(log))
    return manager


def request(key):
    return CollectRequest(
        source="keyed", method="m", credentials={"token": key}
    )


def test_parallel_uses_one_isolated_instance_per_key():
    log = []
    manager = make_manager(log)

    results = manager.collect_parallel([request("a"), request("b")])

    assert [result.row_count for result in results] == [1, 1]
    assert sorted(log) == ["a", "b"]
    assert manager.get_adapter("keyed", "a") is not manager.get_adapter("keyed", "b")


def test_parallel_rejects_multi_key_credentials():
    log = []
    manager = make_manager(log)
    multi = CollectRequest(source="keyed", method="m", credentials={"token": "a,b"})

    with pytest.raises(ValueError, match="只含一个 key"):
        manager.collect_parallel([multi])


def test_parallel_rejects_keyless_source():
    log = []
    manager = AdapterManager()
    manager.register("keyless", lambda: KeylessAdapter(log))

    with pytest.raises(ValueError, match="没有可用于并行的 API key"):
        manager.collect_parallel(
            [CollectRequest(source="keyless", method="m")]
        )


def test_parallel_fail_fast_waits_for_other_lanes():
    log = []
    manager = make_manager(log)

    with pytest.raises(RuntimeError, match="boom"):
        manager.collect_parallel([request("a"), request("bad")])

    assert set(log) == {"a", "bad"}


def test_collect_rejects_mismatched_key():
    log = []
    manager = make_manager(log)

    with pytest.raises(ValueError, match="不一致"):
        manager.collect(request("a"), key="b")


def test_close_releases_all_lane_instances():
    log = []
    manager = make_manager(log)
    manager.collect_parallel([request("a"), request("b")])
    instances = [manager.get_adapter("keyed", "a"), manager.get_adapter("keyed", "b")]

    manager.close()

    assert all(instance.closed for instance in instances)
    assert manager.get_adapter("keyed") is not instances[0]
