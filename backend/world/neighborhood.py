from world.world_tiles import (
    create_world_tile
)


# =========================================================
# GENERATE NEIGHBORHOOD
# =========================================================

def generate_neighborhood(world):

    width = 80
    height = 80

    world["world_width"] = width
    world["world_height"] = height

    tiles = []

    # =====================================
    # BASE GRASS
    # =====================================

    for x in range(width):

        for y in range(height):

            tiles.append(

                create_world_tile(

                    x,
                    y,

                    "grass",

                    "suburb"
                )
            )

    # =====================================
    # MAIN ROAD
    # =====================================

    for x in range(width):

        for y in range(36, 44):

            replace_tile(
                tiles,
                x,
                y,
                "road"
            )

    # =====================================
    # SIDEWALKS
    # =====================================

    for x in range(width):

        replace_tile(
            tiles,
            x,
            35,
            "sidewalk"
        )

        replace_tile(
            tiles,
            x,
            44,
            "sidewalk"
        )

    # =====================================
    # SMALL PARK
    # =====================================

    for x in range(30, 50):

        for y in range(50, 65):

            replace_tile(
                tiles,
                x,
                y,
                "park"
            )

    world["world_tiles"] = tiles

    # =========================================================
# REPLACE TILE
# =========================================================

def replace_tile(

    tiles,

    x,

    y,

    tile_type
):

    for t in tiles:

        if t["x"] == x and t["y"] == y:

            t["type"] = tile_type

            # =================================
            # ROAD
            # =================================

            if tile_type == "road":

                t["vehicle_allowed"] = True
                t["movement_cost"] = 1.2

            # =================================
            # SIDEWALK
            # =================================

            elif tile_type == "sidewalk":

                t["movement_cost"] = 1.0

            # =================================
            # PARK
            # =================================

            elif tile_type == "park":

                t["movement_cost"] = 1.1
                t["noise"] = 0.05

            return