from systems.personal_items import unlock_home
from systems.props import (
    find_nearest_anchor
)

from systems.occupancy import (
    reserve_anchor
)

from systems.anchors import (
    get_world_anchor_position
)

from systems.navigation import plan_character_route


# =========================================================
# REQUEST ROUTE TO ANCHOR
# Sets the character's move_target to the anchor's world
# position so the movement system walks them there.
# =========================================================


def _auto_unlock_for_prop(c, world, prop):
    """Unlock home doors when a character needs to enter their own home."""
    prop_building = prop.get("building_id")
    if not prop_building:
        return
    hid = c.get("household_id")
    if not hid:
        return
    h = world.get("households", {}).get(hid, {})
    if h.get("home_id") == prop_building:
        unlock_home(c, world)


def request_route_to_anchor(c, world, prop, anchor):
    # If the target prop is inside the character's home, unlock it first
    _auto_unlock_for_prop(c, world, prop)
    ax, ay = get_world_anchor_position(prop, anchor)

    c["move_target"] = {
        "x":           ax,
        "y":           ay,
        "target_id":   prop.get("id"),
        "target_type": "prop",
        "anchor_name": anchor.get("name"),
    }

    # Only mark as walking if a route was actually found — otherwise the
    # "walking" phase (activities.py) would wait on is_moving forever with
    # no route ever progressing to clear it.
    if plan_character_route(world, c, ax, ay):
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
