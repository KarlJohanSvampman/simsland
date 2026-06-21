from systems.props import (
    find_nearest_anchor
)

from systems.occupancy import (
    reserve_anchor
)

from systems.anchors import (
    get_world_anchor_position
)


# =========================================================
# REQUEST ROUTE TO ANCHOR
# Sets the character's move_target to the anchor's world
# position so the movement system walks them there.
# =========================================================

def request_route_to_anchor(c, world, prop, anchor):
    ax, ay = get_world_anchor_position(prop, anchor)

    c["move_target"] = {
        "x":           ax,
        "y":           ay,
        "target_id":   prop.get("id"),
        "target_type": "prop",
        "anchor_name": anchor.get("name"),
    }

    c["animation_state"] = "walk"
    c["is_moving"]       = True


# =========================================================
# BEGIN INTERACTION
# Finds the nearest free anchor for an interaction,
# reserves it, and routes the character there.
# =========================================================

def begin_interaction(c, world, interaction_name):

    result = find_nearest_anchor(c, world, interaction_name)

    if not result:
        return None

    prop, anchor = result

    ok = reserve_anchor(c, world, prop, anchor)

    if not ok:
        return None

    request_route_to_anchor(c, world, prop, anchor)

    return {
        "prop":   prop,
        "anchor": anchor,
    }
