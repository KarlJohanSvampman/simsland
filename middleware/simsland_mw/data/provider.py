"""
Data provider primitives (spec section 7).

A *data type* is a semantic name such as "character.needs". A DataProvider
knows how to fetch and extract that type from Simsland, and declares which
other types it depends on. Providers return plain JSON-ish "facts" (numbers,
ids, lists) -- turning those into language is the narrative layer's job, and
deciding what a character is *allowed* to know is the perception filter's.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from ..simulation.client import SimulationClient


class MissingDependency(KeyError):
    """A provider read a dependency it did not declare in `depends_on`."""


@dataclass
class ResolveContext:
    """Per-decision scratch space handed to every provider."""

    char_id: str
    sim: SimulationClient
    results: Dict[str, Any] = field(default_factory=dict)
    _sections: Dict[str, "asyncio.Future[Dict[str, Any]]"] = field(default_factory=dict, repr=False)

    async def section(self, name: str) -> Dict[str, Any]:
        """Fetch one Simsland snapshot section. Memoized and single-flight, so
        five providers that all read "character" cost one HTTP request even
        when they run concurrently in the same wave."""
        fut = self._sections.get(name)
        if fut is None:
            fut = asyncio.ensure_future(self.sim.snapshot(self.char_id, [name]))
            self._sections[name] = fut
        return await fut

    def dep(self, type_name: str) -> Any:
        """Result of an already-resolved dependency."""
        if type_name not in self.results:
            raise MissingDependency(
                f"{type_name} is not resolved -- add it to the provider's depends_on")
        return self.results[type_name]


Fetch = Callable[[ResolveContext], Awaitable[Any]]


@dataclass(frozen=True)
class DataProvider:
    type: str
    fetch: Fetch
    depends_on: Tuple[str, ...] = ()
    # Documentation of where the data comes from (Simsland bridge section).
    sections: Tuple[str, ...] = ()
    endpoint: str = ""
    # Seconds. 0 = never cached (position, needs, activity, money);
    # long for things that barely change (traits, identity). Spec 7.4.
    ttl: float = 0.0
    description: str = ""
