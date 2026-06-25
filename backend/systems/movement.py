import math


# =========================================================
# UPDATE ROUTE MOVEMENT
# =========================================================

def update_character_movement(

    c,

    world
):

    route = c.get(
        "route",
        []
    )

    if not route:
        return False

    segment_index = c.get(
        "route_segment_index",
        0
    )

    if segment_index >= len(route):

        c["route"] = []

        c["activity"] = None

        c["is_moving"] = False

        c["animation_state"] = "idle"

        return False

    segment = route[
        segment_index
    ]

    path = segment.get(
        "tiles",
        []
    )

    path_index = c.get(
        "path_index",
        0
    )

    # =====================================
    # SEGMENT COMPLETE
    # =====================================

    if path_index >= len(path):

        c["route_segment_index"] += 1

        c["path_index"] = 0

        next_index = c[
            "route_segment_index"
        ]

        if next_index < len(route):

            next_segment = route[
                next_index
            ]

            if next_segment["type"] == "outdoor":

                c["building_id"] = None

            elif next_segment["type"] == "indoor":

                c["building_id"] = (
                    next_segment.get(
                        "building_id"
                    )
                )

        return True

    # =====================================
    # NEXT TILE
    # =====================================

    tx, ty = path[path_index]

    dx = tx - c["x"]
    dy = ty - c["y"]

    dist = math.sqrt(
        dx * dx
        + dy * dy
    )

    speed = c.get(
        "move_speed",
        0.05
    )

    # =====================================
    # ARRIVED TILE
    # =====================================

    if dist < 0.05:

        c["x"] = tx
        c["y"] = ty

        c["path_index"] += 1

        return True

    # =====================================
    # MOVE
    # =====================================

    if dist > 0:

        c["x"] += (
            dx / dist
        ) * speed

        c["y"] += (
            dy / dist
        ) * speed

    return True