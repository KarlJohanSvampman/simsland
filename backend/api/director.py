"""
api/director.py

REST surface for systems/director_mode.py's four live-intervention
primitives -- the backend half of VR/operator_view Phase 1 (see the
scoping conversation). Deliberately headset-agnostic: these endpoints are
what BOTH the eventual WebXR controller input and a plain desktop
operator_view test page call, so the mechanism is provable on a mouse
before a headset is involved at all.

POST /director/start_session      {char_id}
POST /director/interrupt_attention {char_id}
POST /director/inject_line        {char_id, text}
POST /director/set_preference     {char_id, field, value}
POST /director/end_session        {char_id}
POST /director/call_attention_radius {x, y, radius}
GET  /director/log                 -> recent world["director_log"] entries
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from db import load_world, save_world, world_lock
from systems import director_mode

router = APIRouter(prefix="/director", tags=["director"])

DEFAULT_SIM_ID = "default"


def _get_character(world, char_id):
    return world.get("characters", {}).get(char_id)


@router.post("/start_session")
def start_session(payload: dict, sim_id: str = DEFAULT_SIM_ID):
    with world_lock():
        world = load_world(sim_id)
        c = _get_character(world, payload.get("char_id"))
        if not c:
            return JSONResponse({"error": "character not found"}, status_code=404)
        session = director_mode.start_director_session(c, world)
        save_world(sim_id, world)
        return {"ok": True, "session": session}


@router.post("/interrupt_attention")
def interrupt_attention(payload: dict, sim_id: str = DEFAULT_SIM_ID):
    with world_lock():
        world = load_world(sim_id)
        c = _get_character(world, payload.get("char_id"))
        if not c:
            return JSONResponse({"error": "character not found"}, status_code=404)
        director_mode.interrupt_attention(c, world)
        save_world(sim_id, world)
        return {"ok": True}


@router.post("/inject_line")
def inject_line(payload: dict, sim_id: str = DEFAULT_SIM_ID):
    with world_lock():
        world = load_world(sim_id)
        c = _get_character(world, payload.get("char_id"))
        if not c:
            return JSONResponse({"error": "character not found"}, status_code=404)
        ok = director_mode.inject_line(c, world, payload.get("text", ""))
        save_world(sim_id, world)
        return {"ok": ok}


@router.post("/set_preference")
def set_preference(payload: dict, sim_id: str = DEFAULT_SIM_ID):
    with world_lock():
        world = load_world(sim_id)
        c = _get_character(world, payload.get("char_id"))
        if not c:
            return JSONResponse({"error": "character not found"}, status_code=404)
        ok = director_mode.set_preference(c, world, payload.get("field"), payload.get("value"))
        save_world(sim_id, world)
        if not ok:
            return JSONResponse({"error": "field missing or value type not allowed"}, status_code=400)
        return {"ok": True, "pending_changes": c.get("_director_session", {}).get("pending_changes", {})}


@router.post("/end_session")
def end_session(payload: dict, sim_id: str = DEFAULT_SIM_ID):
    with world_lock():
        world = load_world(sim_id)
        c = _get_character(world, payload.get("char_id"))
        if not c:
            return JSONResponse({"error": "character not found"}, status_code=404)
        changed = director_mode.end_director_session(c, world)
        save_world(sim_id, world)
        return {"ok": True, "changed_fields": changed}


@router.post("/call_attention_radius")
def call_attention_radius(payload: dict, sim_id: str = DEFAULT_SIM_ID):
    with world_lock():
        world = load_world(sim_id)
        try:
            x = float(payload.get("x"))
            y = float(payload.get("y"))
            radius = float(payload.get("radius", 5))
        except (TypeError, ValueError):
            return JSONResponse({"error": "x, y, and radius must be numbers"}, status_code=400)
        affected = director_mode.call_attention_radius(world, x, y, radius)
        save_world(sim_id, world)
        return {"ok": True, "affected": affected}


@router.get("/log")
def get_log(sim_id: str = DEFAULT_SIM_ID, limit: int = 50):
    world = load_world(sim_id)
    log = world.get("director_log", [])
    return {"log": log[-limit:]}
