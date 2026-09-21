"""Registry of data providers. New semantic types are added here, never in the LLM contract."""

from __future__ import annotations

from typing import Dict, Iterable, List

from .provider import DataProvider


class UnknownDataType(KeyError):
    pass


class Registry:
    def __init__(self, providers: Iterable[DataProvider] = ()):
        self._providers: Dict[str, DataProvider] = {}
        for p in providers:
            self.register(p)

    def register(self, provider: DataProvider) -> DataProvider:
        if provider.type in self._providers:
            raise ValueError(f"data type already registered: {provider.type}")
        self._providers[provider.type] = provider
        return provider

    def get(self, type_name: str) -> DataProvider:
        try:
            return self._providers[type_name]
        except KeyError:
            raise UnknownDataType(type_name) from None

    def types(self) -> List[str]:
        return sorted(self._providers)

    def __contains__(self, type_name: str) -> bool:
        return type_name in self._providers


def build_default_registry() -> Registry:
    from .providers import ALL_PROVIDERS
    return Registry(ALL_PROVIDERS)
