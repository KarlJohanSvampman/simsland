"""
api/debug.py

Stateless developer debug endpoints. Never touch the live simulation.

GET  /debug          → serve debug.html
POST /debug/build-context      → run context builder on dummy entities
POST /debug/llm-test           → build context + call LLM
POST /debug/generate-schedule  → run schedule generator
POST /debug/plan-activity      → show activity phases for intention + props
"""

import json
import time
import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from pathlib import Path


router = APIRouter(prefix="/debug", tags=["debug"])

# ─── Defaults ─────────────────────────────────────────────────────────────────

_WORLD_SKELETON: Dict[str, Any] = {
    "tick": 100,
    "calendar": {
        "weekday": "monday", "hour": 9, "minute": 0,
        "timestamp": 0,
    },
    "characters": {},
    "households": {},
    "homes": {},
    "vacant_homes": [],
    "events": [],
    "props": {},
    "buildings": {},
    "rooms": {},
    "conversations": {},
    "conflicts": {},
    "social_contracts": {},
    "news_feed": [],
    "environment": {"cost_of_living_index": 1.0, "tax_rate": 0.2},
    "market": {},
    "mail": {},
    "mailboxes": {},
    "services": {},
    "businesses": {},
}

_CHAR_SKELETON: Dict[str, Any] = {
    "id": "debug_char",
    "name": "Debug Sim",
    "age": 28,
    "traits": [],
    "occupation": "none",
    "hourly_wage": 15.0,
    "emotion": "neutral",
    "energy": 80,
    "stress": 20,
    "wealth": 500.0,
    "needs": {"hunger": 20, "bladder": 10, "fatigue": 15},
    "body": {"bladder": 10, "fatigue": 15, "hygiene": 90, "hunger": 20},
    "relationships": {},
    "beliefs": {},
    "memories": [],
    "grievances": [],
    "social_contract_ids": [],
    "cold_shoulder_towards": [],
    "_confrontation_emitted": [],
    "recent_behavior_tags": [],
    "active_intentions": [],
    "persistent_desires": [],
    "phone_notifications": [],
    "narratives": [],
    "self_model": {},
    "social_models": {},
    "schedule": {},
    "active_schedule_block": None,
    "current_intention": None,
    "household_id": None,
    "building_id": None,
    "room_id": None,
    "perception": {"visible_props": [], "visible_people": []},
    "attention": {"salience": {}},
    "activity_queue": [],
    "suspended_hobby_sessions": [],
}


def _build_world(patch: dict) -> dict:
    world = {**_WORLD_SKELETON, "calendar": {**_WORLD_SKELETON["calendar"]}}
    world["calendar"]["timestamp"] = time.time()
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(world.get(k), dict):
            world[k] = {**world[k], **v}
        else:
            world[k] = v
    return world


def _build_char(patch: dict) -> dict:
    c = {**_CHAR_SKELETON}
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(c.get(k), dict):
            c[k] = {**c[k], **v}
        else:
            c[k] = v
    return c


# ─── Request models ────────────────────────────────────────────────────────────

class CharWorldReq(BaseModel):
    character: Dict[str, Any] = {}
    world: Dict[str, Any] = {}


class LLMTestReq(BaseModel):
    character: Dict[str, Any] = {}
    world: Dict[str, Any] = {}
    system_prompt_override: Optional[str] = None
    use_cache: bool = False


class ScheduleReq(BaseModel):
    character: Dict[str, Any] = {}
    household: Optional[Dict[str, Any]] = None
    world: Dict[str, Any] = {}


class ActivityPlanReq(BaseModel):
    intention_type: str = "relax"
    character: Dict[str, Any] = {}
    props: Dict[str, Any] = {}
    world: Dict[str, Any] = {}


# ─── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/architecture")
def architecture_page():
    path = Path(__file__).parent.parent / "frontend" / "architecture.html"
    if path.exists():
        return FileResponse(path)
    return JSONResponse({"error": "architecture.html not found"}, status_code=404)


@router.get("")
@router.get("/")
def debug_page():
    path = Path(__file__).parent.parent / "frontend" / "debug.html"
    if path.exists():
        return FileResponse(path)
    return JSONResponse({"error": "debug.html not found"}, status_code=404)


@router.post("/build-context")
def build_context_ep(req: CharWorldReq):
    from brain.context_builder import build_context
    from systems.schema_defaults import ensure_world_defaults

    world = _build_world(req.world)
    c = _build_char(req.character)
    ensure_world_defaults(world)
    world["characters"][c["id"]] = c

    errors: Dict[str, str] = {}
    context: Dict[str, Any] = {}
    try:
        context = build_context(c, world)
    except Exception as e:
        errors["build_context"] = f"{type(e).__name__}: {e}"
        _partial_context(c, world, context, errors)

    return {"context": context, "errors": errors}


def _partial_context(c, world, out, errors):
    from brain.context_builder import (
        build_relationship_context, build_grievance_context,
        build_conflict_context, build_social_context,
        build_available_actions, build_intentions,
        build_memory_context, build_body_context,
    )
    sections = [
        ("identity",          lambda: {"name": c.get("name"), "traits": c.get("traits")}),
        ("internal_state",    lambda: {"emotion": c.get("emotion"), "energy": c.get("energy")}),
        ("relationships",     lambda: build_relationship_context(c, world)),
        ("grievances",        lambda: build_grievance_context(c, world)),
        ("active_conflict",   lambda: build_conflict_context(c, world)),
        ("social",            lambda: build_social_context(c, world)),
        ("available_actions", lambda: build_available_actions(c, world)),
        ("active_intentions", lambda: build_intentions(c)),
        ("memories",          lambda: build_memory_context(c)),
        ("body_state",        lambda: build_body_context(c)),
    ]
    for name, fn in sections:
        if name not in out:
            try:
                out[name] = fn()
            except Exception as e:
                errors[name] = f"{type(e).__name__}: {e}"


@router.post("/llm-test")
async def llm_test_ep(req: LLMTestReq):
    from brain.context_builder import build_context
    from brain.llm_brain import SYSTEM_PROMPT, validate_response
    from llm.llm_client import call_llm
    from systems.schema_defaults import ensure_world_defaults

    world = _build_world(req.world)
    c = _build_char(req.character)
    ensure_world_defaults(world)
    world["characters"][c["id"]] = c

    ctx_errors: Dict[str, str] = {}
    context: Dict[str, Any] = {}
    try:
        context = build_context(c, world)
    except Exception as e:
        ctx_errors["build_context"] = f"{type(e).__name__}: {e}"
        _partial_context(c, world, context, ctx_errors)

    system_prompt = req.system_prompt_override or SYSTEM_PROMPT
    user_prompt = json.dumps(context, indent=2, default=str)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]

    t0 = time.time()
    raw_response: Any = None
    parse_error: Optional[str] = None
    parsed: Optional[Dict] = None
    valid = False

    try:
        raw_response = await asyncio.wait_for(
            call_llm(messages, use_cache=req.use_cache),
            timeout=60,
        )
        if isinstance(raw_response, dict):
            parsed = raw_response
        elif isinstance(raw_response, str):
            try:
                parsed = json.loads(raw_response)
            except Exception as pe:
                parse_error = str(pe)
        if parsed:
            valid = validate_response(parsed)
    except Exception as e:
        parse_error = f"{type(e).__name__}: {e}"

    elapsed = round(time.time() - t0, 2)

    return {
        "context":        context,
        "context_errors": ctx_errors,
        "system_prompt":  system_prompt,
        "user_prompt":    user_prompt,
        "raw_response":   raw_response,
        "parsed_action":  parsed,
        "parse_error":    parse_error,
        "valid":          valid,
        "elapsed_s":      elapsed,
    }


@router.post("/generate-schedule")
def generate_schedule_ep(req: ScheduleReq):
    from systems.scheduling import generate_week_schedule
    from systems.schema_defaults import ensure_world_defaults

    world = _build_world(req.world)
    c = _build_char(req.character)
    ensure_world_defaults(world)

    if req.household:
        hid = req.household.get("id", "debug_household")
        req.household["id"] = hid
        req.household.setdefault("members", [c["id"]])
        req.household.setdefault("weekly_expenses", 950)
        world["households"][hid] = req.household
        c["household_id"] = hid

    world["characters"][c["id"]] = c

    errors: Dict[str, str] = {}
    schedule: Dict[str, Any] = {}
    try:
        schedule = generate_week_schedule(c, world)
    except Exception as e:
        errors["generate"] = f"{type(e).__name__}: {e}"

    return {"schedule": schedule, "character": c, "errors": errors}


@router.post("/plan-activity")
def plan_activity_ep(req: ActivityPlanReq):
    from systems.activities import INTERACTION_ANIMATIONS
    from systems.schema_defaults import ensure_world_defaults

    world = _build_world(req.world)
    world["props"].update(req.props)
    c = _build_char(req.character)
    ensure_world_defaults(world)
    world["characters"][c["id"]] = c

    c["perception"]["visible_props"] = [
        {
            "id":           pid,
            "template":     p.get("template", pid),
            "tags":         p.get("tags", []),
            "interactions": p.get("interactions", []),
            "distance":     p.get("distance", 2.0),
        }
        for pid, p in req.props.items()
    ]

    errors: Dict[str, str] = {}

    prop_phases: List[Dict] = []
    for prop_id, prop in req.props.items():
        for interaction in prop.get("interactions", []):
            phases = INTERACTION_ANIMATIONS.get(interaction)
            if phases:
                prop_phases.append({
                    "prop_id":     prop_id,
                    "prop_tags":   prop.get("tags", []),
                    "interaction": interaction,
                    "phases": {
                        phase: (anim if isinstance(anim, list) else [anim])
                        for phase, anim in phases.items()
                    },
                })

    all_interactions = {
        interaction: {
            phase: (anim if isinstance(anim, list) else [anim])
            for phase, anim in phases.items()
        }
        for interaction, phases in INTERACTION_ANIMATIONS.items()
    }

    return {
        "intention_type":   req.intention_type,
        "prop_phases":      prop_phases,
        "all_interactions": all_interactions,
        "errors":           errors,
    }
