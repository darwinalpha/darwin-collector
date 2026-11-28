"""darwin-collector: configuration-free data collection library."""

from .models import CollectRequest, CollectResult, PaginationMode, Policies
from .manager import AdapterManager
from .registry import Registry
from .exceptions import (
    AdapterError,
    AdapterAuthError,
    AdapterRateLimitError,
    AdapterNetworkError,
    AdapterDataError,
    AdapterNotRegisteredError,
    MethodNotSupportedError,
)
from .backend import Backend, resolve_backend
from .policies import KeyRotationPolicy
from .key_pool import KeyPool, split_keys

__version__ = "0.1.1"

__all__ = [
    "CollectRequest",
    "CollectResult",
    "PaginationMode",
    "Policies",
    "AdapterManager",
    "Registry",
    "AdapterError",
    "AdapterAuthError",
    "AdapterRateLimitError",
    "AdapterNetworkError",
    "AdapterDataError",
    "AdapterNotRegisteredError",
    "MethodNotSupportedError",
    "Backend",
    "resolve_backend",
    "KeyRotationPolicy",
    "KeyPool",
    "split_keys",
]
