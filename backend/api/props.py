from fastapi import APIRouter
from uuid import uuid4

from db import (
    load_world,
    save_world,
    world_lock
)

from core.definitions import (
    load_definitions
)

from systems.prop_events import (
    on_prop_created,
    on_prop_moved,
    on_prop_deleted
)

router = APIRouter()


# =========================================================
# RESOLVE TARGET BUILDING
# =========================================================


def _resolve_building(world, payload):
    """Picks the real world["buildings"] entry this prop belongs to --
    on_prop_created()/assign_prop_room() need the actual building
    instance (id/x/y placement), not a floorplan_templates entry (which
    has no world placement of its own). Prefers an explicit
    payload["building_id"]; falls back to the first building whose
    footprint contains (x, y) so a caller that only knows the tile
    position still resolves correctly."""
    buildings = world.get("buildings", [])
    building_id = payload.get("building_id")
    if building_id:
        for b in buildings:
            if b.get("id") == building_id:
                return b
        return None

    x, y = payload.get("x"), payload.get("y")
    for b in buildings:
        bx, by = b.get("x", 0), b.get("y", 0)
        w, h = b.get("width"), b.get("height")
        if w and h and bx <= x < bx + w and by <= y < by + h:
            return b
    return buildings[0] if buildings else None


# =========================================================
# CREATE PROP
# =========================================================

@router.post("/prop/create")
def create_prop(
    sim_id: str,
    payload: dict
):

    definitions = load_definitions(sim_id)

    # anchors/storage/footprint/category were never actually copied from
    # the template here -- every prop created through this endpoint ended
    # up with none of them, which meant find_nearest_anchor() (props.py)
    # could never find any anchor on it (interaction gated: eat/drink/
    # sit/shower/... all silently failed to start) and
    # containers.ensure_prop_storage() had nothing to lazily stamp from.
    # deepcopy the template's anchors so each prop instance gets its own
    # mutable copy -- reserve_anchor() mutates anchor["occupied_by"]
    # directly, and prop instances of the same template must not share
    # that state.
    import copy
    template = definitions.get("prop_templates", {}).get(payload["template"], {})

    prop = {
        "id": str(uuid4()),

        "template": payload[
            "template"
        ],

        "x": payload["x"],
        "y": payload["y"],

        "rotation": payload.get(
            "rotation",
            0
        ),

        "household_id": payload.get("household_id"),

        "anchors":   copy.deepcopy(template.get("anchors", [])),
        "footprint": template.get("footprint"),
        "category":  template.get("category"),
        "storage":   copy.deepcopy(template.get("storage")),
        "catalog":   template.get("catalog"),
    }

    with world_lock():
        world = load_world(sim_id)

        world.setdefault(
            "props",
            []
        ).append(prop)

        # =====================================
        # SEMANTIC EVENT
        # =====================================

        building = _resolve_building(world, payload)

        if building:

            on_prop_created(

                sim_id,

                building,

                definitions,

                prop
            )

        save_world(sim_id, world)

    return {
        "ok": True,
        "prop": prop
    }


# =========================================================
# MOVE PROP
# =========================================================

@router.post("/prop/move")
def move_prop(
    sim_id: str,
    payload: dict
):

    definitions = load_definitions(sim_id)

    prop_id = payload["id"]

    with world_lock():
        world = load_world(sim_id)

        building = _resolve_building(world, payload)

        for prop in world.get(
            "props",
            []
        ):

            if prop["id"] != prop_id:
                continue

            prop["x"] = payload["x"]
            prop["y"] = payload["y"]

            if "rotation" in payload:

                prop["rotation"] = payload[
                    "rotation"
                ]

            # =====================================
            # SEMANTIC EVENT
            # =====================================

            if building:

                on_prop_moved(

                    sim_id,

                    building,

                    definitions,

                    prop
                )

            save_world(sim_id, world)

            return {
                "ok": True,
                "prop": prop
            }

    return {
        "ok": False,
        "error": "prop not found"
    }


# =========================================================
# DELETE PROP
# =========================================================

@router.post("/prop/delete")
def delete_prop(
    sim_id: str,
    payload: dict
):

    prop_id = payload["id"]

    with world_lock():
        world = load_world(sim_id)

        new_props = []

        found = False

        for prop in world.get(
            "props",
            []
        ):

            if prop["id"] == prop_id:

                found = True
                continue

            new_props.append(prop)

        if not found:

            return {
                "ok": False,
                "error": "prop not found"
            }

        world["props"] = new_props

        # =====================================
        # SEMANTIC EVENT
        # =====================================

        on_prop_deleted(

            sim_id,

            prop_id
        )

        save_world(sim_id, world)

    return {
        "ok": True
    }