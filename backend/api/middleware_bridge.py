"""
api/middleware_bridge.py

The ONLY surface the standalone AI middleware (../middleware) uses to talk
to Simsland. Read side: per-character snapshots split into sections so the
middleware can fetch just what a decision needs. Write side: one execute
route that applies a decision through the normal process_decision() path.

The LLM never reaches this file -- only the middleware does. Simsland stays
authoritative: every decision goes through validate_action()/route_action()
exactly as if brain/llm_brain.py had produced it.
"""

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Any, Dict, Optional

from db import load_world, save_world, world_lock
from brain import external_brain

router = APIRouter(prefix="/mw", tags=["middleware"])

SIM_ID = "default"
log = logging.getLogger(__name__)

# Big / internal keys the middleware has no use for. perception is served as
# its own "environment" section instead.
_CHAR_STRIP = ("_llm_session", "perception", "action_menu_cache", "environment_scan")

# Cross-character leakage guard, enforced at the source: a perceived person
# is reduced to what a bystander could see. Never their body, memories,
# beliefs or intentions.
_PERSON_KEYS = ("id", "name", "distance", "description", "activity",
                "appears", "speaking", "smells", "breath", "direction")

ALL_SECTIONS = ("meta", "character", "environment", "household", "actions")


def _json(payload):
    return Response(content=json.dumps(payload, default=str), media_type="application/json")


def _char_or_404(world, char_id):
    c = world.get("characters", {}).get(char_id)
    if c is None:
        raise HTTPException(status_code=404, detail=f"character '{char_id}' not found")
    return c


def _room_cleanliness(c, world):
    from systems.chores import get_room_cleanliness, zone_key_for_character
    return get_room_cleanliness(world, zone_key_for_character(c))


def _identity(c):
    return {"id": c["id"], "name": c.get("name"), "age": c.get("age"), "sex": c.get("sex")}


def _cognition(c):
    cog = c.get("cognition") or {}
    return {
        "wake_reason": cog.get("wake_reason"),
        "wake_payload": cog.get("wake_payload") or {},
        "next_think_tick": cog.get("next_think_tick", 0),
        "last_think_tick": cog.get("last_think_tick"),
        "idle_streak": cog.get("idle_streak", 0),
        "turn_budget": cog.get("turn_budget"),
    }


@router.get("/characters")
def list_characters():
    world = load_world(SIM_ID)
    tick = world.get("tick", 0)
    out = []
    for cid, c in world.get("characters", {}).items():
        cog = c.get("cognition") or {}
        out.append({
            "id": cid,
            "name": c.get("name"),
            "household_id": c.get("household_id"),
            "external_brain": bool(c.get("external_brain")),
            "due": tick >= cog.get("next_think_tick", 0),
        })
    return {"tick": tick, "characters": out}


@router.get("/due")
def due():
    """Externally-driven characters whose think tick has arrived. Polling
    this doubles as the middleware heartbeat."""
    external_brain.touch()
    world = load_world(SIM_ID)
    tick = world.get("tick", 0)
    out = []
    for cid, c in world.get("characters", {}).items():
        if not external_brain.wants_middleware(c):
            continue
        if c.get("off_grid") or c.get("travel_state"):
            continue   # away/travelling: update_agent() doesn't run them, nothing to decide
        # Confirmed live bug, the real root cause behind a run of "stuck"/
        # "spam" reports today: brain/agent_loop.py::update_agent() already
        # refuses to call think() at all while c["activity"] is set (its own
        # early "execute_activity(...); return" gate) -- but this poll and
        # POST /execute are a SEPARATE path that never goes through
        # update_agent() at all. next_think_tick reflects only the generic
        # ~45-70 tick idle cadence (brain/cognition_scheduler.py::note_think),
        # with no idea how long whatever activity was just started is
        # actually supposed to run -- so the runner kept finding a mid-
        # activity character "due" again within a minute and POSTing a fresh
        # decision, which /execute applied unconditionally, silently
        # overwriting (not completing) whatever was already in progress.
        # Simsland's own emergency-interrupt logic (bladder overriding sleep,
        # a shift starting, ...) already runs for every character every tick
        # regardless of middleware/legacy, and clears c["activity"] itself
        # when something genuinely needs to pre-empt it -- so it's safe to
        # just wait here, matching the legacy gate exactly, rather than
        # trying to guess which wake reasons should override it.
        if c.get("activity"):
            continue
        cog = c.get("cognition") or {}
        if tick >= cog.get("next_think_tick", 0):
            out.append({
                "id": cid,
                "wake_reason": cog.get("wake_reason") or "idle",
                "wake_payload": cog.get("wake_payload") or {},
            })
    return {"tick": tick, "due": out}


@router.get("/characters/{char_id}/snapshot")
def snapshot(char_id: str, sections: str = ",".join(ALL_SECTIONS)):
    external_brain.touch()
    wanted = {s.strip() for s in sections.split(",") if s.strip()}
    unknown = wanted - set(ALL_SECTIONS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown sections: {sorted(unknown)}")

    world = load_world(SIM_ID)
    c = _char_or_404(world, char_id)
    chars = world.get("characters", {})
    out: Dict[str, Any] = {"tick": world.get("tick", 0)}

    if "meta" in wanted:
        out["meta"] = {
            "tick": world.get("tick", 0),
            "calendar": world.get("calendar", {}),
            "cognition": _cognition(c),
        }

    if "character" in wanted:
        out["character"] = {k: v for k, v in c.items() if k not in _CHAR_STRIP}

    if "environment" in wanted:
        perception = c.get("perception") or {}
        people = [
            {k: p.get(k) for k in _PERSON_KEYS if k in p}
            for p in perception.get("visible_people", [])
        ]
        out["environment"] = {
            "building_id": c.get("building_id"),
            "room_id": c.get("room_id"),
            "visible_people": people,
            "visible_props": perception.get("visible_props", []),
            # Cleanliness of the room they are standing in (0 = filthy, 100 =
            # spotless) -- what a person would simply notice on walking in.
            "room_cleanliness": _room_cleanliness(c, world),
        }

    # Minimal identity for everyone this character is allowed to know about
    # (people in view, household, relationship edges). Names only -- see the
    # leakage note on _PERSON_KEYS.
    if wanted & {"environment", "household", "character"}:
        known = {p["id"] for p in (out.get("environment") or {}).get("visible_people", []) if p.get("id")}
        known |= set((c.get("relationships") or {}).keys())
        h = world.get("households", {}).get(c.get("household_id"))
        if h:
            known |= set(h.get("members", []))
        out["people"] = {i: _identity(chars[i]) for i in known if i in chars}

    if "household" in wanted:
        h = world.get("households", {}).get(c.get("household_id"))
        out["household"] = h
        out["household_market"] = world.get("market") if h else None

    if "actions" in wanted:
        from brain.context_builder import build_available_actions
        out["available_actions"] = build_available_actions(c, world)

    return _json(out)


class ExternalBrainReq(BaseModel):
    enabled: bool


@router.post("/characters/{char_id}/external_brain")
def set_external_brain(char_id: str, req: ExternalBrainReq):
    external_brain.touch()
    with world_lock():
        world = load_world(SIM_ID)
        c = _char_or_404(world, char_id)
        c["external_brain"] = bool(req.enabled)
        save_world(SIM_ID, world)
    return {"id": char_id, "external_brain": bool(req.enabled)}


class ExecuteReq(BaseModel):
    # Same "legacy decision" shape brain/llm_brain.py::_to_legacy_decision()
    # produces and process_decision() consumes: {thought, action, speech, ...}
    decision: Dict[str, Any]
    wake_reason: Optional[str] = None
    # Deliberately separate from decision["thought"] (always None -- see
    # middleware/.../executor.py::build_decision's own comment): that field
    # controls whether process_decision() writes a real, persisted memory.
    # This one is display-only -- a thought bubble the character never
    # actually "remembers" having, matching the Phase-1 design intent
    # ("the middleware decides what persists") without silently going
    # back to persisting every thought as a memory to get bubbles back.
    thought: Optional[str] = None


@router.post("/characters/{char_id}/execute")
def execute(char_id: str, req: ExecuteReq):
    external_brain.touch()
    from brain.agent_loop import process_decision, post_update
    from brain.cognition_scheduler import note_think
    from brain.context_builder import build_available_actions

    with world_lock():
        world = load_world(SIM_ID)
        c = _char_or_404(world, char_id)

        c["last_invalid_action"] = None
        if c.get("off_grid"):
            # They left while this decision was being made. Applying it now would
            # leave a stale activity on someone who is away (update_agent() never
            # runs for off-grid characters, so it would sit there forever).
            note_think(c, world, {}, wake_reason=req.wake_reason)
            save_world(SIM_ID, world)
            return {"ok": True, "tick": world.get("tick", 0), "activity_type": None,
                    "invalid_action": None, "ignored": "character is off-grid"}
        available = build_available_actions(c, world)
        try:
            process_decision(c, world, req.decision, available_actions=available)
            if req.thought:
                c["last_thought"] = req.thought
                c["last_narration"] = req.thought
            note_think(c, world, req.decision, wake_reason=req.wake_reason)
            post_update(c, world)
        except Exception as e:  # nothing is saved on failure
            log.exception("middleware execute failed for %s", char_id)
            raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
        save_world(SIM_ID, world)

        activity = c.get("activity") or {}
        return {
            "ok": True,
            "tick": world.get("tick", 0),
            "activity_type": activity.get("type"),
            "invalid_action": c.get("last_invalid_action"),
        }
