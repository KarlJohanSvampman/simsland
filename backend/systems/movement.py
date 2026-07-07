from systems.personal_items import lock_home
import math


# =========================================================
# UPDATE ROUTE MOVEMENT
# =========================================================


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

    # Pushable prop — apply walk_speed_modifier and drag prop along
    pushed_prop_id = c.get("pushed_prop_id")
    if pushed_prop_id:
        prop = world.get("placed_props", {}).get(pushed_prop_id)
        if prop:
            prop_tpl = world.get("definitions", {}).get("prop_templates", {}).get(
                prop.get("template_id", ""), {}
            )
            speed_mod = prop_tpl.get("walk_speed_modifier", 1.0)
            speed = speed * speed_mod
            # Override locomotion style to push animation while moving
            push_anim = prop_tpl.get("push_animation")
            if push_anim:
                c["_active_locomotion_override"] = push_anim
        else:
            # Prop gone — detach
            c.pop("pushed_prop_id", None)
    else:
        c.pop("_active_locomotion_override", None)

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
            prop = world.get("placed_props", {}).get(pushed_prop_id)
            if prop:
                prop["x"] = c["x"] + (dx / dist) * 0.6
                prop["y"] = c["y"] + (dy / dist) * 0.6

    return True