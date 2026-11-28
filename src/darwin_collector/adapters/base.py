"""Adapter contract.

Subclasses implement ``get_source_name`` and ``collect_once``. The instance may
be reused across many collections; ``close`` is called by the host when it
exits, not after each collection.

Key rotation is a library capability, not a per-adapter feature: an adapter
only declares ``key_fields`` (which credential fields hold its API key) and
wraps its SDK call in ``_run_with_keys``. Any credential value containing a
comma is split into multiple keys and rotated on auth / rate-limit failure.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

import pandas as pd

from ..exceptions import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimitError,
)
from ..key_pool import KeyPool, split_keys
from ..policies import KeyRotationPolicy
from ..types import PaginationMode

__all__ = ["BaseAdapter"]

T = TypeVar("T")


class BaseAdapter(ABC):
    #: Declared by each adapter: none / adapter / framework.
    pagination_mode: PaginationMode = PaginationMode.NONE

    #: Credential field names holding this source's key, in priority order.
    #: Empty means the source needs no key (baostock / ohlcvault / yfinance).
    key_fields: Tuple[str, ...] = ()

    def __init__(self) -> None:
        self._available = True
        self._initialized = False
        self._key_pool: Optional[KeyPool] = None
        self._key_policy = KeyRotationPolicy()
        self._key_clients: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------

    @abstractmethod
    def get_source_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def collect_once(self, method: str, **kwargs: Any) -> pd.DataFrame:
        """One SDK call returning one page / chunk of raw data."""
        raise NotImplementedError

    def ensure_ready(self, credentials: Optional[Dict[str, Any]] = None) -> None:
        """Initialize the SDK with parsed credentials. Idempotent."""
        if self._initialized:
            return
        self._initialized = True

    def reauth(self) -> None:
        """Re-login once after an auth error. Default is a no-op."""
        self._initialized = False
        self._reset_key_state()

    def close(self) -> None:
        """Release session / connections. Called by the host at shutdown."""
        self._initialized = False
        self._reset_key_state()

    def configure(self, policies: Any = None) -> None:
        """Inject call-level policies (currently key rotation only)."""
        policy = getattr(policies, "key_rotation", None)
        if policy is None:
            return
        self._key_policy = policy
        if self._key_pool is not None:
            self._key_pool.set_policy(policy)

    def is_available(self) -> bool:
        return self._available

    def mark_unavailable(self) -> None:
        self._available = False

    # ------------------------------------------------------------------
    # Library-level key handling
    # ------------------------------------------------------------------

    def _reset_key_state(self) -> None:
        """Drop cached clients and cooldowns; keep the keys themselves."""
        self._key_clients.clear()
        if self._key_pool is not None:
            self._key_pool.reset()

    def _init_key_pool(
        self,
        credentials: Optional[Dict[str, Any]],
        fields: Optional[Tuple[str, ...]] = None,
    ) -> Optional[KeyPool]:
        """Build the key pool by splitting comma-separated credentials."""
        names = fields if fields is not None else self.key_fields
        if not names:
            return None
        data = credentials or {}
        raw: Any = None
        for name in names:
            value = data.get(name)
            if value not in (None, "", [], ()):
                raw = value
                break
        keys = split_keys(raw)
        if not keys:
            self._key_pool = None
            return None
        self._key_pool = KeyPool(
            keys, self._key_policy, source=self.get_source_name()
        )
        return self._key_pool

    @classmethod
    def resolve_key(cls, credentials: Optional[Dict[str, Any]]) -> Optional[str]:
        """Return the single API key in ``credentials``, if there is exactly one.

        Parallel fan-out pins one request to one key; accepting several keys
        here would let rotation and per-key lanes overlap. Keyless sources
        return ``None``.
        """
        if not cls.key_fields:
            return None
        data = credentials or {}
        raw: Any = None
        for name in cls.key_fields:
            value = data.get(name)
            if value not in (None, "", [], ()):
                raw = value
                break
        keys = split_keys(raw)
        if not keys:
            return None
        if len(keys) > 1:
            raise ValueError(
                f"{cls.__name__} 并行模式要求每个请求只含一个 key，收到 {len(keys)} 个"
            )
        return keys[0]

    def _current_key(self) -> Optional[str]:
        if self._key_pool is None:
            return None
        return self._key_pool.current_key()

    def _cached_client(self, key: Optional[str], factory: Callable[[str], Any]) -> Any:
        """Create at most one client per key, reused across collections."""
        if key is None:
            return factory("")
        if key not in self._key_clients:
            self._key_clients[key] = factory(key)
        return self._key_clients[key]

    def _warm_client(self, factory: Callable[[str], Any]) -> None:
        """Create the first key's client at init time to establish the session.

        Remaining keys are created lazily on rotation, so a resident worker
        does not pay for clients it never needs.
        """
        if self._key_pool is None:
            self._cached_client(None, factory)
            return
        self._cached_client(self._key_pool.keys()[0], factory)

    def _run_with_keys(self, fn: Callable[[Optional[str]], T]) -> T:
        """Run ``fn(key)`` with automatic rotation on auth / rate errors.

        Single-key sources keep the legacy path (no cooldown): an auth or rate
        error is raised immediately so the framework RetryPolicy / reauth
        handles it exactly as before. Multi-key sources rotate the failed key
        and retry within this call; once every key is cooling the resulting
        AdapterRateLimitError propagates to the framework retry layer.
        """
        pool = self._key_pool
        if pool is None or pool.size == 1:
            return fn(self._current_key())

        last_exc: AdapterError | None = None
        for _ in range(self._key_policy.max_rotations + 1):
            key = self._current_key()
            try:
                result = fn(key)
                self._available = True
                return result
            except AdapterAuthError as exc:
                if not self._key_policy.rotate_on_auth:
                    raise
                pool.mark_failed("auth")
                self._available = True  # one bad key does not disable the source
                last_exc = exc
            except AdapterRateLimitError as exc:
                if not self._key_policy.rotate_on_rate_limit:
                    raise
                pool.mark_failed("rate")
                last_exc = exc

        assert last_exc is not None
        raise last_exc

    # ------------------------------------------------------------------
    # Result conversion
    # ------------------------------------------------------------------

    def _to_dataframe(self, data: Any) -> pd.DataFrame:
        if data is None:
            return pd.DataFrame()
        if isinstance(data, pd.DataFrame):
            return data
        try:
            return pd.DataFrame(data)
        except Exception:
            return pd.DataFrame()
