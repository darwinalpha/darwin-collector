"""Retry policy: decides whether a failed call should be retried and how long
to wait. Only network / rate-limit errors are retryable; authentication errors
trigger an optional single re-login first.
"""

import time
from dataclasses import dataclass
from typing import Callable, TypeVar

from ..defaults import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_REAUTH_ONCE,
    DEFAULT_RETRY_BACKOFF,
    DEFAULT_RETRY_BASE_DELAY_MS,
)
from ..exceptions import AdapterAuthError, AdapterError, AdapterNetworkError, AdapterRateLimitError

T = TypeVar("T")


@dataclass
class RetryPolicy:
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_delay_ms: int = DEFAULT_RETRY_BASE_DELAY_MS
    backoff: float = DEFAULT_RETRY_BACKOFF
    reauth_once: bool = DEFAULT_REAUTH_ONCE

    @staticmethod
    def is_retryable(exc: BaseException) -> bool:
        return isinstance(exc, (AdapterRateLimitError, AdapterNetworkError))

    def delay_ms(self, attempt: int) -> int:
        """Delay before retry ``attempt`` (1-based)."""
        return int(self.base_delay_ms * (self.backoff ** max(0, attempt - 1)))

    def wait(self, attempt: int) -> None:
        delay = self.delay_ms(attempt)
        if delay > 0:
            time.sleep(delay / 1000.0)

    def run(
        self,
        fn: Callable[[], T],
        *,
        reauth: Callable[[], None] | None = None,
    ) -> T:
        """Run ``fn`` with bounded retries.

        ``reauth`` is called at most once when an auth error occurs (if
        ``reauth_once`` is enabled); if it still fails the auth error is raised.
        """
        last_exc: AdapterError | None = None
        reauth_done = False

        for attempt in range(1, self.max_attempts + 1):
            try:
                return fn()
            except AdapterAuthError:
                if self.reauth_once and reauth is not None and not reauth_done:
                    reauth_done = True
                    reauth()
                    continue
                raise
            except AdapterError as exc:
                last_exc = exc
                if not self.is_retryable(exc) or attempt >= self.max_attempts:
                    raise
                self.wait(attempt)

        assert last_exc is not None  # loop always raises before falling through
        raise last_exc


__all__ = ["RetryPolicy"]
