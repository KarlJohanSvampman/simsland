"""What is around the character right now."""

from __future__ import annotations

from typing import Any, Dict, List

from ..provider import DataProvider, ResolveContext

# Everything a bystander could observe about someone else; nothing more.
PERCEIVABLE_PERSON_KEYS = ("id", "name", "distance", "description", "activity",
                           "appears", "speaking", "smells", "breath", "direction")


def _time_of_day(hour: int) -> str:
    if hour < 5:
        return "the middle of the night"
    if hour < 9:
        return "the morning"
    if hour < 12:
        return "late morning"
    if hour < 14:
        return "midday"
    if hour < 17:
        return "the afternoon"
    if hour < 21:
        return "the evening"
    return "late at night"


async def current(ctx: ResolveContext) -> Dict[str, Any]:
    loc = ctx.dep("character.location")
    meta = (await ctx.section("meta"))["meta"]
    cal = meta.get("calendar") or {}
    hour = cal.get("hour")
    return {
        "tick": meta.get("tick"),
        "building_id": loc.get("building_id"), "room_id": loc.get("room_id"),
        "indoors": bool(loc.get("building_id")),
        "hour": hour, "minute": cal.get("minute"), "weekday": cal.get("weekday"),
        "time_of_day": _time_of_day(hour) if isinstance(hour, int) else None,
        "wake_reason": (meta.get("cognition") or {}).get("wake_reason"),
        "wake_payload": (meta.get("cognition") or {}).get("wake_payload") or {},
    }


async def room(ctx: ResolveContext) -> Dict[str, Any]:
    """The room the character is standing in, as she would simply notice it."""
    loc = ctx.dep("character.location")
    env = (await ctx.section("environment"))["environment"]
    return {"building_id": loc.get("building_id"), "room_id": loc.get("room_id"),
            "cleanliness": env.get("room_cleanliness")}


async def nearby_characters(ctx: ResolveContext) -> List[Dict[str, Any]]:
    ctx.dep("character.location")  # nobody is "nearby" without knowing where we are
    env = (await ctx.section("environment"))["environment"]
    people: List[Dict[str, Any]] = []
    for p in env.get("visible_people") or []:
        # Re-filtered here even though the bridge already strips: this layer must
        # not depend on the other side keeping the leakage rule.
        people.append({k: p[k] for k in PERCEIVABLE_PERSON_KEYS if k in p})
    people.sort(key=lambda p: p.get("distance") if p.get("distance") is not None else 999)
    return people


async def nearby_props(ctx: ResolveContext) -> List[Dict[str, Any]]:
    env = (await ctx.section("environment"))["environment"]
    props = [{"id": p.get("id"), "template": p.get("template"), "distance": p.get("distance"),
              "tags": list(p.get("tags") or []), "interactions": list(p.get("interactions") or [])}
             for p in env.get("visible_props") or [] if p.get("id")]
    props.sort(key=lambda p: p.get("distance") if p.get("distance") is not None else 999)
    return props


async def available_interactions(ctx: ResolveContext) -> Dict[str, Any]:
    """What Simsland says is currently possible. The option generator only ever
    offers an action type that appears in `action_types`."""
    a = (await ctx.section("actions")).get("available_actions") or {}
    return {"action_types": list(a.get("action_types") or []),
            "interactable_props": list(a.get("interactable_props") or []),
            "nearby_characters": list(a.get("nearby_characters") or [])}


PROVIDERS = [
    DataProvider("environment.current", current, depends_on=("character.location",),
                 sections=("meta",)),
    DataProvider("environment.room", room, depends_on=("character.location",),
                 sections=("environment",)),
    DataProvider("environment.nearby_characters", nearby_characters,
                 depends_on=("character.location",), sections=("environment",)),
    DataProvider("environment.nearby_props", nearby_props, sections=("environment",)),
    DataProvider("environment.available_interactions", available_interactions,
                 sections=("actions",)),
]
