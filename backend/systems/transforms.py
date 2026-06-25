import math


# =========================================================
# NORMALIZE ROTATION
# =========================================================

def normalize_rotation(rotation):

    rotation = int(rotation) % 360

    if rotation not in [

        0,
        90,
        180,
        270
    ]:

        return 0

    return rotation


# =========================================================
# ROTATE LOCAL TILE
# =========================================================

def rotate_local_tile(

    x,

    y,

    rotation
):

    rotation = normalize_rotation(
        rotation
    )

    # =====================================
    # 0
    # =====================================

    if rotation == 0:

        return (

            int(x),

            int(y)
        )

    # =====================================
    # 90
    # =====================================

    if rotation == 90:

        return (

            int(-y),

            int(x)
        )

    # =====================================
    # 180
    # =====================================

    if rotation == 180:

        return (

            int(-x),

            int(-y)
        )

    # =====================================
    # 270
    # =====================================

    if rotation == 270:

        return (

            int(y),

            int(-x)
        )

    return (

        int(x),

        int(y)
    )


# =========================================================
# INVERSE ROTATION
# =========================================================

def inverse_rotation(rotation):

    rotation = normalize_rotation(
        rotation
    )

    return (360 - rotation) % 360


# =========================================================
# LOCAL -> WORLD
# =========================================================

def local_to_world(

    building,

    x,

    y
):

    rotation = building.get(
        "rotation",
        0
    )

    rx, ry = rotate_local_tile(

        x,

        y,

        rotation
    )

    world_x = (
        building["x"] + rx
    )

    world_y = (
        building["y"] + ry
    )

    return (

        int(world_x),

        int(world_y)
    )


# =========================================================
# WORLD -> LOCAL
# =========================================================

def world_to_local(

    building,

    world_x,

    world_y
):

    dx = (
        world_x - building["x"]
    )

    dy = (
        world_y - building["y"]
    )

    inv = inverse_rotation(

        building.get(
            "rotation",
            0
        )
    )

    lx, ly = rotate_local_tile(

        dx,

        dy,

        inv
    )

    return (

        int(lx),

        int(ly)
    )


# =========================================================
# ROTATE FOOTPRINT OFFSET
# =========================================================

def rotate_footprint_offset(

    dx,

    dy,

    rotation
):

    return rotate_local_tile(

        dx,

        dy,

        rotation
    )


# =========================================================
# PROP FOOTPRINT TILES
# =========================================================

def transform_footprint(

    origin_x,

    origin_y,

    footprint,

    rotation=0
):

    tiles = []

    for tile in footprint:

        dx = tile.get(
            "dx",
            0
        )

        dy = tile.get(
            "dy",
            0
        )

        rx, ry = rotate_footprint_offset(

            dx,

            dy,

            rotation
        )

        tiles.append((

            origin_x + rx,

            origin_y + ry
        ))

    return tiles


# =========================================================
# WORLD DISTANCE
# =========================================================

def tile_distance(

    ax,

    ay,

    bx,

    by
):

    return (

        abs(ax - bx)
        +
        abs(ay - by)
    )


# =========================================================
# ADJACENT
# =========================================================

def is_adjacent(

    ax,

    ay,

    bx,

    by
):

    return tile_distance(

        ax,

        ay,

        bx,

        by
    ) <= 1


# =========================================================
# CENTER OF FOOTPRINT
# =========================================================

def footprint_center(

    tiles
):

    if not tiles:

        return (0, 0)

    x = sum(t[0] for t in tiles)
    y = sum(t[1] for t in tiles)

    return (

        x / len(tiles),

        y / len(tiles)
    )


# =========================================================
# WORLD BOUNDS
# =========================================================

def footprint_bounds(

    tiles
):

    if not tiles:

        return None

    xs = [t[0] for t in tiles]
    ys = [t[1] for t in tiles]

    return {

        "min_x": min(xs),
        "max_x": max(xs),

        "min_y": min(ys),
        "max_y": max(ys)
    }