"""
api/admin.py

Server-side admin controls -- currently just time-scale (see main.py's
loop(), sim_loop.py::advance_calendar(), systems/movement.py). Deliberately
its own small router (not folded into api/debug.py, which is explicitly
"never touch the live simulation") so it's easy to extend with more admin
controls later without growing an unrelated file.

GET  /admin/state       -> current time_scale + simulated calendar
POST /admin/time_scale   -> set time_scale (clamped 1-10)
"""

from fastapi import APIRouter

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
