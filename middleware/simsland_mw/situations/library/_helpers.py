"""Small resolvers shared by the seed library. Every one returns a concrete
Simsland outcome built from real, currently-available things, or None."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..definition import Outcome, SituationContext


def interact(ctx: SituationContext, kind: str) -> Optional[Outcome]:
    dc = ctx.dc
    prop = dc.find_prop(kind)
    if not prop or not dc.allowed("interact"):
        return None
    out: Outcome = {"type": "interact", "target": prop["id"]}
    interaction = dc.interaction_for(prop, kind)
    if interaction:
        out["interaction"] = interaction
    return out


def act(ctx: SituationContext, action_type: str, **extra: Any) -> Optional[Outcome]:
    """A target-less action, only if Simsland lists it as currently possible."""
    if not ctx.dc.allowed(action_type):
        return None
    return {"type": action_type, **extra}


def prop_action(ctx: SituationContext, action_type: str, kind: str) -> Optional[Outcome]:
    prop = ctx.dc.find_prop(kind)
    if not prop or not ctx.dc.allowed(action_type):
        return None
    return {"type": action_type, "target": prop["id"]}


def speak_to(ctx: SituationContext, pid: Optional[str]) -> Optional[Outcome]:
    if not pid or not ctx.person(pid) or not ctx.dc.allowed("speak"):
        return None
    return {"type": "speak", "target": pid}


def socialize_with(ctx: SituationContext, pid: Optional[str]) -> Optional[Outcome]:
    if not pid or not ctx.person(pid) or not ctx.dc.allowed("socialize"):
        return None
    return {"type": "socialize", "target": pid}


def adults_here(ctx: SituationContext) -> List[Dict[str, Any]]:
    return [p for p in ctx.dc.people if not ctx.dc.is_dependent(p["id"])]


def first_adult(ctx: SituationContext) -> Optional[str]:
    a = adults_here(ctx)
    return a[0]["id"] if a else None
