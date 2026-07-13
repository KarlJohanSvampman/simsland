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
# PROCESS-LOCAL DEFINITIONS CACHE
# =========================================================
# definitions.json is large (hundreds of KB) and effectively immutable
# between edits — this was being re-read and re-parsed from disk on every
# single load_definitions() call (every tick, plus every API route that
# needs it). Cached here, invalidated only by save_definitions() (the one
# real mutator, in api/editor.py) via invalidate_definitions_cache().
_definitions_cache = {}


def invalidate_definitions_cache(sim_id):
    _definitions_cache.pop(sim_id, None)


# =========================================================
# LOAD DEFINITIONS
# =========================================================

def load_definitions(sim_id):

    if sim_id in _definitions_cache:
        return _definitions_cache[sim_id]

    path = defs_path(sim_id)

    if not path.exists():

        # Not cached — the file may be created later (e.g. via the
        # Definitions editor), and the next call should pick it up.
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

    _definitions_cache[sim_id] = defs

    return defs