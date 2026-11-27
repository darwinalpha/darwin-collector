"""Execution backend selection.

A worker is an optional backend that hosts reusable adapter instances across
processes. The branch is reserved here, but no worker is implemented in this
version: ``resolve_backend`` always returns ``DIRECT``. Everything else in the
library is agnostic to which process runs the collection.
"""

from enum import Enum

__all__ = ["Backend", "resolve_backend"]


class Backend(str, Enum):
    DIRECT = "direct"
    WORKER = "worker"


def resolve_backend(source: str) -> Backend:
    """Return the execution backend for ``source``.

    Always ``DIRECT`` today. When a per-source worker exists this is the single
    place to switch to ``WORKER``; no caller or adapter needs to change.
    """
    return Backend.DIRECT
