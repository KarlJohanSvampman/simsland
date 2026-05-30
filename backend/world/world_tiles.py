from core.spatial import (
    spatial_key
)


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
            # ROADS
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
            # GRASS
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
            spatial_key(
                t["x"],
                t["y"]
            )
        ] = t

    world[
        "world_tile_lookup"
    ] = lookup

# =========================================================
# ROAD GATEWAYS
# =========================================================

def generate_road_gateways(world):

    if not world.get("world_tile_lookup"):
        build_world_tile_lookup(world)

    width = (
        world.get("world_width")
        or world.get("grid", {}).get("width")
        or 100
    )

    height = (
        world.get("world_height")
        or world.get("grid", {}).get("height")
        or 100
    )

    traffic = world.setdefault("traffic", {})

    entry_points = []
    exit_points = []

    for tile in world.get("world_tiles", []):

        if tile.get("type") != "road":
            continue

        x = tile["x"]
        y = tile["y"]

        if x == 0:
            entry_points.append({"x": x, "y": y, "direction": "east", "lane": "inbound"})
            exit_points.append({"x": x, "y": y, "direction": "west", "lane": "outbound"})

        elif x == width - 1:
            entry_points.append({"x": x, "y": y, "direction": "west", "lane": "inbound"})
            exit_points.append({"x": x, "y": y, "direction": "east", "lane": "outbound"})

        elif y == 0:
            entry_points.append({"x": x, "y": y, "direction": "south", "lane": "inbound"})
            exit_points.append({"x": x, "y": y, "direction": "north", "lane": "outbound"})

        elif y == height - 1:
            entry_points.append({"x": x, "y": y, "direction": "north", "lane": "inbound"})
            exit_points.append({"x": x, "y": y, "direction": "south", "lane": "outbound"})

    traffic["entry_points"] = entry_points
    traffic["exit_points"] = exit_points

    # legacy compatibility
    world["road_entry_points"] = entry_points
    world["road_exit_points"] = exit_points

    return traffic

# =========================================================
# BUILD ROAD GRAPH
# =========================================================

def build_road_graph(world):

    if not world.get(
        "world_tile_lookup"
    ):
        build_world_tile_lookup(
            world
        )

    graph = {}

    lookup = world[
        "world_tile_lookup"
    ]

    for tile in world.get(
        "world_tiles",
        []
    ):

        if tile.get(
            "type"
        ) != "road":

            continue

        x = tile["x"]
        y = tile["y"]

        node = (x, y)

        graph[node] = []

        for dx, dy in [

            (1, 0),
            (-1, 0),
            (0, 1),
            (0, -1)

        ]:

            nx = x + dx
            ny = y + dy

            neighbor = lookup.get(

                spatial_key(
                    nx,
                    ny
                )
            )

            if not neighbor:
                continue

            if neighbor.get(
                "type"
            ) != "road":
                continue

            graph[node].append(
                (nx, ny)
            )

    world["road_graph"] = graph

    return graph


# =========================================================
# DETECT INTERSECTIONS
# =========================================================

def generate_intersections(world):

    graph = world.get(
        "road_graph",
        {}
    )

    traffic = world.setdefault(
        "traffic",
        {}
    )

    intersections = []

    for node, neighbors in graph.items():

        if len(neighbors) >= 3:

            intersections.append({

                "x": node[0],

                "y": node[1]
            })

    traffic[
        "intersections"
    ] = intersections

    return intersections 

# =========================================================
# BUILD TRAFFIC NETWORK
# =========================================================

def build_traffic_network(world):

    generate_road_gateways(
        world
    )

    build_road_graph(
        world
    )

    generate_intersections(
        world
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
    ).get(

        spatial_key(x, y)
    )


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

