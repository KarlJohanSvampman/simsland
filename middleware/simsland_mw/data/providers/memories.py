"""Short-term memory and recent events."""

from __future__ import annotations

from typing import Any, Dict, List

from ..provider import DataProvider, ResolveContext

MAX_MEMORIES = 6
# A character's own passing thoughts are not fed back as "memories": echoing
# them turns the model into a loop that quotes itself.
_EXCLUDED_KINDS = {"thought"}
_EVENT_KINDS = {"shared_event", "sighting", "event"}


async def recent_memories(ctx: ResolveContext) -> List[Dict[str, Any]]:
    c = (await ctx.section("character"))["character"]
    mems = [m for m in (c.get("memories") or [])
            if m.get("kind") not in _EXCLUDED_KINDS and "thought" not in (m.get("tags") or [])]
    # importance already decays with wall-clock time in Simsland; tick breaks ties toward recent.
    mems.sort(key=lambda m: (-(m.get("importance") or 0), -(m.get("tick") or 0)))
    return [{"id": m.get("id"), "text": m.get("text"), "kind": m.get("kind"),
             "people": list(m.get("people") or []), "importance": m.get("importance") or 0,
             "tick": m.get("tick")} for m in mems[:MAX_MEMORIES] if m.get("text")]


async def recent_events(ctx: ResolveContext) -> List[Dict[str, Any]]:
    mems = ctx.dep("character.recent_memories")
    return [m for m in mems if m.get("kind") in _EVENT_KINDS]


PROVIDERS = [
    DataProvider("character.recent_memories", recent_memories, sections=("character",)),
    DataProvider("events.recent", recent_events, depends_on=("character.recent_memories",),
                 sections=("character",)),
]
