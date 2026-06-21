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
    # Using lists here: the backend picks one at random when the phase starts.
    # The frontend also has its own ANIM_VARIANTS pool that cycles through
    # variants for the full duration of the activity.
    "socialize":    {"walking": "walk", "using": ["talk", "talk_gesture_a", "talk_gesture_b", "talk_nod"], "finishing": "idle"},
    "talk":         {"walking": "walk", "using": ["talk", "talk_gesture_a", "talk_gesture_b", "talk_nod"], "finishing": "idle"},
    "phone":        {"walking": "walk", "using": ["phone", "phone_gesture"], "finishing": "idle"},

    # --- work ---
    "work":         {"walking": "walk", "using": ["work", "work_type", "work_read"], "finishing": "idle"},

    # --- reading / hobbies ---
    "read":         {"walking": "walk", "using": "read",       "finishing": "idle"},

    # --- inspection / investigation ---
    "examine":      {"walking": "walk", "using": ["examine", "examine_crouch"], "finishing": "idle"},
    "inspect":      {"walking": "walk", "using": ["examine", "examine_crouch"], "finishing": "idle"},
    "search":       {"walking": "walk", "using": "search",     "finishing": "idle"},

    # --- object manipulation ---
    "carry":        {"walking": "walk", "using": "carry_idle", "finishing": "put_down"},
    "trash":        {"walking": "walk", "using": "throw",      "finishing": "idle"},
    "destroy":      {"walking": "walk", "using": "smash",      "finishing": "idle"},

    # --- cleaning (generic; use get_clean_animation for prop-aware variant) ---
    "clean":        {"walking": "walk", "using": "clean_generic", "finishing": "idle"},
    "clean_floor":  {"walking": "walk", "using": "mop",           "finishing": "idle"},
    "sweep":        {"walking": "walk", "using": "sweep",         "finishing": "idle"},
    "scrub":        {"walking": "walk", "using": "scrub",         "finishing": "idle"},
    "wipe":         {"walking": "walk", "using": "wipe",          "finishing": "idle"},
    "wash_dishes":  {"walking": "walk", "using": "wash_dishes",   "finishing": "idle"},
    "window_clean": {"walking": "walk", "using": "window_wipe",   "finishing": "idle"},

    # --- generic fallback ---
    "interact":     {"walking": "walk", "using": "interact",   "finishing": "idle"},
}


# =========================================================
# CLEAN ANIMATION RESOLVER
# Picks the right cleaning animation based on prop tags,
# overriding the generic "clean" entry above.
# =========================================================

_CLEAN_TAG_ANIMATIONS = [
    ({"floor", "carpet", "rug"},                "mop"),
    ({"toilet", "sink", "bathtub", "shower"},   "scrub"),
    ({"table", "counter", "desk", "surface"},   "wipe"),
    ({"window", "glass", "mirror"},             "window_wipe"),
    ({"dish", "plate", "bowl", "cup"},          "wash_dishes"),
]

# =========================================================
# PROP ANIMATION STATES
# Controls what anim_state is set on the prop when a character
# enters the "using" phase and when the interaction finishes.
# The frontend plays the GLB clip matching the state name.
#
# Convention for prop GLB clip names:
#   open, close, activated, flushing, on, off, idle
# =========================================================

_PROP_ANIM_STATES = {
    # interaction         (on_use,       on_finish)
    "open":              ("open",         None),        # stays open
    "open_door":         ("open",         "closed"),    # auto-closes
    "close_door":        ("closed",       None),
    "open_cabinet":      ("open",         "closed"),
    "close_cabinet":     ("closed",       None),
    "open_fridge":       ("open",         "closed"),
    "open_drawer":       ("open",         "closed"),
    "close_drawer":      ("closed",       None),
    "press_button":      ("activated",    "idle"),
    "press":             ("activated",    "idle"),
    "flush":             ("flushing",     "idle"),
    "turn_on":           ("on",           None),
    "turn_off":          ("off",          None),
}


def _set_prop_anim(prop, state):
    """Set prop["anim_state"] if prop exists and state is not None."""
    if prop is not None and state is not None:
        prop["anim_state"] = state


def get_clean_animation(prop, phase="using"):
    """Return the cleaning animation for a given prop based on its tags."""
    if phase != "using":
        return "idle" if phase == "finishing" else "walk"
    tags = set(prop.get("tags", []))
    for tag_set, anim in _CLEAN_TAG_ANIMATIONS:
        if tags & tag_set:
            return anim
    return "clean_generic"


def get_phase_animation(interaction, phase):
    """Return the animation name for a given interaction + phase.

    Values in INTERACTION_ANIMATIONS may be a string (single clip) or a list
    of strings (variants). When a list is given, one is chosen at random so
    that the same interaction doesn't always play the same clip.
    Falls back to sensible defaults when no mapping exists.
    """
    entry = INTERACTION_ANIMATIONS.get(interaction)
    if entry:
        val = entry.get(phase, "idle")
        if isinstance(val, list):
            return random.choice(val)
        return val
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

    # =====================================================
    # CARRY — special multi-leg phases
    # picking_up → delivering → put_down
    # =====================================================

    if interaction == "carry":

        phase = act.get("phase", "picking_up")

        if phase == "walking":
            # Walking to the prop to pick up
            if c.get("is_moving"):
                return True
            # Arrived at prop — attach it to character
            prop = get_prop_by_id(world, act.get("target_id"))
            if prop:
                prop["carried_by"] = c["id"]
                prop["visible"] = False   # hide world instance; frontend shows carried model
                c["carrying"] = act.get("target_id")
            set_activity_phase(act, "picking_up", world)
            c["animation_state"] = "pick_up"
            return True

        if phase == "picking_up":
            # Brief pickup animation, then route to destination
            elapsed = world["tick"] - act["phase_started_tick"]
            if elapsed < 3:
                return True
            dest = act.get("destination", {})
            c["move_target"] = {
                "x": dest.get("x", c.get("x", 0)),
                "y": dest.get("y", c.get("y", 0)),
                "target_type": "tile",
            }
            c["is_moving"] = True
            set_activity_phase(act, "delivering", world)
            c["animation_state"] = "carry_walk"
            return True

        if phase == "delivering":
            # Walking to destination while carrying
            if c.get("is_moving"):
                c["animation_state"] = "carry_walk"
                return True
            set_activity_phase(act, "put_down", world)
            c["animation_state"] = "put_down"
            return True

        if phase == "put_down":
            # Release prop at current position
            prop = get_prop_by_id(world, act.get("target_id"))
            if prop:
                prop["x"] = c.get("x", 0)
                prop["y"] = c.get("y", 0)
                prop.pop("carried_by", None)
                prop["visible"] = True
            c.pop("carrying", None)
            finish_activity(c, world)
            return False

        return True

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

        # Resolve animation: clean gets prop-aware variant
        if interaction in ("clean", "clean_floor", "sweep", "scrub",
                           "wipe", "wash_dishes", "window_clean"):
            using_anim = get_clean_animation(prop, "using") if prop else "clean_generic"
        else:
            using_anim = get_phase_animation(interaction, "using")

        # Trigger prop animation (door opens, button activates, etc.)
        _set_prop_anim(prop, _PROP_ANIM_STATES.get(interaction, (None, None))[0])

        set_activity_phase(act, "using", world)
        c["animation_state"] = using_anim
        return True

    # =====================================================
    # USING  — tick elapsed time
    # =====================================================

    if act["phase"] == "using":

        elapsed = world["tick"] - act["phase_started_tick"]

        if elapsed >= act["duration"]:

            # Trash/Destroy: remove prop from world on completion
            if interaction in ("trash", "destroy"):
                prop = get_prop_by_id(world, act.get("target_id"))
                if prop:
                    props = world.get("props", {})
                    pid = prop.get("id")
                    if isinstance(props, dict):
                        props.pop(pid, None)
                    else:
                        world["props"] = [p for p in props if p.get("id") != pid]

            # Reset prop animation (door closes, button returns to idle, etc.)
            prop = get_prop_by_id(world, act.get("target_id"))
            _set_prop_anim(prop, _PROP_ANIM_STATES.get(interaction, (None, None))[1])

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

        from systems.cooking_process import (
            start_cooking_process
        )

        household = world[
            "households"
        ].get(
            c.get("household_id")
        )

        if household:

            recipe_id = choose_recipe(

                c,

                household
            )

            if recipe_id:

                start_cooking_process(

                    c,

                    household,

                    recipe_id,

                    world
                )         
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
    elif activity_type == "check_mail":

        household = world[
            "households"
        ].get(
            c.get("household_id")
        )

        if household:

            household.setdefault(
                "mailbox",
                {}
            )

            household[
                "mailbox"
            ][
                "has_mail"
            ] = False

            c.setdefault(
                "mail_history",
                []
            )

            delivered = household.get(
                "delivered_mail",
                []
            )

            c[
                "mail_history"
            ].extend(delivered)

            household[
                "delivered_mail"
            ] = []
    elif activity_type == "sort_mail":

        household = world[
            "households"
        ].get(
            c.get("household_id")
        )

        if household:
            sort_household_mail(household, world)
    elif activity_type == "retrieve_package":

        household = world[
            "households"
        ].get(
            c.get("household_id")
        )

        if household:

            packages = household.get(
                "pending_packages",
                []
            )

            for package in packages:

                acquire_product(

                    household,

                    package
                )

            household[
                "pending_packages"
            ] = []
    elif activity_type == "take_out_trash":

        household = world[
            "households"
        ].get(
            c.get("household_id")
        )

        if household:

            household[
                "trash_level"
            ] = max(

                0,

                household[
                    "trash_level"
                ] - 0.5
            )

            household.setdefault(
                "garbage_bin",
                {}
            )

            household[
                "garbage_bin"
            ][
                "fullness"
            ] = min(

                1.0,

                household[
                    "garbage_bin"
                ].get(
                    "fullness",
                    0
                ) + 0.5
            )
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
