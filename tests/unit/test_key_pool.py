"""Unit tests for the library-level key pool and rotation policy."""

import pytest

from darwin_collector import (
    AdapterAuthError,
    AdapterRateLimitError,
    KeyPool,
    KeyRotationPolicy,
    split_keys,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_split_keys_handles_comma_list_and_blank():
    assert split_keys("k1, k2 ,,k3") == ["k1", "k2", "k3"]
    assert split_keys(["k1,k2", " k3 "]) == ["k1", "k2", "k3"]
    assert split_keys(None) == []
    assert split_keys("") == []
    assert split_keys(123) == ["123"]


def test_key_pool_requires_keys():
    with pytest.raises(ValueError):
        KeyPool([])


def test_key_pool_stays_on_healthy_key_until_failure():
    """The cursor advances only on failure, so a healthy key is reused —
    which is exactly what a resident worker wants for session stability."""
    pool = KeyPool(["k1", "k2", "k3"])
    assert [pool.current_key() for _ in range(4)] == ["k1", "k1", "k1", "k1"]
    assert pool.hits() == {0: 4}


def test_rate_failure_cools_key_and_skips_it():
    clock = FakeClock()
    pool = KeyPool(["k1", "k2"], KeyRotationPolicy(cooldown_seconds=30), clock=clock)
    assert pool.current_key() == "k1"
    pool.mark_failed("rate")
    assert pool.current_key() == "k2"
    assert not pool.has_available() or pool.current_key() == "k2"


def test_auth_failure_uses_longer_cooldown():
    clock = FakeClock()
    policy = KeyRotationPolicy(
        cooldown_seconds=10, auth_cooldown_seconds=100
    )
    pool = KeyPool(["k1", "k2"], policy, clock=clock)
    pool.current_key()
    pool.mark_failed("auth")
    clock.now = 50
    assert pool.current_key() == "k2"  # k1 still cooling (100s)


def test_cooldown_decays_and_key_becomes_eligible_again():
    clock = FakeClock()
    pool = KeyPool(["k1"], KeyRotationPolicy(cooldown_seconds=30), clock=clock)
    pool.current_key()
    pool.mark_failed("rate")
    with pytest.raises(AdapterRateLimitError):
        pool.current_key()
    clock.now = 31
    assert pool.current_key() == "k1"


def test_all_keys_cooling_raises_rate_limit():
    clock = FakeClock()
    pool = KeyPool(["k1", "k2"], clock=clock)
    pool.current_key()
    pool.mark_failed("rate")
    pool.current_key()
    pool.mark_failed("rate")
    with pytest.raises(AdapterRateLimitError):
        pool.current_key()


def test_reset_and_set_policy():
    clock = FakeClock()
    pool = KeyPool(["k1"], clock=clock)
    pool.current_key()
    pool.mark_failed("rate")
    assert not pool.has_available()
    pool.set_policy(KeyRotationPolicy(cooldown_seconds=0))
    pool.reset()
    assert pool.has_available()
    assert pool.cursor == 0
    assert pool.hits() == {}
