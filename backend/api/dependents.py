"""
api/dependents.py

Per-character dependents summary for the Life tab's Dependents section --
each real entry in c["dependents"] (systems/child_care.py::
_sync_dependents), resolved into a real whereabouts summary (last known
location, last real contact, expected activity from their own schedule,
current caretaker if not with this parent, expected-home-today) via
systems/dependent_tracking.py::get_dependents_summary().

Character data reaches the frontend over the WS snapshot/delta protocol,
and c["dependents"] itself IS part of that (it's a plain list of ids on
the character dict) -- but the resolved summary requires cross-character
lookups (each child's own live state, conversations, schedule) that
aren't something the frontend should re-derive itself, so this mirrors
api/finances.py's shape: a plain REST poll computed from the real
backend logic, not a WS addition.
"""

from fastapi import APIRouter

from db import load_world

router = APIRouter()


@router.get("/dependents/{character_id}")
def get_character_dependents(character_id: str, sim_id: str = "default"):
    world = load_world(sim_id)
    c = world.get("characters", {}).get(character_id)
    if not c:
        return {"ok": False, "error": "character not found"}

    from systems.dependent_tracking import get_dependents_summary
    summaries = get_dependents_summary(c, world)

    chars = world.get("characters", {})
    for s in summaries:
        child = chars.get(s["child_id"])
        s["name"] = child.get("name", s["child_id"]) if child else s["child_id"]
        s["age"] = child.get("age") if child else None

    return {"ok": True, "dependents": summaries}
