"""Key rotation policy.

A credential value containing a comma is split into several keys by the
adapter base class. This policy decides when a failed key is rotated away from
and how long it stays cooled down. It follows the same injectable-policy shape
as RetryPolicy / RateLimitPolicy; callers override it through ``Policies``.
"""

from dataclasses import dataclass

from ..defaults import (
    DEFAULT_KEY_AUTH_COOLDOWN_SECONDS,
    DEFAULT_KEY_COOLDOWN_SECONDS,
    DEFAULT_KEY_MAX_ROTATIONS,
)

__all__ = ["KeyRotationPolicy"]


@dataclass
class KeyRotationPolicy:
    """Rotation behavior for a pool of interchangeable API keys.

    ``rotate_on_auth`` is enabled because an invalid/dead key is as good a
    reason to switch as a rate limit. Cooldown is measured on a monotonic clock
    and decays naturally: a key becomes eligible again once its cooldown
    expires, so the pool never permanently blacklists a key.
    """

    cooldown_seconds: float = DEFAULT_KEY_COOLDOWN_SECONDS
    auth_cooldown_seconds: float = DEFAULT_KEY_AUTH_COOLDOWN_SECONDS
    max_rotations: int = DEFAULT_KEY_MAX_ROTATIONS
    rotate_on_auth: bool = True
    rotate_on_rate_limit: bool = True
