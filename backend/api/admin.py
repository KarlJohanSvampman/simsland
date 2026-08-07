"""
api/admin.py

Server-side admin controls -- currently just time-scale (see main.py's
loop(), sim_loop.py::advance_calendar(), systems/movement.py) and read-only
inspection of live per-character cognition-scheduler state. Deliberately
its own small router (not folded into api/debug.py, which is explicitly
"never touch the live simulation") so it's easy to extend with more admin
controls later without growing an unrelated file.

GET  /admin/state              -> current time_scale + simulated calendar
POST /admin/time_scale          -> set time_scale (clamped 1-10)
GET  /admin/cognition           -> world-level cognition-scheduler histogram
GET  /admin/cognition/{char_id} -> one character's live cognition state
POST /admin/reset_characters    -> wipe all characters/households (keeps
                                    the hand-placed map/buildings/roads)
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from db import load_world, save_world, world_lock

router = APIRouter(prefix="/admin", tags=["admin"])

DEFAULT_SIM_ID = "default"


@router.get("/state")
def get_state(sim_id: str = DEFAULT_SIM_ID):
    world = load_world(sim_id)
    return {
        "time_scale": world.get("time_scale", 1),
        "calendar":   world.get("calendar", {}),
    }


@router.post("/time_scale")
def set_time_scale(payload: dict, sim_id: str = DEFAULT_SIM_ID):
    value = max(1, min(10, int(payload.get("value", 1))))
    with world_lock():
        world = load_world(sim_id)
        world["time_scale"] = value
        save_world(sim_id, world)
    return {"time_scale": value}


@router.post("/reset_characters")
def reset_characters(sim_id: str = DEFAULT_SIM_ID):
    """Wipes all characters and households -- the map/buildings/roads/props
    are hand-placed via the World Editor and aren't code-regenerable, so
    this deliberately leaves them untouched, only unassigning each
    building's owner_household_id since the households that owned them no
    longer exist."""
    with world_lock():
        world = load_world(sim_id)
        world["characters"] = {}
        world["households"] = {}
        for building in world.get("buildings", []):
            building["owner_household_id"] = None
        save_world(sim_id, world)
    return {"ok": True}


@router.get("/cognition")
def get_cognition_histogram(sim_id: str = DEFAULT_SIM_ID):
    world = load_world(sim_id)
    tick = world.get("tick", 0)
    characters = world.get("characters", {})

    wake_reason_counts: dict = {}
    idle_streak_total = 0
    due_now = 0
    n = 0
    for c in characters.values():
        cog = c.get("cognition")
        if cog is None:
            continue
        n += 1
        reason = cog.get("wake_reason")
        if reason:
            wake_reason_counts[reason] = wake_reason_counts.get(reason, 0) + 1
        idle_streak_total += cog.get("idle_streak", 0)
        if tick >= cog.get("next_think_tick", 0):
            due_now += 1

    # Instantaneous snapshot above (what's pending right now) + Round 10's
    # rolling in-process counters below (what's actually been happening —
    # think()s/tick, wake-reason histogram of fired thinks, prompt size,
    # resolver accept/ambiguous/fail rates, describe/recall usage) — see
    # brain/cognition_scheduler.py's get_stats(). The rolling counters are
    # process-lifetime, not filtered by sim_id (this deployment only ever
    # runs one sim per process today).
    from brain.cognition_scheduler import get_stats
    return {
        "tick": tick,
        "character_count": n,
        "pending_wake_reasons": wake_reason_counts,
        "due_now": due_now,
        "mean_idle_streak": round(idle_streak_total / n, 2) if n else 0,
        "rolling": get_stats(),
    }


@router.get("/cognition/{char_id}")
def get_cognition_for_char(char_id: str, sim_id: str = DEFAULT_SIM_ID):
    world = load_world(sim_id)
    c = world.get("characters", {}).get(char_id)
    if not c:
        return JSONResponse({"error": f"character '{char_id}' not found"}, status_code=404)
    return {
        "tick": world.get("tick", 0),
        "cognition": c.get("cognition", {}),
    }
