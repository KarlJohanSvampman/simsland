from fastapi import APIRouter

from db import load_world

from core.definitions import (
    load_definitions
)

from brain.perception import (
    visual_range,
    hearing_range
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

    # Kept in sync with main.py::_view_radius() -- the ~25-30% buffer over
    # the strict "what's visible" figure gives pan/zoom drift slack before
    # it falls outside the loaded window (see that function's comment).
    radius = {

        1: 32,
        2: 20,
        3: 12

    }.get(zoom, 20)

    # =====================================
    # CHARACTERS
    # =====================================

    # Keyed by character id (not a list) to match the shape of the
    # WebSocket delta payload (_build_delta in main.py) — the frontend
    # merges snapshot and delta characters into the same dict, and if this
    # were a list, Object.entries() would key characters by array index
    # ("0", "1", ...) instead of their real id, creating a second,
    # never-cleaned-up model for the same character once a delta arrived.
    characters = {

        cid: c

        for cid, c in world.get(
            "characters",
            {}
        ).items()

        if in_view(

            c["x"],
            c["y"],

            cx,
            cy,

            radius
        )
    }

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
    # RUNTIME TILES (floorplan interiors)
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
    # OUTDOOR WORLD TILES (grass/road/sidewalk)
    # =====================================
    # These were never sent to the live game client at all — only
    # floorplan-interior tiles were, via runtime_tiles above — so outdoor
    # ground never rendered. Walk just the viewport range through
    # world_tile_lookup (O(radius^2), not the full 300x300 grid) rather
    # than scanning world["world_tiles"] (90k entries) on every request.
    # Skip anything a building's floorplan already covers, so outdoor
    # grass/road doesn't render on top of interior floors.
    building_footprint = {
        (t["x"], t["y"])
        for t in world.get("runtime_tiles", [])
    }

    tile_lookup = world.get("world_tile_lookup", {})
    for wx in range(cx - radius, cx + radius + 1):
        for wy in range(cy - radius, cy + radius + 1):
            if (wx, wy) in building_footprint:
                continue
            t = tile_lookup.get(f"{wx},{wy}")
            if t:
                tiles.append(t)

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
        "definitions": definitions,

        # current world tick -- frontend needs this for off-grid/travel
        # "back in Nm" countdowns (see main.js::renderCharacterInspector).
        "tick": world.get("tick", 0)
    }


# =========================================================
# PERCEPTION RANGE (debug overlay UI — vision/hearing rings)
# =========================================================
# visual_range()/hearing_range() (brain/perception.py) are pure functions,
# never persisted onto the character dict -- computed fresh here against
# the real live world, not replicated in JS, to avoid a two-language
# drift bug between the Python formula and a client-side copy.

@router.get("/view/perception-range/{char_id}")
def get_perception_range(
    char_id: str,
    sim_id: str
):
    world = load_world(sim_id)

    c = world.get("characters", {}).get(char_id)

    if not c:
        return {"visual_range": None, "hearing_range": None}

    return {
        "visual_range": visual_range(c, world),
        "hearing_range": hearing_range(c)
    }