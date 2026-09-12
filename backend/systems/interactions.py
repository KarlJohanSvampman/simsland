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

    # find_nearest_anchor() picks the globally nearest matching anchor
    # without checking occupancy (unlike find_free_anchor(), used by
    # every other reserve_anchor() call site) -- guard here instead.
    # reserve_anchor() itself has no return value to check.
    if anchor.get("occupied_by") and anchor["occupied_by"] != c["id"]:
        # Per the user's ask: before giving up, check whether a SECOND
        # instance of this same appliance (a different bathroom's
        # toilet/sink, ...) is free elsewhere and go there instead.
        from systems.props import find_nearest_free_anchor
        alt = find_nearest_free_anchor(c, world, interaction_name, exclude_anchor=anchor)
        if alt:
            prop, anchor = alt
        else:
            avoid_key = f"{prop['id']}:{anchor['name']}"
            avoided = c.get("_avoided_anchors", {}).get(avoid_key, 0)
            if world.get("tick", 0) < avoided:
                # Confirmed live bug: this same occupied anchor was already
                # abandoned recently (waiting.py's tick_waiting() gave up
                # after too many door-bangs) -- without this check, the
                # character's still-unmet need (bladder, ...) just
                # re-triggered the exact same queue on the very next tick,
                # making the earlier give-up a no-op in practice. Stay
                # genuinely unresolved for the cooldown window instead.
                return None

            # Nothing free anywhere -- this used to just silently fail
            # every tick with no visible consequence (begin_interaction
            # returning None, over and over, forever). Queue at the one
            # that's occupied (systems/occupancy.py::enqueue_anchor --
            # confirmed real but never actually called before this) and
            # arm the same patience-timer/growing-stress mechanism
            # already used for waiting on a person/business/delivery
            # (systems/waiting.py) -- genuine, escalating impatience
            # instead of a no-op, with a real wake to reconsider once
            # patience runs out.
            from systems.occupancy import enqueue_anchor
            from systems.waiting import start_waiting_for
            from systems.posture import set_posture
            enqueue_anchor(c, prop, anchor)
            # Confirmed live bug: a character queued here while still
            # carrying a stale "sitting_seat" posture from an EARLIER,
            # already-completed use of this same toilet (see
            # activities.py's use_toilet completion fix) rendered as if
            # they were simultaneously using the appliance they were
            # actually just standing in line for.
            set_posture(c, world, "standing")
            c["activity"] = {
                "type": "wait",
                "phase": "using",
                "phase_started_tick": world.get("tick", 0),
                "duration": 120,
                "state": {},
            }
            start_waiting_for(c, world, "prop", f"{prop['id']}:{anchor['name']}")
            return None

    reserve_anchor(c, prop, anchor)

    request_route_to_anchor(c, world, prop, anchor)

    return {
        "prop":   prop,
        "anchor": anchor,
    }
