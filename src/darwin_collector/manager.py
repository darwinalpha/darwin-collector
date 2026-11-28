"""AdapterManager: the public facade.

Holds the registry and executor, resolves an execution backend for the source,
and exposes a single ``collect`` entry point. Old configuration-loading methods
are intentionally absent — this is a new library with no compatibility surface.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional, Sequence, Tuple

from .adapters.base import BaseAdapter
from .backend import Backend, resolve_backend
from .defaults import DEFAULT_MAX_PARALLEL_LANES
from .exceptions import AdapterNotRegisteredError
from .executor import Executor
from .models import CollectRequest, CollectResult
from .registry import AdapterFactory, Registry

__all__ = ["AdapterManager"]


class AdapterManager:
    def __init__(self) -> None:
        self._registry = Registry()
        self._executor = Executor()
        self._instances: Dict[Tuple[str, Optional[str]], BaseAdapter] = {}

    def register(self, source: str, factory: AdapterFactory) -> None:
        self._registry.register(source, factory)

    def get_adapter(self, source: str, key: Optional[str] = None) -> BaseAdapter:
        """Get or create a reusable adapter instance for ``source``.

        ``key`` pins the instance to one credential, giving parallel lanes
        isolated sessions. Without it the original per-source cache is kept.
        """
        cache_key = (source.lower(), key)
        if cache_key not in self._instances:
            factory = self._registry.get(source)
            self._instances[cache_key] = factory()
        return self._instances[cache_key]

    def collect(self, request: CollectRequest, *, key: Optional[str] = None) -> CollectResult:
        backend: Backend = resolve_backend(request.source)
        if backend == Backend.WORKER:
            # Reserved: worker client path is not implemented in this version.
            raise NotImplementedError("worker backend 尚未实现")

        adapter = self.get_adapter(request.source, key)
        if key is not None and type(adapter).resolve_key(request.credentials) != key:
            raise ValueError("key 与 credentials 中的单个 key 不一致")

        return self._executor.execute(adapter, request)

    def collect_parallel(
        self,
        requests: Sequence[CollectRequest],
        *,
        max_workers: Optional[int] = None,
    ) -> list[CollectResult]:
        """Run single-key requests concurrently, one isolated adapter per key.

        The caller splits a download into sub-requests and gives each one
        exactly one key. Multi-key or keyless requests are rejected so serial
        rotation and parallel lanes can never overlap. Results follow input
        order; the first lane error propagates after all started lanes finish.
        """
        probes: Dict[str, BaseAdapter] = {}
        lanes: list[Tuple[CollectRequest, str]] = []
        for request in requests:
            if request.source not in probes:
                probes[request.source] = self._registry.get(request.source)()
            key = type(probes[request.source]).resolve_key(request.credentials)
            if key is None:
                raise ValueError(f"{request.source} 没有可用于并行的 API key")
            lanes.append((request, key))

        if not lanes:
            return []
        workers = max_workers if max_workers is not None else min(
            len(lanes), DEFAULT_MAX_PARALLEL_LANES
        )
        if workers < 1:
            raise ValueError("max_workers 必须为正整数")

        with ThreadPoolExecutor(max_workers=min(workers, len(lanes))) as pool:
            futures = [pool.submit(self.collect, request, key=key) for request, key in lanes]
            return [future.result() for future in futures]

    def close(self) -> None:
        """Release all cached adapter instances. Call when the host exits."""
        for adapter in self._instances.values():
            adapter.close()
        self._instances.clear()

    @property
    def sources(self):
        return self._registry.sources()
