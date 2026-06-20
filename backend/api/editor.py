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

        cache_floorplan