"""Explicit adapter registry. No directory scanning or name derivation."""

from typing import Callable, Dict, Iterable, List, Optional

from .adapters.base import BaseAdapter
from .exceptions import AdapterNotRegisteredError

AdapterFactory = Callable[[], BaseAdapter]

__all__ = ["Registry", "AdapterFactory"]


class Registry:
    """Maps a source name to an adapter factory."""

    def __init__(self) -> None:
        self._factories: Dict[str, AdapterFactory] = {}

    def register(self, source: str, factory: AdapterFactory) -> None:
        key = source.lower()
        if key in self._factories:
            raise ValueError(f"适配器已注册: {source}")
        self._factories[key] = factory

    def get(self, source: str) -> AdapterFactory:
        key = source.lower()
        if key not in self._factories:
            raise AdapterNotRegisteredError(
                f"未注册的适配器: {source}", source=source
            )
        return self._factories[key]

    def has(self, source: str) -> bool:
        return source.lower() in self._factories

    def sources(self) -> List[str]:
        return sorted(self._factories)

    def __len__(self) -> int:
        return len(self._factories)
