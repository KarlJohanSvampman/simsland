"""Providers for facts about the character themself. Raw facts only -- no prose."""

from __future__ import annotations

from typing import Any, Dict, List

from ..provider import DataProvider, ResolveContext

MAX_INTENTIONS = 6


async def _char(ctx: ResolveContext) -> Dict[str, Any]:
    return (await ctx.section("character"))["character"]


async def identity(ctx: ResolveContext) -> Dict[str, Any]:
    c = await _char(ctx)
    return {
        "id": c.get("id"), "name": c.get("name"), "age": c.get("age"), "sex": c.get("sex"),
        "household_id": c.get("household_id"), "family_id": c.get("family_id"),
        "employed": bool(c.get("employed")), "retired": bool(c.get("retired")),
        "job": c.get("job"),
    }


async def location(ctx: ResolveContext) -> Dict[str, Any]:
    c = await _char(ctx)
    return {"building_id": c.get("building_id"), "room_id": c.get("room_id"),
            "posture": c.get("posture")}


async def traits(ctx: ResolveContext) -> Dict[str, Any]:
    c = await _char(ctx)
    return {"traits": list(c.get("traits") or []),
            "physical_traits": list(c.get("physical_traits") or [])}


async def body(ctx: ResolveContext) -> Dict[str, Any]:
    c = await _char(ctx)
    return dict(c.get("body") or {})


async def needs(ctx: ResolveContext) -> Dict[str, Any]:
    """Physical body plus long-term drives that have built up real frustration."""
    c = await _char(ctx)
    lt = c.get("lt_needs") or {}
    frustrated = sorted(
        (name for name, d in lt.items()
         if isinstance(d, dict) and (d.get("frustration") or 0) >= 0.5),
        key=lambda n: -(lt[n].get("frustration") or 0))
    return {"body": ctx.dep("character.body"), "frustrated_drives": frustrated}


async def activity(ctx: ResolveContext) -> Dict[str, Any]:
    c = await _char(ctx)
    a = c.get("activity") or {}
    return {"type": a.get("type"), "phase": a.get("phase")}


async def intentions(ctx: ResolveContext) -> List[Dict[str, Any]]:
    c = await _char(ctx)
    items = sorted(c.get("active_intentions") or [], key=lambda i: -(i.get("priority") or 0))
    return [{"type": i.get("type"), "priority": i.get("priority") or 0,
             "reason": i.get("reason"), "source": i.get("source"),
             "target_id": i.get("target_id")} for i in items[:MAX_INTENTIONS]]


async def expectations(ctx: ResolveContext) -> List[Dict[str, Any]]:
    c = await _char(ctx)
    out = []
    for key, e in (c.get("expectations") or {}).items():
        out.append({
            "id": e.get("template_id") or key, "cadence": e.get("cadence"),
            "status": e.get("status"), "frustration": e.get("frustration") or 0.0,
            "missed_count": e.get("missed_count") or 0, "streak": e.get("streak") or 0,
            "blame": list(e.get("last_missed_blame") or []),
        })
    out.sort(key=lambda e: -e["frustration"])
    return out


async def grievances(ctx: ResolveContext) -> Dict[str, Any]:
    """Grievances grouped by who caused them, with a total weight per person."""
    c = await _char(ctx)
    by_person: Dict[str, Dict[str, Any]] = {}
    for g in c.get("grievances") or []:
        who = g.get("caused_by")
        entry = by_person.setdefault(who, {"total": 0.0, "events": []})
        entry["total"] += g.get("weight") or 0.0
        entry["events"].append(g.get("event_type"))
    return by_person


async def beliefs(ctx: ResolveContext) -> Dict[str, Any]:
    c = await _char(ctx)
    held = []
    for b in c.get("held_beliefs") or []:
        held.append(b.get("text") if isinstance(b, dict) else str(b))
    mentality = c.get("mentality")
    if isinstance(mentality, dict):
        mentality = mentality.get("summary") or mentality.get("text")
    return {"held": [h for h in held if h], "mentality": mentality}


PROVIDERS = [
    DataProvider("character.identity", identity, sections=("character",),
                 endpoint="GET /mw/characters/{id}/snapshot?sections=character", ttl=30),
    DataProvider("character.location", location, sections=("character",)),
    DataProvider("character.traits", traits, sections=("character",), ttl=300),
    DataProvider("character.body", body, sections=("character",)),
    DataProvider("character.needs", needs, depends_on=("character.body",), sections=("character",)),
    DataProvider("character.activity", activity, sections=("character",)),
    DataProvider("character.intentions", intentions, sections=("character",)),
    DataProvider("character.expectations", expectations, sections=("character",)),
    DataProvider("character.grievances", grievances, sections=("character",)),
    DataProvider("character.beliefs", beliefs, sections=("character",)),
]
