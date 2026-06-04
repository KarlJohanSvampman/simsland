from pathlib import Path
import json

from systems.navigation import (
    cache_floorplan
)


BASE = Path("/data/simulations")


def defs_path(sim_id):

    return (
        BASE
        / sim_id
        / "definitions.json"
    )


# =========================================================
# LOAD DEFINITIONS
# =========================================================

def load_definitions(sim_id):

    path = defs_path(sim_id)

    if not path.exists():

        return {

            "prop_templates": {},
            "item_templates": {},
            "character_templates": {},
            "interaction_templates": {},
            "activity_templates": {},
            "tile_templates": {},
            "floorplan_templates": {},
            "trait_templates": {},
            "job_templates": {},
            "company_templates": {}
        }

    with open(path, "r") as f:

        defs = json.load(f)

    # =====================================
    # CACHE FLOORPLANS
    # =====================================

    floorplans = defs.get(
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

    return defs