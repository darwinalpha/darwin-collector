import pytest

from darwin_collector import AdapterNotRegisteredError, Registry
from tests.conftest import FakeAdapter


def factory():
    return FakeAdapter()


def test_register_and_get():
    r = Registry()
    r.register("Tushare", factory)
    assert r.has("tushare")
    assert isinstance(r.get("tushare")(), FakeAdapter)
    assert r.sources() == ["tushare"]
    assert len(r) == 1


def test_unregistered_raises_typed_error():
    r = Registry()
    with pytest.raises(AdapterNotRegisteredError) as e:
        r.get("nope")
    assert e.value.source == "nope"


def test_duplicate_register_fails():
    r = Registry()
    r.register("tushare", factory)
    with pytest.raises(ValueError):
        r.register("tushare", factory)
