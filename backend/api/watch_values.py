"""
/admin/watch -- the data behind VR "Watch values" (frontend/src/vrWatch.js): what can be watched on a character, and
the current values of the ones being watched (systems/watch_values.py).
"""

from fastapi import APIRouter, HTTPException

from db import load_world

router = APIRouter(prefix="/admin/watch", tags=["watch"])


def _char(world, char_id):
    c = (world.get("characters") or {}).get(char_id)
    if not c:
        raise HTTPException(404, f"no character '{char_id}'")
    return c


@router.get("/{char_id}/fields")
def watch_fields(char_id: str, group: str | None = None, sim_id: str = "default"):
    from systems.watch_values import fields
    world = load_world(sim_id)
    return fields(_char(world, char_id), world, group)


@router.get("/{char_id}/values")
def watch_values(char_id: str, paths: str = "", sim_id: str = "default"):
    from systems.watch_values import value, QUICK
    world = load_world(sim_id)
    c = _char(world, char_id)
    out = {}
    for p in [p for p in paths.split(",") if p][:40]:
        out[p] = value(c, world, p)
    return {"tick": world.get("tick", 0), "values": out, "labels": {k: v[0] for k, v in QUICK.items()}}
