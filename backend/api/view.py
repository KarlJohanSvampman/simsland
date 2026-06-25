from fastapi import APIRouter

from db import load_world

from core.definitions import (
    load_definitions
)

router = APIRouter()


# =========================================================
# VIEW TEST
# =========================================================

def in_view(
    x,
    y,
    cx,
    cy,
    radius
):

    return (

        abs(x - cx) <= radius
        and
        abs(y - cy) <= radius
    )


# =========================================================
# VIEW API
# =========================================================

@router.get("/view")
def get_view(

    sim_id: str,

    cx: int,

    cy: int,

    zoom: int = 2
):

    # =====================================
    # LOAD WORLD
    # =====================================

    world = load_world(sim_id)

    # =====================================
    # LOAD DEFINITIONS
    # =====================================

    definitions = load_definitions(
        sim_id
    )

    # =====================================
    # VIEW RADIUS
    # =====================================

    radius = {

        1: 25,
        2: 15,
        3: 8

    }.get(zoom, 15)

    # =====================================
    # CHARACTERS
    # =====================================

    characters = [

        c

        for c in world.get(
            "characters",
            {}
        ).values()

        if in_view(

            c["x"],
            c["y"],

            cx,
            cy,

            radius
        )
    ]

    # =====================================
    # PROPS
    # =====================================

    props = [

        {

            **p,

            "rotation": p.get(
                "rotation",
                0
            )
        }

        for p in world.get(
            "props",
            []
        )

        if in_view(

            p["x"],
            p["y"],

            cx,
            cy,

            radius
        )
    ]

    # =====================================
    # RUNTIME TILES
    # =====================================

    tiles = [

        t

        for t in world.get(
            "runtime_tiles",
            []
        )

        if in_view(

            t["x"],
            t["y"],

            cx,
            cy,

            radius
        )
    ]

    # =====================================
    # RUNTIME ROOMS
    # =====================================

    rooms = [

        r

        for r in world.get(
            "runtime_rooms",
            []
        )

        if any(

            in_view(

                tile["x"],
                tile["y"],

                cx,
                cy,

                radius
            )

            for tile in r.get(
                "tiles",
                []
            )
        )
    ]

    # =====================================
    # RUNTIME DOORS
    # =====================================

    doors = [

        d

        for d in world.get(
            "runtime_doors",
            []
        )

        if in_view(

            d["x"],
            d["y"],

            cx,
            cy,

            radius
        )
    ]

    # =====================================
    # RUNTIME WINDOWS
    # =====================================

    windows = [

        w

        for w in world.get(
            "runtime_windows",
            []
        )

        if in_view(

            w["x"],
            w["y"],

            cx,
            cy,

            radius
        )
    ]

    # =====================================
    # BUILDINGS
    # =====================================

    buildings = [

        b

        for b in world.get(
            "buildings",
            []
        )

        if in_view(

            b["x"],
            b["y"],

            cx,
            cy,

            radius * 2
        )
    ]

    # =====================================
    # RESPONSE
    # =====================================

    return {

        "center": {

            "x": cx,
            "y": cy
        },

        "zoom": zoom,

        # runtime geometry
        "tiles": tiles,

        "rooms": rooms,

        "doors": doors,

        "windows": windows,

        "buildings": buildings,

        # entities
        "characters": characters,

        "props": props,

        # semantic defs
        "definitions": definitions
    }