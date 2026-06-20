import random

from systems.occupancy import (
    release_anchor,
    release_reservation
)

from systems.household_storage import (
    find_household_resource,
    remove_household_resource
)

from systems.mail import (
    sort_household_mail
)

from systems.waste import (
    generate_activity_waste
)
from systems.props import (
    find_nearest_anchor,
    get_prop_by_id,
    get_anchor,
)

from systems.interactions import (
    begin_interaction
)

from systems.conversation_runtime import (
    update_conversation_activity
)

# =========================================================
# INTERACTION ANIMATIONS
# Maps interaction name → animations per activity phase.
# Used by execute_activity and action_router to drive the
# frontend animation state machine.
#
# Convention for prop GLB nodes:
#   anchor_<interaction>  — where the character stands/sits
#   target_<anything>     — what they look at (IK target)
# =========================================================

INTERACTION_ANIMATIONS = {
    # --- furniture ---
    "sit":          {"walking": "walk", "using": "sit_idle",   "finishing": "stand_up"},
    "lie":          {"walking": "walk", "using": "lie_idle",   "finishing": "stand_up"},
    "lie_down":     {"walking": "walk", "using": "lie_idle",   "finishing": "stand_up"},

    # --- sleep ---
    "sleep":        {"walking": "walk", "using": "sleep_idle", "finishing": "wake_up"},

    # --- screens / entertainment ---
    "watch_tv":     {"walking": "walk", "using": "sit_idle",   "finishing": "stand_up"},
    "use_computer": {"walking": "walk", "using": "sit_idle",   "finishing": "stand_up"},

    # --- food ---
    "eat":          {"walking": "walk", "using": "eat",        "finishing": "idle"},
    "cook":         {"walking": "walk", "using": "cook",       "finishing": "idle"},
    "stove":        {"walking": "walk", "using": "cook",       "finishing": "idle"},
    "microwave":    {"walking": "walk", "using": "cook",       "finishing": "idle"},
    "fridge":       {"walking": "walk", "using": "interact",   "finishing": "idle"},

    # --- hygiene ---
    "take_shower":  {"walking": "walk", "using": "shower",     "finishing": "idle"},
    "use_toilet":   {"walking": "walk", "using": "sit_idle",   "finishing": "stand_up"},
    "brush_teeth":  {"walking": "walk", "using": "interact",   "finishing": "idle"},
    "wash_hands":   {"walking": "walk", "using": "interact",   "finishing": "idle"},
    "mirror":       {"walking": "walk", "using": "interact",   "finishing": "idle"},

    # --- social ---
    "socialize":    {"walking": "walk", "using": "talk",       "finishing": "idle"},
    "talk":         {"walking": "walk", "using": "talk",       "finishing": "idle"},
    "phone":        {"walking": "walk", "using": "phone",      "finishing": "idle"},

    # --- work ---
    "work":         {"walking": "walk", "using": "work",       "finishing": "idle"},

    # --- reading / hobbies ---
    "read":         {"walking": "walk", "using": "read",       "finishing": "idle"},

    # --- generic fallback ---
    "interact":     {"walking": "walk", "using": "interact",   "finishing": "idle"},
}


def get_phase_animation(interaction, phase):
    """Return the animation name for a given interaction + phase.
    Falls back to sensible defaults when no mapping exists."""
    entry = INTERACTION_ANIMATIONS.get(interaction)
    if entry:
        return entry.get(phase, "idle")
    defaults = {"walking": "walk", "using": "interact", "finishing": "idle"}
    return defaults.get(phase, "idle")


# =========================================================
# ACTIVITIES
# =========================================================
ACTIVITIES = {
    # =====================================================
    # SOCIAL ACTIVITIES
    # =====================================================
    "text_person": {

        "interaction": "phone",

        "base_duration_minutes": 3,

        "interruptible": True,

        "category": "social"
    },
    "call_person": {

    "interaction": "phone",

    "base_duration_minutes": 12,

    "interruptible": True,

    "category": "social"
    },
    "visit_person": {

        "interaction": "socialize",

        "base_duration_minutes": 90,

        "interruptible": True,

        "category": "social"
    },
    "seek_comfort": {

        "interaction": "socialize",

        "base_duration_minutes": 25,

        "interruptible": False,

        "category": "social"
    },
    "apologize": {

        "interaction": "socialize",

        "base_duration_minutes": 15,

        "interruptible": False,

        "category": "social"
    },
    "gossip": {

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
    # =====================================================
    # FOOD
    # =====================================================
    "heat_meal": {

        "interaction": "microwave",

        "base_duration_minutes": 4,

        "interruptible": False,

        "category": "food",

        "waste": {

            "TRASH_PLASTIC": 1
        }
    },

    "retrieve_food": {

        "interaction": "fridge",

        "base_duration_minutes": 2,

        "interruptible": False,

        "category": "food"
    },

    "store_leftovers": {

        "interaction": "fridge",

        "base_duration_minutes": 3,

        "interruptible": False,

        "category": "food"
    },

    "cook_recipe": {

        "interaction": "stove",

        "base_duration_minutes": 20,

        "interruptible": False,

        "category": "food",
        
        "waste": {

            "TRASH_FOOD_PACKAGING": 2,

            "TRASH_ORGANIC": 1
        }
    },

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
    "sort_mail": {
        "interaction": "desk",
        "base_duration_minutes": 8,
        "interruptible": True,
        "category": "domestic"
    },
    "pay_bills": {
        "interaction": "computer",
        "base_duration_minutes": 12,
        "interruptible": False,
        "category": "domestic"
    },

    "respond_to_mail": {
        "interaction": "desk",
        "base_duration_minutes": 25,
        "interruptible": False,
        "category": "domestic"
    },
    "fill_form": {
        "interaction": "desk",
        "base_duration_minutes": 40,
        "interruptible": False,
        "category": "domestic"
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
    "take_out_trash": {

        "interaction": "garbage_bin",

        "base_duration_minutes": 5,

        "interruptible": False,

        "category": "chore"
    } ,
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
    "throw_away_trash": {

        "interaction": "garbage_bin",

        "base_duration_minutes": 3,

        "interruptible": True,

        "category": "chore"
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
    },
    # =========================================================
    # PACKAGE DELIVERIES
    # =========================================================
    "unpack_delivery": {

        "interaction": "front_door",

        "base_duration_minutes": 10,

        "interruptible": False,

        "category": "errand",

        "waste": {

            "TRASH_CARDBOARD": 3,

            "TRASH_PLASTIC": 2
        }
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

        config["interaction"]
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
# EXECUTE ACTIVITY
# =========================================================

def execute_activity(

    c,

    world,

    act
):

    activity_type = act.get(
        "type"
    )

    # =====================================================
    # CONVERSATION
    # =====================================================

    if activity_type == "conversation":

        return update_conversation_activity(

            c,

            world,

            act
        )

    # Resolve the interaction name for animation lookups
    # (LLM-dispatched activities store it as act["interaction"];
    #  ACTIVITIES-config activities use their config's "interaction" field)
    interaction = (
        act.get("interaction")
        or ACTIVITIES.get(activity_type, {}).get("interaction")
        or activity_type
    )

    # =====================================================
    # WALKING  — wait until movement system clears is_moving
    # =====================================================

    if act.get("phase", "using") == "walking":

        if c.get("is_moving"):
            return True

        # Character arrived — snap logical grid position to anchor
        prop = get_prop_by_id(world, act.get("target_id"))
        if prop and act.get("anchor_name"):
            anchor = get_anchor(prop, act["anchor_name"])
            if anchor:
                c["x"] = anchor["x"]
                c["y"] = anchor["y"]

        set_activity_phase(act, "using", world)
        c["animation_state"] = get_phase_animation(interaction, "using")
        return True

    # =====================================================
    # USING  — tick elapsed time
    # =====================================================

    if act["phase"] == "using":

        elapsed = world["tick"] - act["phase_started_tick"]

        if elapsed >= act["duration"]:

            complete_activity(c, world, act)
            set_activity_phase(act, "finishing", world)
            c["animation_state"] = get_phase_animation(interaction, "finishing")

        return True

    # =====================================================
    # FINISHING  — one tick to play finishing animation
    # =====================================================

    if act["phase"] == "finishing":

        finish_activity(c, world)
        return False

    return True
#=======================================================
# COMPLETE ACTIVITY
# =========================================================

def complete_activity(

    c,

    world,

    act
):

    activity_type = act["type"]


    # =====================================
    # GENERATE WASTE
    # =====================================
    household = world[
        "households"
    ].get(
        c.get("household_id")
    )

    if household:

        generate_activity_waste(

            household,

            act
        )
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
    # MEAL
    # =====================================
    elif activity_type == "eat_meal":

        household = world[
            "households"
        ].get(
            c.get("household_id")
        )

    if household:

        meal = find_household_resource(

            household,

            resource_type="MEAL"
        )

        if meal:

            nutrition = meal.get(
                "nutrition",
                0.5
            )

            c["needs"]["hunger"] = max(

                0,

                c["needs"][
                    "hunger"
                ]

                -

                nutrition
            )

            meal["servings"] -= 1

            if meal["servings"] <= 0:

                remove_household_resource(

                    household,

                    meal,

                    1
                )
            elif meal["servings"] > 0:

                from systems.resource_runtime import (
                    convert_meal_to_leftovers
                )

                convert_meal_to_leftovers(
                    meal
                )
    # =====================================
    # MEAL
    # =====================================
    elif activity_type == "cook_recipe":

        from systems.cooking_proce