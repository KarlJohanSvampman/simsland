import random

from systems.occupancy import (
    release_anchor,
    release_reservation
)

from systems.props import (
    find_nearest_anchor
)

from systems.movement import (
    request_route_to_anchor
)


# =========================================================
# ACTIVITY CONFIG
# =========================================================

ACTIVITIES = {

    "sleep": {

        "prop": "sleep",

        "base_duration_minutes": 480,

        "interruptible": True
    },

    "use_toilet": {

        "prop": "sit",

        "base_duration_minutes": 3,

        "interruptible": False
    },

    "take_shower": {

        "prop": "take_shower",

        "base_duration_minutes": 12,

        "interruptible": False
    },

    "eat_snack": {

        "prop": "eat",

        "base_duration_minutes": 8,

        "interruptible": True
    }
}


# =========================================================
# DURATION
# =========================================================

def compute_duration_ticks(

    c,

    base_minutes
):

    ticks = base_minutes * 60

    emotion = c.get(
        "emotion"
    )

    if emotion == "stressed":
        ticks *= 1.3

    elif emotion == "focused":
        ticks *= 0.8

    if "lazy" in c.get(
        "traits",
        []
    ):
        ticks *= 1.2

    ticks *= random.uniform(
        0.85,
        1.15
    )

    return int(ticks)


# =========================================================
# START ACTIVITY
# =========================================================

def start_activity(

    c,

    world,

    activity_type
):

    config = ACTIVITIES.get(
        activity_type
    )

    if not config:
        return False

    interaction = config["prop"]

    result = find_nearest_anchor(

        c,

        world,

        interaction
    )

    if not result:
        return False

    prop, anchor = result

    duration = compute_duration_ticks(

        c,

        config[
            "base_duration_minutes"
        ]
    )

    c["activity"] = {

        "type":
            activity_type,

        "phase":
            "walking",

        "phase_started_tick":
            world["tick"],

        "target_id":
            prop["id"],

        "anchor_name":
            anchor["name"],

        "duration":
            duration,

        "state": {}
    }

    request_route_to_anchor(

        c,

        world,

        prop,

        anchor
    )

    return True


# =========================================================
# UPDATE ACTIVITY
# =========================================================

def update_activity(

    c,

    world
):

    act = c.get(
        "activity"
    )

    if not act:
        return False

    activity_type = act.get(
        "type"
    )

    # =====================================
    # WALKING
    # =====================================

    if act["phase"] == "walking":

        if c.get("is_moving"):
            return True

        act["phase"] = "using"

        act[
            "phase_started_tick"
        ] = world["tick"]

        c["animation_state"] = (
            activity_type
        )

        return True

    # =====================================
    # USING
    # =====================================

    if act["phase"] == "using":

        elapsed = (

            world["tick"]

            -

            act[
                "phase_started_tick"
            ]
        )

        if elapsed >= act["duration"]:

            complete_activity(

                c,

                world,

                act
            )

            act["phase"] = (
                "finishing"
            )

            act[
                "phase_started_tick"
            ] = world["tick"]

        return True

    # =====================================
    # FINISHING
    # =====================================

    if act["phase"] == "finishing":

        release_anchor(
            c,
            world
        )

        release_reservation(
            c,
            world
        )

        c["animation_state"] = (
            "idle"
        )

        c["activity"] = None

        return False

    return True


# =========================================================
# COMPLETE ACTIVITY
# =========================================================

def complete_activity(

    c,

    world,

    act
):

    activity_type = act["type"]

    # =====================================
    # SLEEP
    # =====================================

    if activity_type == "sleep":

        c["needs"][
            "energy"
        ] = 1.0

    # =====================================
    # TOILET
    # =====================================

    elif activity_type == (
        "use_toilet"
    ):

        c["needs"][
            "bladder"
        ] = 0

    # =====================================
    # SHOWER
    # =====================================

    elif activity_type == (
        "take_shower"
    ):

        c["needs"][
            "hygiene"
        ] = 1.0

    # =====================================
    # SNACK
    # =====================================

    elif activity_type == (
        "eat_snack"
    ):

        c["needs"][
            "hunger"
        ] = max(

            0,

            c["needs"].get(
                "hunger",
                1
            )

            - 0.5
        )