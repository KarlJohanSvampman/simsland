"""The character's household: who lives there and how the money looks."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..provider import DataProvider, ResolveContext


async def _household(ctx: ResolveContext) -> Optional[Dict[str, Any]]:
    ident = ctx.dep("character.identity")
    if not ident.get("household_id"):
        return None
    return (await ctx.section("household")).get("household")


async def members(ctx: ResolveContext) -> List[Dict[str, Any]]:
    ident = ctx.dep("character.identity")
    if not ident.get("household_id"):
        return []
    resp = await ctx.section("household")
    h = resp.get("household") or {}
    people = resp.get("people") or {}
    return [{"id": m, "name": (people.get(m) or {}).get("name") or m, "is_self": m == ident["id"]}
            for m in h.get("members") or []]


async def finances(ctx: ResolveContext) -> Optional[Dict[str, Any]]:
    h = await _household(ctx)
    if h is None:
        return None
    bills = [{"name": b.get("name") or b.get("type"), "amount": b.get("amount")}
             for b in h.get("bills_due") or [] if isinstance(b, dict)]
    return {"wealth": h.get("wealth"), "weekly_expenses": h.get("weekly_expenses"),
            "loans": h.get("loans") or {}, "bills_due": bills}


async def state(ctx: ResolveContext) -> Optional[Dict[str, Any]]:
    h = await _household(ctx)
    if h is None:
        return None
    return {"name": h.get("name"), "cleanliness": h.get("cleanliness"),
            "trash_level": h.get("trash_level")}


PROVIDERS = [
    DataProvider("household.members", members, depends_on=("character.identity",), sections=("household",)),
    DataProvider("household.finances", finances, depends_on=("character.identity",), sections=("household",)),
    DataProvider("household.state", state, depends_on=("character.identity",), sections=("household",)),
]
