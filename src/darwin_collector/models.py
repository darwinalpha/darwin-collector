"""Request / result data contracts.

The library only accepts already-parsed parameters. It never reads config
files, environment variables, or writes results anywhere.
"""

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Dict, List, Optional

import pandas as pd

from .policies import KeyRotationPolicy, Paginator, RateLimitPolicy, RetryPolicy
from .types import PaginationMode

__all__ = ["PaginationMode", "Policies", "CollectRequest", "CollectResult"]


@dataclass
class Policies:
    """Optional policy overrides. ``None`` fields use library defaults."""

    retry: Optional[RetryPolicy] = None
    rate_limit: Optional[RateLimitPolicy] = None
    paginator: Optional[Paginator] = None
    pagination_mode: Optional[PaginationMode] = None
    key_rotation: Optional[KeyRotationPolicy] = None


@dataclass
class CollectRequest:
    """Everything needed for one collection task, already resolved by caller."""

    source: str
    method: str
    params: Dict[str, Any] = field(default_factory=dict)
    options: Dict[str, Any] = field(default_factory=dict)
    credentials: Optional[Dict[str, Any]] = None
    policies: Optional[Policies] = None
    fake: bool = False


@dataclass
class CollectResult:
    """Collection outcome. No file path, cleaning config or write state."""

    source: str
    method: str
    frames: List[pd.DataFrame] = field(default_factory=list)
    attempts: int = 1
    elapsed_ms: float = 0.0
    fake: bool = False

    def to_dataframe(self) -> pd.DataFrame:
        """Default contract: merge all chunks into one DataFrame."""
        if not self.frames:
            return pd.DataFrame()
        if len(self.frames) == 1:
            return self.frames[0]
        return pd.concat(self.frames, ignore_index=True)

    def to_records(self) -> List[Dict[str, Any]]:
        """Optional view: records generated lazily from the DataFrame."""
        return self.to_dataframe().to_dict(orient="records")

    @property
    def row_count(self) -> int:
        return sum(len(frame) for frame in self.frames)

    @property
    def chunk_count(self) -> int:
        return len(self.frames)


def result_from_frame(
    frame: pd.DataFrame,
    request: CollectRequest,
    *,
    attempts: int = 1,
    started: Optional[float] = None,
) -> CollectResult:
    elapsed = 0.0
    if started is not None:
        elapsed = (perf_counter() - started) * 1000.0
    return CollectResult(
        source=request.source,
        method=request.method,
        frames=[frame],
        attempts=attempts,
        elapsed_ms=elapsed,
        fake=request.fake,
    )
