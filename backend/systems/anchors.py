from systems.transforms import (
    rotate_local_tile
)


# =========================================================
# WORLD ANCHOR POSITION
# =========================================================

def get_world_anchor_position(

    prop,

    anchor
):

    rotation = prop.get(
        "rotation",
        0
    )

    dx = anchor.get(
        "dx",
        0
    )

    dy = anchor.get(
        "dy",
        0
    )

    rx, ry = rotate_local_tile(

        dx,

        dy,

        rotation
    )

    return (

        prop["x"] + rx,

        prop["y"] + ry
    )

# =========================================================
# WORLD ANCHOR
# =========================================================

def get_world_anchor(

    prop,

    anchor
):

    wx, wy = get_world_anchor_position(

        prop,

        anchor
    )

    result = dict(anchor)

    result["x"] = wx
    result["y"] = wy

    return result