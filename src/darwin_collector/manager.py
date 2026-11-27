"""AdapterManager: the public facade.

Holds the registry and executor, resolves an execution backend for the source,
and exposes a single ``collect`` entry point. Old configuration-loading methods
are intentionally absent — this is a new library with no compatibility surface.
"""

from typing import Any, Dict, Optional

from .adapters.base import BaseAdapter
from .backend import Backend, resolve_backend
from .exceptions import AdapterNotRegisteredError
from .executor import Executor
from .models import CollectRequest, CollectResult
from .registry import AdapterFactory, Registry

__all__ = ["AdapterManager"]


class AdapterManager:
    def __init__(self) -> None:
        self._registry = Registry()
        self._executor = Executor()
        self._instances: Dict[str, BaseAdapter] = {}

    def register(self, source: str, factory: AdapterFactory) -> None:
        self._registry.register(source, factory)

    def get_adapter(self, source: str) -> BaseAdapter:
        """Get or create a reusable adapter instance for ``source``.

        Instances are cached so a long-lived host (e.g. a future worker) can
        reuse a login/session across requests. ``close()`` is the caller's job.
        """
        key = source.lower()
        if key not in self._instances:
            factory = self._registry.get(source)
            self._instances[key] = factory()
        return self._instances[key]

    def collect(self, request: CollectRequest) -> CollectResult:
        backend: Backend = resolve_backend(request.source)
        if backend == Backend.WORKER:
            # Reserved: worker client path is not implemented in this version.
            raise NotImplementedError("worker backend 尚未实现")

        adapter = self.get_adapter(request.source)
        return self._executor.execute(adapter, request)

    def close(self) -> None:
        """Release all cached adapter instances. Call when the host exits."""
        for adapter in self._instances.values():
            adapter.close()
        self._instances.clear()

    @property
    def sources(self):
        return self._registry.sources()
