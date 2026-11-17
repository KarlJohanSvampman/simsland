"""
api/persona.py -- a live character's persona, for the inspector's Persona tab (and later, director mode).

    GET  /api/characters/{id}/persona   traits, speech quirks, insecurities, confidence sources, the per-mood trait
                                        table (with every mood there is), and the trait change log
    POST /api/characters/{id}/persona   change any of those; a change to the traits by hand is logged as such

See systems/personality_profile.py.
"""

from fastapi import APIRouter

from core.commands import command
from db import load_world, save_world, world_lock

router = APIRouter()


@router.get("/characters/{char_id}/persona")
def get_persona(char_id: str, sim_id: str = "default"):
    world = load_world(sim_id)
    c = (world.get("characters") or {}).get(char_id)
    if not c:
        return {"ok": False, "error": "character not found"}
    from systems.personality_profile import read
    return {"ok": True, **read(c, world)}


@router.post("/characters/{char_id}/persona")
@command("persona.update", entities=lambda a: [("characters", a["char_id"])])
def update_persona(char_id: str, payload: dict, sim_id: str = "default"):
    from systems.personality_profile import update
    with world_lock():
        world = load_world(sim_id)
        c = (world.get("characters") or {}).get(char_id)
        if not c:
            return {"ok": False, "error": "character not found"}
        out = update(c, world, payload or {}, why=(payload or {}).get("why") or "set by hand")
        from sim_loop import _mark_dirty
        _mark_dirty(world, char_ids=[char_id])
        save_world(sim_id, world)
    return {"ok": True, **out}
