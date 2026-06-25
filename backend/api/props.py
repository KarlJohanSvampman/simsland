from fastapi import APIRouter
from uuid import uuid4

from db import (
    load_world,
    save_world
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
# GET DEFAULT FLOORPLAN
# =========================================================


def get_default_floorplan(definitions):

    floorplans = definitions.get(
        "floorplan_templates",
        {}
    )

    if not floorplans:
        return None

    return next(iter(floorplans.values()))


# =========================================================
# CREATE PROP
# =========================================================

@router.post("/prop/create")
def create_prop(
    sim_id: str,
    payload: dict
):

    world = load_world(sim_id)

    definitions = load_definitions(sim_id)

    floorplan = get_default_floorplan(
        definitions
    )

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
        )
    }

    world.setdefault(
        "props",
        []
    ).append(prop)

    # =====================================
    # SEMANTIC EVENT
    # =====================================

    if floorplan:

        on_prop_created(

            sim_id,

            floorplan,

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

    world = load_world(sim_id)

    definitions = load_definitions(sim_id)

    floorplan = get_default_floorplan(
        definitions
    )

    prop_id = payload["id"]

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

        if floorplan:

            on_prop_moved(

                sim_id,

                floorplan,

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

    world = load_world(sim_id)

    prop_id = payload["id"]

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