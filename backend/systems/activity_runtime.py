from systems.affordances import (
    find_props_with_affordance
)
from systems.navigation import (
    build_multi_room_path
)
from systems.reservations import (

    reserve_object,

    release_object
)


# =========================================================
# START ACTIVITY
# =========================================================

def start_activity(

    world,

    character,

    activity_id,

    activity_template
):

    required = (

        activity_template
        .get(
            "required_affordances",
            []
        )
    )

    if not required:
        return False

    affordance = required[0]

    candidates = (

        find_props_with_affordance(

            world,

            affordance
        )
    )

    if not candidates:
        return False

    target = candidates[0]

    ok = reserve_object(

        target,

        character["id"]
    )

    if not ok:
        return False

    character["activity"] = (
        activity_id
    )

    character["activity_state"] = (
        "walking"
    )

    character["activity_target_id"] = (
        target["id"]
    )

    character["activity_timer"] = 0

    return True

# =========================================================
# GET PROP BY ID
# =========================================================

def get_prop_by_id(

    world,

    prop_id
):

    for p in world.get(
        "props",
        []
    ):

        if p["id"] == prop_id:
            return p

    return None

from systems.navigation import (
    build_multi_room_path
)

# =========================================================
# UPDATE WALKING
# =========================================================

import math


# =========================================================
# WALKING
# =========================================================

def update_character_walking(

    world,

    character
):

    target = get_prop_by_id(

        world,

        character.get(
            "activity_target_id"
        )
    )

    if not target:
        return

    # =====================================
    # BUILD REAL PATH
    # =====================================

    if not character.get("path"):

        building_id = target.get(
            "building_id"
        )

        if not building_id:
            return

        building = None

        for b in world.get(
            "buildings",
            []
        ):

            if b["id"] == building_id:

                building = b

                break

        if not building:
            return

        floorplan = (

            world["definitions"]
            ["floorplan_templates"]
            .get(
                building["template"]
            )
        )

        if not floorplan:
            return

        path = build_multi_room_path(

            building,

            floorplan,

            (
                character["x"],
                character["y"]
            ),

            (
                target["x"],
                target["y"]
            )
        )

        print("PATH:", path)

        character["path"] = path

        character["path_index"] = 0

    path = character.get(
        "path",
        []
    )

    idx = character.get(
        "path_index",
        0
    )

    if idx >= len(path):

        character[
            "activity_state"
        ] = "using"
        activity = character.get(
            "activity"
        )

        if activity:

            template = (
                world["definitions"]
                ["activity_templates"]
                .get(activity)
            )

            if template:

                character[
                    "animation_state"
                ] = template.get(
                    "animation",
                    "idle"
                )
        return

    next_tile = path[idx]

    tx = next_tile[0]
    ty = next_tile[1]

    dx = tx - character["x"]
    dy = ty - character["y"]

    dist = math.sqrt(
        dx * dx
        + dy * dy
    )

    speed = character.get(
        "move_speed",
        0.05
    )

    # reached tile
    if dist < 0.05:

        character["x"] = tx
        character["y"] = ty

        character["path_index"] += 1

        return

    # normalized move
    if dist > 0:

        character["x"] += (
            dx / dist
        ) * speed

        character["y"] += (
            dy / dist
        ) * speed
# =========================================================
# UPDATE USING
# =========================================================

def update_character_using(

    world,

    character,

    activity_template
):

    character[
        "activity_timer"
    ] += 1

    duration = activity_template.get(
        "duration",
        60
    )

    if (

        character["activity_timer"]

        < duration
    ):
        character[
        "animation_state"
        ] = "idle"
        return

    changes = activity_template.get(
        "need_changes",
        {}
    )

    needs = character.get(
        "needs",
        {}
    )

    for need, delta in changes.items():

        needs[need] = min(

            100,

            needs.get(need, 0)
            + delta
        )

    character["activity_state"] = (
        "idle"
    )

    character["activity"] = None

    character["activity_timer"] = 0

    target = get_prop_by_id(

        world,

        character.get(
            "activity_target_id"
        )
    )

    if target:

        release_object(target)

        

    character["activity_target_id"] = None

