"""
The character's OWN view of other people (directed edges, Kimberly -> Dennis).

This deliberately exposes nothing but the edge and the other person's name.
Their memories, beliefs, intentions and private thoughts are never read here
-- see the cross-character leakage rule in the spec (section 6).
"""

from __future__ import annotations

from typing import Any, Dict

from ..provider import DataProvider, ResolveContext


async def relationships(ctx: ResolveContext) -> Dict[str, Dict[str, Any]]:
    resp = await ctx.section("character")
    c = resp["character"]
    people = resp.get("people") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for other_id, r in (c.get("relationships") or {}).items():
        out[other_id] = {
            "name": (people.get(other_id) or {}).get("name") or other_id,
            "age": (people.get(other_id) or {}).get("age"),
            "trust": r.get("trust", 0), "friendship": r.get("friendship", 0),
            "familiarity": r.get("familiarity", 0), "respect": r.get("respect", 0),
            "labels": list(r.get("labels") or []),
            "authority_over": bool(r.get("authority_over")),
            "designation": r.get("designation"),
        }
    return out


PROVIDERS = [
    DataProvider("character.relationships", relationships, sections=("character",)),
]
