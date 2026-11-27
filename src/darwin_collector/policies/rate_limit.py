"""Rate-limit policy: spacing between SDK calls and a cooldown window after a
429/rate-limit response. Replaces the old scattered ``sleep`` calls and makes
the previously inert retry/rate-limit settings effective.
"""

import time
from dataclasses import dataclass

from ..defaults import DEFAULT_COOLDOWN_MS, DEFAULT_INTERVAL_MS


@dataclass
class RateLimitPolicy:
    interval_ms: int = DEFAULT_INTERVAL_MS
    cooldown_ms: int = DEFAULT_COOLDOWN_MS

    def before_call(self) -> None:
        if self.interval_ms > 0:
            time.sleep(self.interval_ms / 1000.0)

    def on_rate_limit(self) -> None:
        if self.cooldown_ms > 0:
            time.sleep(self.cooldown_ms / 1000.0)


__all__ = ["RateLimitPolicy"]
