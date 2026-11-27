"""Typed exceptions raised by the collection library.

Successful collection returns a ``CollectResult``; failure always raises one of
the exceptions defined here. Every exception carries source / method / attempts
context so the caller can map it to an exit code without inspecting messages.
"""

from typing import Any, Dict, Optional


class AdapterError(Exception):
    """Base class for all collection errors."""

    def __init__(
        self,
        message: str,
        *,
        source: Optional[str] = None,
        method: Optional[str] = None,
        attempts: int = 0,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.source = source
        self.method = method
        self.attempts = attempts
        self.context = context or {}

    def __str__(self) -> str:
        parts = [self.message]
        if self.source:
            parts.append(f"source={self.source}")
        if self.method:
            parts.append(f"method={self.method}")
        if self.attempts:
            parts.append(f"attempts={self.attempts}")
        return " | ".join(parts)


class AdapterAuthError(AdapterError):
    """Authentication failed or credentials are missing."""


class AdapterRateLimitError(AdapterError):
    """Rate limited by the data source; retries exhausted."""


class AdapterNetworkError(AdapterError):
    """Network / connection failure."""


class AdapterDataError(AdapterError):
    """Bad request, missing data, or unsupported SDK method."""


class AdapterNotRegisteredError(AdapterError):
    """Programming error: source was never registered."""


class MethodNotSupportedError(AdapterError):
    """Programming error: the adapter does not support the requested method."""


__all__ = [
    "AdapterError",
    "AdapterAuthError",
    "AdapterRateLimitError",
    "AdapterNetworkError",
    "AdapterDataError",
    "AdapterNotRegisteredError",
    "MethodNotSupportedError",
]
