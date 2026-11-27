"""Credential splitting and instance-scoped key rotation.

A single credential value may contain several keys separated by commas. The
library splits it once, then rotates between the keys on rate-limit or auth
failure. Rotation state lives on the adapter instance (never on the module),
so a long-lived host such as a future worker reuses the same pool across
collections instead of re-authenticating from scratch.

Cooldowns are measured with ``time.monotonic``: in a resident worker the clock
keeps advancing between requests, so a cooled key becomes eligible again on a
later request without any external coordination.
"""

import time
from typing import Any, Dict, List, Optional

from .exceptions import AdapterRateLimitError
from .policies.key_rotation import KeyRotationPolicy

__all__ = ["split_keys", "KeyPool"]


def split_keys(value: Any) -> List[str]:
    """Split one credential value into a list of usable keys.

    Strings are split on commas; sequences are expanded and each element is
    split again, so ``"a,b"``, ``["a", "b"]`` and ``["a,b"]`` are equivalent.
    A missing or blank value yields an empty list.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        keys: List[str] = []
        for item in value:
            keys.extend(split_keys(item))
        return keys
    text = str(value).strip()
    return [text] if text else []


class KeyPool:
    """Round-robin pool of interchangeable keys with per-key cooldown.

    The pool is owned by one adapter instance. It is safe to reuse across many
    ``collect`` calls from a resident process; it is not thread-safe, matching
    the current single-threaded worker plan.
    """

    def __init__(
        self,
        keys: List[str],
        policy: Optional[KeyRotationPolicy] = None,
        *,
        source: Optional[str] = None,
        clock: Optional[Any] = None,
    ) -> None:
        if not keys:
            raise ValueError("KeyPool requires at least one key")
        self._keys = list(keys)
        self._policy = policy or KeyRotationPolicy()
        self._source = source
        self._clock = clock or time.monotonic
        self._cursor = 0
        self._cooled_until: Dict[int, float] = {}
        self._hits: Dict[int, int] = {}

    @property
    def size(self) -> int:
        return len(self._keys)

    @property
    def cursor(self) -> int:
        return self._cursor

    def keys(self) -> List[str]:
        return list(self._keys)

    def hits(self) -> Dict[int, int]:
        """Per-key call counts, exposed for behavior-lock tests and debugging."""
        return dict(self._hits)

    def _available(self) -> List[int]:
        now = self._clock()
        return [
            index
            for index in range(len(self._keys))
            if self._cooled_until.get(index, 0.0) <= now
        ]

    def has_available(self) -> bool:
        return bool(self._available())

    def current_key(self) -> str:
        """Return the key at the cursor, advancing to an available one."""
        available = self._available()
        if not available:
            raise AdapterRateLimitError(
                f"{self._source or 'adapter'} 所有 {len(self._keys)} 个 key 均在冷却期",
                source=self._source,
            )
        if self._cursor not in available:
            self._cursor = available[0]
        self._hits[self._cursor] = self._hits.get(self._cursor, 0) + 1
        return self._keys[self._cursor]

    def mark_failed(self, kind: str) -> None:
        """Cool the current key and advance the cursor to the next usable one."""
        failed = self._cursor
        if kind == "auth":
            seconds = self._policy.auth_cooldown_seconds
        else:
            seconds = self._policy.cooldown_seconds
        self._cooled_until[failed] = self._clock() + max(0.0, float(seconds))

        available = self._available()
        if not available:
            return
        for index in available:
            if index > failed:
                self._cursor = index
                return
        self._cursor = available[0]

    def reset(self) -> None:
        """Clear cooldowns and call counts (used by reauth and close)."""
        self._cooled_until.clear()
        self._hits.clear()
        self._cursor = 0

    def set_policy(self, policy: KeyRotationPolicy) -> None:
        """Replace the rotation policy in place (state is preserved)."""
        self._policy = policy
