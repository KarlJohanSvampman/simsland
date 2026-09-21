"""
Async, dependency-aware data resolution (spec section 7.2).

Given the semantic types a decision needs, the resolver
  1. expands them with their transitive dependencies,
  2. groups them into waves (a type runs one wave after its last dependency),
  3. runs each wave concurrently with asyncio.gather.

A failing provider never sinks the decision: its error is recorded, providers
that depend on it are skipped, and everything else still resolves.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from ..simulation.client import SimulationClient
from .provider import ResolveContext
from .registry import Registry


class DependencyCycle(RuntimeError):
    pass


@dataclass
class Resolution:
    values: Dict[str, Any] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)
    waves: List[List[str]] = field(default_factory=list)
    cache_hits: List[str] = field(default_factory=list)

    def get(self, type_name: str, default: Any = None) -> Any:
        return self.values.get(type_name, default)


class TTLCache:
    """Tiny per-(character, type) cache. Simsland stays authoritative; this only
    trims load for slow-changing data. `clock` is injectable for tests."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._data: Dict[Tuple[str, str], Tuple[float, Any]] = {}

    def get(self, char_id: str, type_name: str) -> Tuple[bool, Any]:
        hit = self._data.get((char_id, type_name))
        if hit and hit[0] > self._clock():
            return True, hit[1]
        return False, None

    def put(self, char_id: str, type_name: str, value: Any, ttl: float) -> None:
        if ttl > 0:
            self._data[(char_id, type_name)] = (self._clock() + ttl, value)

    def clear(self) -> None:
        self._data.clear()


class Resolver:
    def __init__(self, registry: Registry, cache: Optional[TTLCache] = None):
        self.registry = registry
        self.cache = cache if cache is not None else TTLCache()

    def plan(self, types: Iterable[str]) -> List[List[str]]:
        """Waves of type names; every type appears after all of its dependencies."""
        level: Dict[str, int] = {}
        visiting: List[str] = []

        def visit(t: str) -> int:
            if t in level:
                return level[t]
            if t in visiting:
                raise DependencyCycle(" -> ".join(visiting + [t]))
            visiting.append(t)
            deps = self.registry.get(t).depends_on  # raises UnknownDataType
            level[t] = 1 + max((visit(d) for d in deps), default=0)
            visiting.pop()
            return level[t]

        for t in types:
            visit(t)
        waves: Dict[int, List[str]] = {}
        for t, lv in level.items():
            waves.setdefault(lv, []).append(t)
        return [sorted(waves[lv]) for lv in sorted(waves)]

    async def resolve(self, types: Iterable[str], sim: SimulationClient, char_id: str) -> Resolution:
        waves = self.plan(list(types))
        ctx = ResolveContext(char_id=char_id, sim=sim)
        out = Resolution(waves=waves)

        for wave in waves:
            async def run(t: str) -> Tuple[str, bool, Any]:
                provider = self.registry.get(t)
                failed = [d for d in provider.depends_on if d in out.errors]
                if failed:
                    raise RuntimeError(f"dependency failed: {', '.join(failed)}")
                if provider.ttl > 0:
                    hit, value = self.cache.get(char_id, t)
                    if hit:
                        return t, True, value
                value = await provider.fetch(ctx)
                self.cache.put(char_id, t, value, provider.ttl)
                return t, False, value

            results = await asyncio.gather(*(run(t) for t in wave), return_exceptions=True)
            for t, res in zip(wave, results):
                if isinstance(res, BaseException):
                    out.errors[t] = f"{type(res).__name__}: {res}"
                    continue
                _, cached, value = res
                ctx.results[t] = value
                out.values[t] = value
                if cached:
                    out.cache_hits.append(t)
        return out
