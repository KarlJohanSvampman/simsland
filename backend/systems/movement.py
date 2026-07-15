from systems.personal_items import lock_home
from systems.props import get_prop_by_id
from systems.templates import get_prop_template
from systems.prop_movement import get_move_capacity, get_drag_animation, get_push_animation
import math


# =========================================================
# UPDATE ROUTE MOVEMENT
# =========================================================

OFFSET_DRAG = 0.6   # matches the pre-existing baby-carriage "in front" offset
OFFSET_PUSH = 1.1   # pusher trails further back than the dragged prop itself


def _auto_lock_on_exit(c, world):
    """Lock home when character transitions from their home building to outdoor."""
    current_building = c.get("building_id")
    if not current_building:
        return
    hid = c.get("household_id")
    if not hid:
        return
    h = world.get("households", {}).get(hid, {})
    if h.get("home_id") == current_building:
        lock_home(c, world)


def update_character_movement(

    c,

    world
):

    # Defense-in-depth: a route already in flight when a character dies or
    # collapses (see systems/health.py::apply_severity_consequences)
    # shouldn't keep interpolating just because it was queued before that
    # happened — action_router.py's _movement_blocked() already stops a
    # *new* move/turn_and_run from being issued, this covers one already
    # underway.
    if not c.get("alive", True) or c.get("posture") in ("unconscious", "dead"):
        c["route"] = []
        c["is_moving"] = False
        return False

    # A pusher has no route/move_target of their own — they're attached to
    # the prop, not independently walking. Position is driven entirely by
    # the dragger's movement, so this short-circuits before the normal
    # route logic below (which a route-less pusher would otherwise just
    # bail out of via the `if not route` check with no effect at all).
    pushing_prop_id = c.get("pushing_prop_id")
    if pushing_prop_id:
        prop = get_prop_by_id(world, pushing_prop_id)
        if prop and prop.get("being_dragged_by"):
            dragger = world.get("characters", {}).get(prop["being_dragged_by"])
            if dragger:
                ddx = dragger["x"] - prop["x"]
                ddy = dragger["y"] - prop["y"]
                ddist = math.hypot(ddx, ddy) or 1
                c["x"] = prop["x"] - (ddx / ddist) * OFFSET_PUSH
                c["y"] = prop["y"] - (ddy / ddist) * OFFSET_PUSH
            push_anim = get_push_animation(world, prop)
            if push_anim:
                c["animation_state"] = push_anim
        else:
            # Dragger let go or prop gone — detach.
            c["pushing_prop_id"] = None
        return True

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

                # Lock home doors when character steps outside
                _auto_lock_on_exit(c, world)
                prev_building = c.get("building_id")
                c["building_id"] = None
                # Fire departure observation (incidental speech system)
                if prev_building:
                    try:
                        from systems.incidental_speech import mark_departure
                        mark_departure(c, prev_building)
                    except Exception:
                        pass

            elif next_segment["type"] == "indoor":

                new_building = next_segment.get("building_id")
                c["building_id"] = new_building

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
    # STUCK DETECTION
    # =====================================
    # The interpolation below always closes `dist` by exactly `speed` per
    # tick, so it can't stall on its own — but nothing upstream guarantees
    # `path`/`route` stay valid (e.g. a stale route computed against a
    # since-changed building, or c["x"]/c["y"] getting perturbed by
    # another system). Previously a character wedged into that state had
    # no way out until the next LLM decision cycle, which can be minutes
    # away — track lack of progress here and abandon the route so a fresh
    # decision gets made promptly instead of leaving them frozen.
    last_dist = c.get("_stuck_last_dist")
    if last_dist is not None and dist >= last_dist - (speed * 0.5):
        c["_stuck_ticks"] = c.get("_stuck_ticks", 0) + 1
    else:
        c["_stuck_ticks"] = 0
    c["_stuck_last_dist"] = dist

    if c["_stuck_ticks"] > 60:
        c["route"] = []
        c["route_segment_index"] = 0
        c["path_index"] = 0
        c["is_moving"] = False
        c["animation_state"] = "idle"
        c["_stuck_ticks"] = 0
        c["_stuck_last_dist"] = None
        return False

    # Pushable prop (baby carriage / lawnmower) — apply walk_speed_modifier
    # and set the push animation directly. Previously looked up a
    # "placed_props" world key nothing ever wrote to, and a "template_id"
    # instance field that's actually called "template" — both always
    # resolved to nothing, so this silently no-op'd every tick. The
    # animation override also used to be written to
    # c["_active_locomotion_override"], which nothing anywhere ever read
    # back — fixed to set c["animation_state"] directly instead, matching
    # the already-working pattern activities.py uses for carry_walk.
    pushed_prop_id = c.get("pushed_prop_id")
    if pushed_prop_id:
        pushed_prop = get_prop_by_id(world, pushed_prop_id)
        if pushed_prop:
            prop_tpl = get_prop_template(world, pushed_prop) or {}
            speed_mod = prop_tpl.get("walk_speed_modifier", 1.0)
            speed = speed * speed_mod
            push_anim = prop_tpl.get("push_animation")
            if push_anim:
                c["animation_state"] = push_anim
        else:
            # Prop gone — detach
            c.pop("pushed_prop_id", None)

    # Dragged prop (chairs/sofas/etc. — see systems/prop_movement.py)
    dragged_prop = None
    dragged_prop_id = c.get("dragged_prop_id")
    if dragged_prop_id:
        dragged_prop = get_prop_by_id(world, dragged_prop_id)
        if dragged_prop:
            drag_anim = get_drag_animation(world, dragged_prop)
            if drag_anim:
                c["animation_state"] = drag_anim
        else:
            c["dragged_prop_id"] = None

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

        # Keep pushed prop in front of character
        pushed_prop_id = c.get("pushed_prop_id")
        if pushed_prop_id:
            pushed_prop = get_prop_by_id(world, pushed_prop_id)
            if pushed_prop:
                pushed_prop["x"] = c["x"] + (dx / dist) * OFFSET_DRAG
                pushed_prop["y"] = c["y"] + (dy / dist) * OFFSET_DRAG

        # Dragged prop trails BEHIND the character (negated offset, vs.
        # the pushed-prop "in front" case above). A move_capacity=2 prop
        # only actually follows once a second character has joined as
        # pusher — otherwise it deliberately stays put; the dragger can
        # still walk off without it.
        if dragged_prop_id and dragged_prop:
            capacity = get_move_capacity(dragged_prop)
            crewed = capacity == 1 or (capacity == 2 and dragged_prop.get("being_pushed_by"))
            if crewed:
                dragged_prop["x"] = c["x"] - (dx / dist) * OFFSET_DRAG
                dragged_prop["y"] = c["y"] - (dy / dist) * OFFSET_DRAG

    return True