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

from systems.interactions import (
    begin_interaction
)

# =========================================================
# ACTIVITIES
# =========================================================
ACTIVITIES = {

    # =====================================================
    # BASIC NEEDS
    # =====================================================

    "sleep": {

        "interaction": "sleep",

        "base_duration_minutes": 480,

        "interruptible": True,

        "category": "survival"
    },

    "nap": {

        "interaction": "sleep",

        "base_duration_minutes": 45,

        "interruptible": True,

        "category": "survival"
    },

    "use_toilet": {

        "interaction": "use_toilet",

        "base_duration_minutes": 3,

        "interruptible": False,

        "category": "survival"
    },

    "take_shower": {

        "interaction": "take_shower",

        "base_duration_minutes": 12,

        "interruptible": False,

        "category": "survival"
    },

    "brush_teeth": {

        "interaction": "brush_teeth",

        "base_duration_minutes": 4,

        "interruptible": True,

        "category": "hygiene"
    },

    "wash_hands": {

        "interaction": "wash_hands",

        "base_duration_minutes": 2,

        "interruptible": True,

        "category": "hygiene"
    },

    "shave": {

        "interaction": "mirror",

        "base_duration_minutes": 8,

        "interruptible": True,

        "category": "appearance"
    },

    "apply_makeup": {

        "interaction": "mirror",

        "base_duration_minutes": 15,

        "interruptible": True,

        "category": "appearance"
    },

    "eat_snack": {

        "interaction": "eat",

        "base_duration_minutes": 8,

        "interruptible": True,

        "category": "survival"
    },

    "cook_meal": {

        "interaction": "cook",

        "base_duration_minutes": 35,

        "interruptible": False,

        "category": "survival"
    },

    "eat_meal": {

        "interaction": "eat",

        "base_duration_minutes": 25,

        "interruptible": True,

        "category": "survival"
    },

    "drink_water": {

        "interaction": "drink",

        "base_duration_minutes": 2,

        "interruptible": True,

        "category": "survival"
    },

    # =====================================================
    # HOME LIFE
    # =====================================================

    "watch_tv": {

        "interaction": "watch_tv",

        "base_duration_minutes": 45,

        "interruptible": True,

        "category": "leisure"
    },

    "sit_and_relax": {

        "interaction": "sit",

        "base_duration_minutes": 30,

        "interruptible": True,

        "category": "leisure"
    },

    "listen_to_music": {

        "interaction": "music",

        "base_duration_minutes": 40,

        "interruptible": True,

        "category": "leisure"
    },
    "reflect": {

    "interaction": "sit",

    "base_duration_minutes": 25,

    "interruptible": True,

    "category": "internal" 
    },

    "read_book": {

        "interaction": "read",

        "base_duration_minutes": 60,

        "interruptible": True,

        "category": "leisure"
    },

    "browse_phone": {

        "interaction": "phone",

        "base_duration_minutes": 20,

        "interruptible": True,

        "category": "leisure"
    },

    "clean_house": {

        "interaction": "clean",

        "base_duration_minutes": 45,

        "interruptible": True,

        "category": "maintenance"
    },

    "do_laundry": {

        "interaction": "laundry",

        "base_duration_minutes": 90,

        "interruptible": True,

        "category": "maintenance"
    },

    "wash_dishes": {

        "interaction": "sink",

        "base_duration_minutes": 20,

        "interruptible": True,

        "category": "maintenance"
    },

    "take_out_trash": {

        "interaction": "trash",

        "base_duration_minutes": 10,

        "interruptible": True,

        "category": "maintenance"
    },

    # =====================================================
    # WORK / PRODUCTIVITY
    # =====================================================

    "work_shift": {

        "interaction": "work",

        "base_duration_minutes": 480,

        "interruptible": False,

        "category": "work"
    },

    "apply_job": {

        "interaction": "computer",

        "base_duration_minutes": 15,

        "interruptible": True,

        "category": "work"
    },

    "look_for_job": {

        "interaction": "computer",

        "base_duration_minutes": 25,

        "interruptible": True,

        "category": "work"
    },

    "study": {

        "interaction": "desk",

        "base_duration_minutes": 90,

        "interruptible": True,

        "category": "growth"
    },

    "write": {

        "interaction": "desk",

        "base_duration_minutes": 60,

        "interruptible": True,

        "category": "creative"
    },

    "paint": {

        "interaction": "creative",

        "base_duration_minutes": 90,

        "interruptible": True,

        "category": "creative"
    },

    "practice_skill": {

        "interaction": "practice",

        "base_duration_minutes": 60,

        "interruptible": True,

        "category": "growth"
    },

    # =====================================================
    # SOCIAL
    # =====================================================

    "conversation": {

        "interaction": "socialize",

        "base_duration_minutes": 20,

        "interruptible": True,

        "category": "social"
    },

    "hangout": {

        "interaction": "socialize",

        "base_duration_minutes": 120,

        "interruptible": True,

        "category": "social"
    },

    "flirt": {

        "interaction": "socialize",

        "base_duration_minutes": 15,

        "interruptible": True,

        "category": "social"
    },

    "argue": {

        "interaction": "socialize",

        "base_duration_minutes": 20,

        "interruptible": False,

        "category": "social"
    },

    "comfort_someone": {

        "interaction": "socialize",

        "base_duration_minutes": 25,

        "interruptible": False,

        "category": "social"
    },

    "gossip": {

        "interaction": "socialize",

        "base_duration_minutes": 30,

        "interruptible": True,

        "category": "social"
    },

    "phone_call": {

        "interaction": "phone",

        "base_duration_minutes": 15,

        "interruptible": True,

        "category": "social"
    },

    "texting": {

        "interaction": "phone",

        "base_duration_minutes": 5,

        "interruptible": True,

        "category": "social"
    },

    "invite_over": {

        "interaction": "phone",

        "base_duration_minutes": 5,

        "interruptible": True,

        "category": "social"
    },

    # =====================================================
    # OUTDOOR / ERRANDS
    # =====================================================

    "go_shopping": {

        "interaction": "shop",

        "base_duration_minutes": 90,

        "interruptible": False,

        "category": "errands"
    },

    "buy_food": {

        "interaction": "shop_food",

        "base_duration_minutes": 45,

        "interruptible": False,

        "category": "errands"
    },

    "walk_neighborhood": {

        "interaction": "walk",

        "base_duration_minutes": 40,

        "interruptible": True,

        "category": "leisure"
    },

    "exercise": {

        "interaction": "exercise",

        "base_duration_minutes": 60,

        "interruptible": True,

        "category": "health"
    },

    "jog": {

        "interaction": "exercise",

        "base_duration_minutes": 45,

        "interruptible": True,

        "category": "health"
    },

    "sit_in_park": {

        "interaction": "sit",

        "base_duration_minutes": 50,

        "interruptible": True,

        "category": "leisure"
    },

    # =====================================================
    # SELF / INTERNAL
    # =====================================================

    "reflect": {

        "interaction": "sit",

        "base_duration_minutes": 30,

        "interruptible": True,

        "category": "internal"
    },

    "cry": {

        "interaction": "sit",

        "base_duration_minutes": 12,

        "interruptible": False,

        "category": "emotional"
    },

    "daydream": {

        "interaction": "sit",

        "base_duration_minutes": 20,

        "interruptible": True,

        "category": "internal"
    },

    "journal": {

        "interaction": "desk",

        "base_duration_minutes": 25,

        "interruptible": True,

        "category": "internal"
    },

    "doomscroll": {

        "interaction": "phone",

        "base_duration_minutes": 40,

        "interruptible": True,

        "category": "internal"
    },

    # =====================================================
    # FUTURE / SPECIALIZED
    # =====================================================

    "cook_together": {

        "interaction": "cook",

        "base_duration_minutes": 45,

        "interruptible": False,

        "category": "social"
    },

    "watch_movie_together": {

        "interaction": "watch_tv",

        "base_duration_minutes": 120,

        "interruptible": True,

        "category": "social"
    },

    "family_dinner": {

        "interaction": "eat",

        "base_duration_minutes": 60,

        "interruptible": False,

        "category": "social"
    },

    "party": {

        "interaction": "socialize",

        "base_duration_minutes": 240,

        "interruptible": False,

        "category": "social"
    },

    "fight": {

        "interaction": "socialize",

        "base_duration_minutes": 10,

        "interruptible": False,

        "category": "conflict"
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

    interaction = begin_interaction(

    c,

    world,

    interaction
    ) 
    if not interaction:
        return False

    prop = interaction["prop"]
    anchor = interaction["anchor"]

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

    # =====================================
    # CONVERSATION
    '
    elif activity_type == "conversation":

        return update_conversation_activity(

            c,

            world,

            act
        )
    # =====================================

def set_activity_phase(

    act,

    phase,

    world
):

    act["phase"] = phase

    act[
        "phase_started_tick"
    ] = world["tick"]


def finish_activity(c, world):

    release_anchor(
        c,
        world
    )

    release_reservation(
        c,
        world
    )

    c["animation_state"] = "idle"

    c["activity"] = None


from conversations import (
    add_message
)


def update_conversation_activity(

    c,

    world,

    act
):

    # =====================================
    # WALKING
    # =====================================

    if act["phase"] == "walking":

        if c.get("is_moving"):
            return True

        set_activity_phase(

            act,

            "using",

            world
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

        # -------------------------
        # SPEAK EVERY 20 TICKS
        # -------------------------

        if (

            elapsed

            -

            act["state"].get(
                "last_turn_tick",
                0
            )

            >= 20
        ):

            do_conversation_turn(

                c,

                world,

                act
            )

            act["state"][
                "last_turn_tick"
            ] = elapsed

        # -------------------------
        # END
        # -------------------------

        if elapsed >= act["duration"]:

            set_activity_phase(

                act,

                "finishing",

                world
            )

        return True

    # =====================================
    # FINISHING
    # =====================================

    if act["phase"] == "finishing":

        finish_activity(
            c,
            world
        )

        return False

    return True