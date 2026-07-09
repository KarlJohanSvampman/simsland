from fastapi import APIRouter, HTTPException, Request
from pathlib import Path
import json
import uuid

from db import load_world, save_world
from core.definitions import load_definitions as _load_defs_core

from systems.navigation import cache_floorplan
from systems.character_gen import generate_character

router = APIRouter()

@router.get("/world")
def get_world(sim_id: str):
    return load_world(sim_id)

@router.post("/world")
def save(sim_id: str, data: dict):
    save_world(sim_id, data)
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
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    floorplans = data.get("floorplan_templates", {})
    for fp_id, fp in floorplans.items():
        if "id" not in fp:
            fp["id"] = fp_id
        cache_floorplan(fp_id, fp)
    return {"ok": True}


# =====================================
# SPAWN CHARACTER
# =====================================

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

    defs  = load_definitions(sim_id)
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


# =====================================
# GENERATE FAMILY TREE
# =====================================

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

    defs  = load_definitions(sim_id)
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
