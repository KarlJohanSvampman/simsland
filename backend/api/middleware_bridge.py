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
        available = build_available_actions(c, world)
        try:
            process_decision(c, world, req.decision, available_actions=available)
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
