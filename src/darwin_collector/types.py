"""Shared lightweight enums. Kept separate to avoid import cycles between
models and policies.
"""

from enum import Enum

__all__ = ["PaginationMode"]


class PaginationMode(str, Enum):
    NONE = "none"
    ADAPTER = "adapter"
    FRAMEWORK = "framework"
