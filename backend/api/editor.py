from fastapi import APIRouter, HTTPException, Request
from pathlib import Path
import json
import uuid

from db import load_world, save_world
from core.definitions import load_definitions

from systems.navigation import (
    cache_floorplan
)
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

    # =====================================
    # EMPTY DEFAULTS
    # =====================================

    if not path.exists():
        return {
            "prop_templates": {},
            "item_templates": {},
            "character_templates": {},
            "interaction_templates": {},
            "activity_templates": {},
            "tile_templates": {},
            "floorplan_templates": {},

            "material_templates": {},
            "recipe_templates": {},
            "product_templates": {},
            "appliance_templates": {},
            "vehicle_templates": {},
            "service_templates": {},
            "storage_templates": {},
            "social_templates": {},
            "need_templates": {},
            "trait_templates": {},
            "job_templates": {},
            "company_templates": {} 
        }

    # =====================================
    # LOAD JSON
    # =====================================

    with open(path, "r") as f:

        defs = json.load(f)

    # =====================================
    # FLOORPLAN CACHE REGISTRATION
    # =====================================

    floorplans = defs.get(
        "floorplan_templates",
        {}
    )

    for fp_id, fp in floorplans.items():

        # ensure ID exists
        if "id" not in fp:

            fp["id"] = fp_id

        try:

            cache_floorplan(
                fp_id,
                fp
            )

        except Exception as e:

            print(
                f"Failed to cache floorplan {fp_id}:",
                e
            )

    return defs

# =====================================
# SAVE DEFINITIONS
# =====================================

@router.post("/definitions")
async def save_definitions(
    sim_id: str,
    request: Request
):

    data = await request.json()

    path = defs_path(sim_id)

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    
    floorplans = data.get(
    "floorplan_templates",
    {}
    )

    for fp_id, fp in floorplans.items():

        if "id" not in fp:
            fp["id"] = fp_id

        cache_floorplan(
            fp_id,
            fp
        )

    return {"ok": True}


# =====================================
# SPAWN CHARACTER
# =====================================

@router.post("/spawn_character")
async def spawn_character(request: Request):

    body     = await request.json()
    sim_id   = body.get("sim_id", "default")
    template_id = body.get("template")
    x        = body.get("x", 0)
    y        = body.get("y", 0)

    if not template_id:
        raise HTTPException(status_code=400, detail="template is required")

    defs = load_definitions(sim_id)
    tmpl = defs.get("character_templates", {}).get(template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail=f"Character template '{template_id}' not found")

    world = load_world(sim_id)

    cid = f"char_{uuid.uuid4().hex[:8]}"
    name = tmpl.get("name") or template_id.replace("_", " ").title()

    character = {
        "id":       cid,
        "template": template_id,
        "name":     name,
        "model":    tmpl.get("model"),
        "x":        x,
        "y":        y,
        "rotation": 0,
        "facing":   "south",
        "needs": {
            "energy":   0.8,
            "hunger":   0.5,
            "social":   0.7,
            "fun":      0.6,
            "hygiene":  0.9
        },
        "traits":               tmpl.get("traits", []),
        "goal":                 {"type": "rest"},
        "plan":                 None,
        "task_queue":           [],
        "current_task":         None,
        "activity":             None,
        "secondary_activity":   None,
        "reservations":         [],
        "path":                 [],
        "destination":          None,
        "animation_state":      {"base": "idle", "upper": None},
        "last_utterance":       "",
        "conversation_target":  None,
        "look_target":          None
    }

    world.setdefault("characters", {})[cid] = character
    save_world(sim_id, world)

    return {"ok": True, "id": cid, "name": name}