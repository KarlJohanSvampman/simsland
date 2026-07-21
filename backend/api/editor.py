from fastapi import APIRouter, HTTPException, Request
from pathlib import Path
import json
import uuid
import asyncio

from db import load_world, save_world, refresh_static_world_cache, _STATIC_WORLD_KEYS, world_lock
from core.definitions import load_definitions as _load_defs_core, invalidate_definitions_cache

from systems.navigation import cache_floorplan
from systems.character_gen import generate_character

router = APIRouter()

@router.get("/world")
def get_world(sim_id: str):
    return load_world(sim_id)

@router.post("/world")
def save(sim_id: str, data: dict):
    # world_tiles and its derived nav structures (world_tile_lookup,
    # outdoor_navigation, road_graph, etc.) are deliberately excluded from
    # the persisted world blob everywhere else (see main.py::loop()) so that
    # load_world() always rebuilds them from the process-local static cache
    # instead of serving a snapshot straight from Redis/Postgres. The editor
    # posts the full merged world dict back (it round-trips whatever
    # loadWorld() gave it), which would otherwise smuggle stale derived nav
    # data into persistence and get served ahead of the freshly-rebuilt
    # cache below. Strip them before persisting; keep the human-edited
    # world_tiles only to refresh the process-local cache.
    world_tiles = data.get("world_tiles")
    persisted = {k: v for k, v in data.items() if k not in _STATIC_WORLD_KEYS}
    with world_lock():
        save_world(sim_id, persisted)
    refresh_static_world_cache(sim_id, world_tiles)
    return {"status": "ok"}


BASE = Path("/data/simulations")

def defs_path(sim_id):
    return BASE / sim_id / "definitions.json"


# =====================================
# LOAD DEFINITIONS
# =====================================

@router.get("/definitions")
def load_definitions(sim_id: str):
    path = defs_path(sim_id)
    if not path.exists():
        return {
            "prop_templates":         {},
            "item_templates":         {},
            "character_templates":    {},
            "trait_templates":        {},
            "need_templates":         {},
            "mood_templates":         {},
            "activity_templates":     {},
            "interaction_templates":  {},
            "recipe_templates":       {},
            "service_templates":      {},
            "job_templates":          {},
            "company_templates":      {},
            "vehicle_templates":      {},
            "floorplan_templates":    {},
            "tile_templates":         {},
            "wall_segment_templates": {},
            "material_templates":     {},
        }
    with open(path, "r") as f:
        defs = json.load(f)
    floorplans = defs.get("floorplan_templates", {})
    for fp_id, fp in floorplans.items():
        if "id" not in fp:
            fp["id"] = fp_id
        try:
            cache_floorplan(fp_id, fp)
        except Exception as e:
            print(f"Failed to cache floorplan {fp_id}:", e)
    return defs


# =====================================
# SAVE DEFINITIONS
# =====================================

@router.post("/definitions")
async def save_definitions(sim_id: str, request: Request):
    data = await request.json()
    path = defs_path(sim_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file then atomically replace — writing the real
    # path in place left a window where a concurrent reader (main.py's
    # tick loop now reloads definitions every tick, not just once at
    # startup) could open the file mid-write and hit a torn/truncated
    # JSONDecodeError. os.replace() is atomic on both POSIX and Windows,
    # so a reader always sees either the fully-old or fully-new file.
    import os
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)
    floorplans = data.get("floorplan_templates", {})
    for fp_id, fp in floorplans.items():
        if "id" not in fp:
            fp["id"] = fp_id
        cache_floorplan(fp_id, fp)
    invalidate_definitions_cache(sim_id)
    return {"ok": True}


# =====================================
# SPAWN CHARACTER
# =====================================

def _spawn_character_locked(sim_id, template_id, x, y, body):
    """Runs on a background thread (see spawn_character below) — holds
    world_lock() for its whole load_world->mutate->save_world span, same
    as every other world-mutating route."""
    defs = load_definitions(sim_id)
    with world_lock():
        world = load_world(sim_id)

        if template_id:
            tmpl = defs.get("character_templates", {}).get(template_id)
            if not tmpl:
                raise HTTPException(status_code=404,
                                    detail=f"Character template '{template_id}' not found")
            cid  = f"char_{uuid.uuid4().hex[:8]}"
            name = tmpl.get("name") or template_id.replace("_", " ").title()
            overrides = {
                "id": cid, "x": x, "y": y, "template": template_id, "name": name,
            }
            if tmpl.get("model"):    overrides["model"]  = tmpl["model"]
            if tmpl.get("traits"):   overrides["traits"] = tmpl["traits"]
            if tmpl.get("physical_traits"): overrides["physical_traits"] = tmpl["physical_traits"]
            if tmpl.get("hobbies"):         overrides["hobbies"] = tmpl["hobbies"]
            if tmpl.get("worn"):               overrides["worn"] = tmpl["worn"]
            if tmpl.get("starting_inventory"): overrides["starting_inventory"] = tmpl["starting_inventory"]
            if tmpl.get("job"):            overrides["job"] = tmpl["job"]
            if tmpl.get("education"):      overrides["education"] = tmpl["education"]
            if tmpl.get("current_school"): overrides["current_school"] = tmpl["current_school"]
            if tmpl.get("work_history"):   overrides["work_history"] = tmpl["work_history"]
            if tmpl.get("legal"):          overrides["legal"] = tmpl["legal"]
            if tmpl.get("instance"): overrides.update(tmpl["instance"])
            character = generate_character(defs, overrides)
        else:
            overrides = {k: v for k, v in body.items()
                         if k not in ("sim_id", "x", "y")}
            overrides["x"] = x
            overrides["y"] = y
            character = generate_character(defs, overrides)

        world.setdefault("characters", {})[character["id"]] = character
        save_world(sim_id, world)
    return {"ok": True, "id": character["id"], "name": character.get("name")}


@router.post("/spawn_character")
async def spawn_character(request: Request):
    """
    Spawn a character into the simulation.

    Body fields:
      sim_id    – which simulation (default: "default")
      template  – character_template key; if omitted a fully random character
                  is generated via generate_character()
      x, y      – world position
      overrides – dict of any other field overrides forwarded to generate_character
    """
    body        = await request.json()
    sim_id      = body.get("sim_id", "default")
    template_id = body.get("template")
    x           = body.get("x", 0)
    y           = body.get("y", 0)

    # world_lock() blocks (a real blocking call, not asyncio-aware) — run
    # the whole critical section on a background thread so a contended
    # lock doesn't freeze the event loop (this route used to call
    # load_world/save_world directly inline here, already blocking the
    # event loop for its DB round-trip; this fixes that too).
    return await asyncio.get_event_loop().run_in_executor(
        None, _spawn_character_locked, sim_id, template_id, x, y, body
    )


# =====================================
# GENERATE FAMILY TREE
# =====================================

def _generate_family_locked(sim_id, char_id, depth, replace):
    """Runs on a background thread (see generate_family below). Both
    possible outcomes (already-has-a-family early return, and the
    freshly-generated-family path) each call save_world() exactly once,
    but both must sit inside the *same* lock acquisition spanning from
    this function's own load_world() — holding world_lock() around the
    whole function body does that correctly regardless of which branch
    runs."""
    defs = load_definitions(sim_id)
    with world_lock():
        world = load_world(sim_id)

        char = world.get("characters", {}).get(char_id)
        if not char:
            raise HTTPException(status_code=404, detail=f"Character '{char_id}' not found")

        # Optionally remove existing family membership
        if replace and char.get("family_id"):
            old_fam_id = char["family_id"]
            old_fam = world.get("families", {}).get(old_fam_id, {})
            # Remove char from old family (orphan them, don't destroy others)
            old_fam.get("members", []).remove(char_id) if char_id in old_fam.get("members", []) else None
            # Remove directed edges from/to char
            world["families"][old_fam_id]["relations"] = {
                k: v for k, v in old_fam.get("relations", {}).items()
                if not k.startswith(f"{char_id}:") and not k.endswith(f":{char_id}")
            }
            char["family_id"]   = None
            char["family_role"] = None

        if char.get("family_id") and not replace:
            # Already has a family — just return the summary
            from systems.family import get_family_summary
            fam = world["families"][char["family_id"]]
            save_world(sim_id, world)
            return {"ok": True, "already_existed": True, "family": get_family_summary(fam, world)}

        from systems.family import generate_family_for_character, get_family_summary
        family = generate_family_for_character(char, world, defs, depth=depth)
        save_world(sim_id, world)

    return {
        "ok":     True,
        "family": get_family_summary(family, world),
    }


@router.post("/characters/{char_id}/generate_family")
async def generate_family(char_id: str, request: Request):
    """
    Procedurally generate a family tree for the given character and persist it.
    The character must already exist in the world.

    Optional body:
      sim_id  – simulation id (default: "default")
      depth   – 1 = immediate family (default), 2 = extended (grandparents, cousins)
      replace – if true, removes any existing family first (default: false)
    """
    body   = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    sim_id = body.get("sim_id", "default")
    depth  = int(body.get("depth", 1))
    replace= bool(body.get("replace", False))

    return await asyncio.get_event_loop().run_in_executor(
        None, _generate_family_locked, sim_id, char_id, depth, replace
    )
