from copy import deepcopy

from systems.transforms import (
    local_to_world
)
#=============================================
# INSTANTIATE FLOORPLAN
# ============================================


def instantiate_floorplan(

    building,

    floorplan
):

    result = {

        "building_id": building["id"],

        "tiles": [],

        "rooms": [],

        "doors": [],

        "windows": [],

        "navigation": {}
    }

    # =====================================
    # TILES
    # =====================================

    for key, tile in floorplan.get(
        "tiles",
        {}
    ).items():

        tx, ty = (
            int(v) for v in key.split(",")
        )

        wx, wy = local_to_world(
            building,
            tx,
            ty
        )

        projected = deepcopy(tile)

        projected["x"] = wx
        projected["y"] = wy

        # All tiles from a floorplan are interior by definition;
        # floor=True for any tile whose type is "floor"
        tile_type = tile.get("type", "")
        projected.setdefault("interior", True)
        projected.setdefault("floor", tile_type == "floor")

        result["tiles"].append(
            projected
        )

    # =====================================
    # ROOMS
    # =====================================

    for room in floorplan.get(
        "rooms",
        []
    ):

        projected_room = deepcopy(room)

        projected_tiles = []

        for tile in room.get(
            "tiles",
            []
        ):

            wx, wy = local_to_world(
                building,
                tile["x"],
                tile["y"]
            )

            projected_tiles.append({
                "x": wx,
                "y": wy
            })

        projected_room[
            "tiles"
        ] = projected_tiles

        result["rooms"].append(
            projected_room
        )

    # =====================================
    # DOORS
    # =====================================

    for door in floorplan.get(
        "doors",
        []
    ):

        projected = deepcopy(door)

        wx, wy = local_to_world(
            building,
            door["x"],
            door["y"]
        )

        projected["x"] = wx
        projected["y"] = wy

        result["doors"].append(
            projected
        )

    # =====================================
    # WINDOWS
    # =====================================

    for window in floorplan.get(
        "windows",
        []
    ):

        projected = deepcopy(window)

        wx, wy = local_to_world(
            building,
            window["x"],
            window["y"]
        )

        projected["x"] = wx
        projected["y"] = wy

        result["windows"].append(
            projected
        )

    return result