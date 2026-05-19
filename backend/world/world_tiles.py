# =========================================================
# CREATE TILE
# =========================================================

def create_world_tile(

    x,

    y,

    tile_type,

    district=None
):

    tile = {

        "x": x,

        "y": y,

        "type": tile_type,

        "district": district,

        "walkable": True,

        "vehicle_allowed": False,

        "movement_cost": 1.0,

        "blocks_vision": False,

        "noise": 0.1,

        "safety": 0.8
    }

    # =====================================
    # TYPE RULES
    # =====================================

    if tile_type == "road":

        tile["vehicle_allowed"] = True

        tile["noise"] = 0.7

        tile["safety"] = 0.5

    elif tile_type == "sidewalk":

        tile["noise"] = 0.4

        tile["safety"] = 0.8

    elif tile_type == "grass":

        tile["movement_cost"] = 1.8

        tile["noise"] = 0.05

    elif tile_type == "park":

        tile["movement_cost"] = 1.2

        tile["noise"] = 0.02

        tile["safety"] = 0.9

    return tile


    # =========================================================
# GENERATE WORLD TILES
# =========================================================

def generate_world_tiles(world):

    tiles = []

    width = world.get(
        "world_width",
        300
    )

    height = world.get(
        "world_height",
        300
    )

    for x in range(width):

        for y in range(height):

            # =====================================
            # ROADS EVERY 20
            # =====================================

            if x % 20 == 0 or y % 20 == 0:

                tile = create_world_tile(

                    x,

                    y,

                    "road",

                    "urban"
                )

            # =====================================
            # SIDEWALKS
            # =====================================

            elif (
                x % 20 in [1, 19]
                or
                y % 20 in [1, 19]
            ):

                tile = create_world_tile(

                    x,

                    y,

                    "sidewalk",

                    "urban"
                )

            # =====================================
            # LOTS / GRASS
            # =====================================

            else:

                tile = create_world_tile(

                    x,

                    y,

                    "grass",

                    "residential"
                )

            tiles.append(tile)

    world["world_tiles"] = tiles



# =========================================================
# BUILD TILE LOOKUP
# =========================================================

def build_world_tile_lookup(world):

    lookup = {}

    for t in world.get(
        "world_tiles",
        []
    ):

        lookup[
            (t["x"], t["y"])
        ] = t

    world["world_tile_lookup"] = (
        lookup
    )

# =========================================================
# GET TILE
# =========================================================

def get_world_tile(

    world,

    x,

    y
):

    return world.get(
        "world_tile_lookup",
        {}
    ).get((x, y))

# =========================================================
# WALKABLE
# =========================================================

def is_world_walkable(

    world,

    x,

    y
):

    tile = get_world_tile(
        world,
        x,
        y
    )

    if not tile:
        return False

    return tile.get(
        "walkable",
        False
    )