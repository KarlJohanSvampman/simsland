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
from systems.interactions import (
    request_route_to_anchor
)
from systems.props import (
    find_nearest_anchor,
    get_prop_by_id,
    get_anchor,
)

from systems.interactions import (
    begin_interaction
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
    # "using" reuses "lie_idle" (not a separate "sleep_idle") — sleep is
    # modeled as the "lying" stance's idle animation, same as just lying
    # down awake; there's no distinct sleep stance.
    "sleep":        {"walking": "walk", "using": "lie_idle",   "finishing": "wake_up"},

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

    # --- phone (real interaction strings action_router.py's phone_*
    # routes scaffold with -- _scaffold() sets interaction=activity_type,
    # which doesn't match the generic "phone"/"use_computer" keys above,
    # so these fell through to the generic "interact" default before
    # this. Two distinct loops per the animation-loops round: ear-hold
    # for calls (reuses the existing "phone" stem/variants), screen-tap
    # for texting/checking/reading (new "phone_screen" stem -- see
    # frontend/src/main.js's ANIM_LAYERS/ANIM_VARIANTS). ---
    "phone_call":       {"walking": "walk", "using": ["phone", "phone_gesture"], "finishing": "idle"},
    "phone_answer":     {"walking": "walk", "using": ["phone", "phone_gesture"], "finishing": "idle"},
    "phone_send_text":  {"walking": "walk", "using": "phone_screen", "finishing": "idle"},
    "phone_check":      {"walking": "walk", "using": "phone_screen", "finishing": "idle"},
    "phone_read_text":  {"walking": "walk", "using": "phone_screen", "finishing": "idle"},

    # --- work ---
    "work":         {"walking": "walk", "using": ["work", "work_type", "work_read"], "finishing": "idle"},

    # --- computer (real interaction strings action_router.py's
    # _route_computer* family scaffolds with -- same gap as phone above.
    # Reuses "work"'s existing stem/variants (already includes
    # "work_type") -- sitting-and-typing, no new frontend clips needed. ---
    "computer_social_media":     {"walking": "walk", "using": ["work", "work_type", "work_read"], "finishing": "idle"},
    "computer_videos":           {"walking": "walk", "using": ["work", "work_type", "work_read"], "finishing": "idle"},
    "computer_game":             {"walking": "walk", "using": ["work", "work_type", "work_read"], "finishing": "idle"},
    "computer_wiki_research":    {"walking": "walk", "using": ["work", "work_type", "work_read"], "finishing": "idle"},
    "computer_news":             {"walking": "walk", "using": ["work", "work_type", "work_read"], "finishing": "idle"},
    "computer_window_shopping":  {"walking": "walk", "using": ["work", "work_type", "work_read"], "finishing": "idle"},
    "computer_dating":           {"walking": "walk", "using": ["work", "work_type", "work_read"], "finishing": "idle"},
    "computer_job_search":       {"walking": "walk", "using": ["work", "work_type", "work_read"], "finishing": "idle"},
    "computer_apply_for_job":    {"walking": "walk", "using": ["work", "work_type", "work_read"], "finishing": "idle"},
    "computer_send_email":       {"walking": "walk", "using": ["work", "work_type", "work_read"], "finishing": "idle"},
    "computer_respond_email":    {"walking": "walk", "using": ["work", "work_type", "work_read"], "finishing": "idle"},
    "computer_check_email":      {"walking": "walk", "using": ["work", "work_type", "work_read"], "finishing": "idle"},

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
    "load_dishwasher": {"walking": "walk", "using": "fill_container", "finishing": "idle"},
    "clean_floors": {"walking": "walk", "using": "sweep",         "finishing": "idle"},
    "dust_and_wipe": {"walking": "walk", "using": "wipe",         "finishing": "idle"},
    "window_clean": {"walking": "walk", "using": "window_wipe",   "finishing": "idle"},

    # --- laundry (fill hand-off into systems/task_process.py; the rest of
    # the wash/dry/fold/put-away chain progresses in the background, not
    # through activities.py — see chore_templates["laundry_load"]) ---
    "do_laundry":   {"walking": "walk", "using": "fill_container", "finishing": "idle"},

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


def set_activity_phase(act, phase, world):
    """Transition an activity to a new phase and reset its phase clock.

    Every phase-elapsed check in this file (e.g. the "USING" tick-elapsed
    branch) reads act["phase_started_tick"] relative to world["tick"], so
    the two must always change together.
    """
    act["phase"] = phase
    act["phase_started_tick"] = world.get("tick", 0)


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

    # Individual wait activity, first example — start the microwave, then
    # the character is free (c["activity"] clears normally via
    # finish_activity(), same as any other activity) while
    # c["character_wait"] ticks in the background. See complete_activity()
    # below and sim_loop.py's character_wait cadence block.
    "start_microwave": {

        "interaction": "microwave",

        "base_duration_minutes": 1,

        "interruptible": True,

        "category": "food"
    },

    "take_out_of_microwave": {

        "interaction": "microwave",

        "base_duration_minutes": 1,

        "interruptible": True,

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

    "read_newspaper": {

        "interaction": "read",

        "base_duration_minutes": 30,

        "interruptible": True,

        "category": "leisure"
    },

    "browse_news": {

        "interaction": "phone",

        "base_duration_minutes": 30,

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

    # Loads the washing machine, then hands off to systems/task_process.py
    # (start_process(), "laundry_load" chore) — the wash cycle, emptying,
    # hanging, folding, and putting away all progress in the background
    # from there (systems/sim_loop.py's update_household_processes()), not
    # through further activities.py entries. See complete_activity()'s
    # do_laundry_fill branch below, mirroring cook_recipe's hand-off to
    # systems/cooking_process.py.
    "do_laundry_fill": {

        "interaction": "do_laundry",

        "base_duration_minutes": 3,

        "interruptible": True,

        "category": "maintenance"
    },

    # Hand off into systems/task_process.py's "dishes_manual" process,
    # mirroring do_laundry's fill-then-background-progress shape (see
    # complete_activity()'s wash_dishes branch) -- "sink" was never a
    # real anchor interaction name (kitchen_sink's own anchor is named
    # "wash_dishes"), so this action never actually found a target before.
    "wash_dishes": {

        "interaction": "wash_dishes",

        "base_duration_minutes": 5,

        "interruptible": True,

        "category": "chore"
    },
    # Hand off into "dishes_machine" -- see dishwasher's own anchor
    # (interaction "load_dishwasher").
    "load_dishwasher": {

        "interaction": "load_dishwasher",

        "base_duration_minutes": 5,

        "interruptible": True,

        "category": "chore"
    },
    # Zone-scoped, not prop-scoped -- "clean wherever you currently are"
    # has no single prop to walk to. no_target tells start_activity() to
    # skip begin_interaction()'s anchor search entirely (see there).
    "clean_floors": {

        "no_target": True,

        "base_duration_minutes": 3,

        "interruptible": True,

        "category": "chore"
    },
    "dust_and_wipe": {

        "no_target": True,

        "base_duration_minutes": 3,

        "interruptible": True,

        "category": "chore"
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
    # TRANSPORTATION
    # =====================================================

    "order_taxi": {

        # Multi-phase, see execute_activity()'s "order_taxi" phase block
        # below -- order (call/app) -> walk to pickup spot -> wait.
        "interaction": "order_taxi",

        "base_duration_minutes": 30,

        "interruptible": True,

        "category": "errand"
    },

    # =====================================================
    # SOCIAL
    # =====================================================

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

    # Real on-grid walk-up-and-buy at the convenience store's register
    # (systems/convenience_store.py) -- distinct from "go_shopping"/
    # "buy_food" above, which are unimplemented placeholders tied to the
    # abstracted off-grid errand system, not a physical prop.
    "convenience_store_checkout": {

        "interaction": "checkout",

        "base_duration_minutes": 6,

        "interruptible": False,

        "category": "errands"
    },

    "use_atm": {

        "interaction": "use_atm",

        "base_duration_minutes": 3,

        "interruptible": False,

        "category": "errands"
    },

    # Reuses prop_templates["wardrobe"]'s existing "anchor_change_clothes"
    # anchor (interaction "change_clothes") -- authored content that had
    # no activity referencing it until systems/dressing.py.
    "get_dressed": {

        "interaction": "change_clothes",

        "base_duration_minutes": 5,

        "interruptible": False,

        "category": "self_care"
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

    duration = compute_duration_ticks(

        c,

        config[
            "base_duration_minutes"
        ]
    )

    # no_target activities (systems/chores.py's clean_floors/dust_and_wipe
    # -- "clean wherever you currently are") have no prop to walk to at
    # all, so there's no anchor to find -- start straight at "using",
    # same as action_router.py's _scaffold()-based actions (jog, etc.).
    if config.get("no_target"):
        c["activity"] = {
            "type": activity_type,
            "phase": "using",
            "phase_started_tick": world["tick"],
            "duration": duration,
            "state": {},
        }
        from core.event_bus import emit
        emit("activity_started", {"character_id": c["id"], "activity_type": activity_type})
        return True

    interaction = begin_interaction(

        c,

        world,

        config["interaction"]
    )
    if not interaction:
        return False

    prop = interaction["prop"]
    anchor = interaction["anchor"]

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

    # convenience_store_checkout has no external caller-supplied item --
    # pick from the register's own catalog (definitions.json's "register"
    # prop_template) right here at start, same as every other activity
    # resolves its own specifics without external input.
    if activity_type == "convenience_store_checkout" and prop.get("catalog"):
        import random as _random
        from systems.clothing import is_body_compatible
        item_templates = world.get("definitions", {}).get("item_templates", {})
        stock = [
            entry for entry in prop["catalog"]
            if is_body_compatible(item_templates.get(entry["item_template"], {}), c.get("model"))
        ]
        if stock:
            c["activity"]["state"]["catalog_entry"] = _random.choice(stock)

    request_route_to_anchor(

        c,

        world,

        prop,

        anchor
    )

    from core.event_bus import emit
    emit("activity_started", {"character_id": c["id"], "activity_type": activity_type})

    return True

# =========================================================
# USE SEAT / FINISH SEATED
# =========================================================
# Sitting is open-ended: reaching the "using" phase marks the queue task
# done and clears the activity so a dependent task (e.g. a hobby session)
# can dispatch next while the character stays seated. Standing back up is
# driven externally — by complete_activity()'s hobby-session branch, or an
# explicit stand_up route — via _finish_seated(), not by this function
# staying active.

def _execute_use_seat(c, world, act):
    from systems.posture import set_posture

    phase = act.get("phase", "walking")

    if phase == "walking":
        if c.get("is_moving"):
            return True

        # Arrived — anchor onto the seat and sit down. seat_prop_id is set
        # on the character (not just the activity dict) because that's
        # what complete_activity()'s hobby-session branch and
        # _finish_seated() both read to know a character is seated.
        c["seat_prop_id"] = act.get("seat_prop_id")
        set_posture(c, world, "sitting_seat")
        set_activity_phase(act, "using", world)
        return True

    if phase == "using":
        from systems.activity_queue import mark_queue_task_done
        mark_queue_task_done(c, "use_seat", success=True)
        c["activity"] = None
        c["current_intention"] = None
        return False

    return True


def _finish_seated(c, world):
    from systems.posture import set_posture

    c.pop("seat_prop_id", None)
    release_anchor(c, world)
    set_posture(c, world, "standing")


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
                # If carrying a seat to a target prop, rotate it to face the target
                if act.get("is_seat_carry"):
                    target_prop = get_prop_by_id(world, act.get("destination", {}).get("target_prop_id"))
                    if target_prop:
                        import math
                        dx = target_prop["x"] - prop["x"]
                        dy = target_prop["y"] - prop["y"]
                        prop["rotation"] = round(math.degrees(math.atan2(dx, dy)) / 90) * 90
            c.pop("carrying", None)
            from systems.activity_queue import mark_queue_task_done
            mark_queue_task_done(c, "carry_seat", success=True)
            finish_activity(c, world)
            return False

        return True

    # =====================================================
    # ORDER TAXI — order (call/app) -> walk to pickup spot -> wait for
    # the vehicle (systems/rideshare.py). Placed before walking so it
    # can manage its own movement, same as CARRY above.
    # =====================================================

    if interaction == "order_taxi":

        phase = act.get("phase", "ordering")

        if phase == "ordering":
            method = act.get("params", {}).get("method", "phone_app")
            if method == "phone_call":
                from systems.action_router import _route_order_taxi_by_phone_call as _order
            else:
                from systems.action_router import _route_order_taxi_by_phone_app as _order
            _order(c, world, {"destination": act.get("params", {}).get("destination")})

            if not c.get("pickup_request", {}).get("vehicle_id"):
                # Couldn't order (no phone/app/road network) -- bail out
                # of the activity rather than waiting forever.
                finish_activity(c, world)
                return False

            pickup = c["pickup_request"]["location"]
            from systems.road_network import nearest_road_tile
            spot = nearest_road_tile(world, pickup["x"], pickup["y"]) or (pickup["x"], pickup["y"])
            c["move_target"] = {"x": spot[0], "y": spot[1], "target_type": "tile"}
            c["is_moving"] = True
            set_activity_phase(act, "walking_to_pickup", world)
            c["animation_state"] = "walk"
            return True

        if phase == "walking_to_pickup":
            if c.get("is_moving"):
                return True
            set_activity_phase(act, "waiting_for_taxi", world)
            c["animation_state"] = "idle"
            return True

        if phase == "waiting_for_taxi":
            status = c.get("pickup_request", {}).get("status")
            if status in ("in_transit", "arrived"):
                finish_activity(c, world)
                return False
            return True

        return True

    # =====================================================
    # SEARCH ROOM — walk to each container prop, check contents
    # Placed before walking so it can manage its own movement.
    # =====================================================

    if activity_type == "search_room":
        return _execute_search_room(c, world, act)

    # =====================================================
    # RETRIEVE ITEM — walk to container, pick up item, carry to dest
    # =====================================================

    if activity_type in ("retrieve_item", "return_item"):
        return _execute_retrieve_or_return(c, world, act)

    # =====================================================
    # USE SEAT — walk to chair, sit, mark as seated
    # =====================================================

    if activity_type == "use_seat":
        return _execute_use_seat(c, world, act)

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

    if act.get("phase", "using") == "using":

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
                    # "destroy" is a real offense (vandalism), not the
                    # legitimate garbage disposal "trash" is -- see
                    # systems/emergency.py::report_property_damage_incident,
                    # picked up by action_router.py::_route_call_parent /
                    # context_builder.py's call_parent-offering logic with
                    # zero changes to either.
                    if interaction == "destroy":
                        try:
                            from systems.emergency import report_property_damage_incident
                            report_property_damage_incident(world, c, prop)
                        except Exception:
                            pass
                        # Curiosity hook (systems/curiosity.py): a real
                        # audible event a nearby character could notice
                        # and go investigate -- see brain/perception.py's
                        # VOLUME_TIERS.
                        try:
                            from brain.perception import emit_ambient_sound
                            emit_ambient_sound(world, prop["x"], prop["y"], "breaking_glass", "loud")
                        except Exception:
                            pass

            # Reset prop animation (door closes, button returns to idle, etc.)
            prop = get_prop_by_id(world, act.get("target_id"))
            _set_prop_anim(prop, _PROP_ANIM_STATES.get(interaction, (None, None))[1])

            complete_activity(c, world, act)
            set_activity_phase(act, "finishing", world)
            c["animation_state"] = get_phase_animation(interaction, "finishing")

            # Wake the character for a fresh (brief-mode) think() once the
            # finishing animation plays out — see brain/cognition_scheduler.py.
            # Deliberately only fired on this specific transition, not every
            # set_activity_phase() call (walking/picking_up/delivering/etc.
            # are still mid-activity and the existing c["activity"] gate
            # already short-circuits update_agent() for those).
            from core.event_bus import emit
            from brain.cognition_scheduler import wake_character
            emit("activity_phase_changed", {
                "character_id": c["id"],
                "activity_type": act.get("type"),
                "from_phase": "using",
                "to_phase": "finishing",
            })
            wake_character(c, world, "activity_phase_changed")

        return True

    # =====================================================
    # FINISHING  — one tick to play finishing animation
    # =====================================================

    if act.get("phase", "using") == "finishing":

        finish_activity(c, world)
        return False

    return True
#=======================================================
# REAL ITEM RESOLUTION FOR EAT/DRINK COMPLETION
# =========================================================
# complete_activity()'s eat_snack/drink_water/eat branches used to look
# up act["target_id"] (always a PROP id -- fridge/table/sink, see
# start_activity() above) in world.get("items", {}), a dict nothing in
# the backend ever writes to -- so real fridge/cabinet/bowl stock was
# never actually consumed, only a small flat fallback applied regardless.
# These helpers resolve against where items really live: prop storage
# (systems/containers.py's ensure_prop_storage, e.g. fridge_a/
# kitchen_cabinet), placed containers (a fruit bowl), and the character's
# own inventory/held_stack.

def _household_storage_containers(c, world):
    """Yields every real storage container belonging to c's household --
    fridge/cabinet/counter props and food-capable placed items (e.g. a
    fruit bowl) -- the actual physical stock behind the abstract
    household_storage.py resource-pool hints resolve_hunger_strategy()
    checks to decide whether to pursue eating at all."""
    from systems.containers import ensure_prop_storage, ensure_item_container

    household = world.get("households", {}).get(c.get("household_id"))
    building_ids = set(household.get("building_ids", [])) if household else set()

    for prop in world.get("props", []):
        if prop.get("building_id") not in building_ids:
            continue
        container = ensure_prop_storage(prop, world)
        if container:
            yield container

    for item in world.get("placed_items", {}).values():
        container = item if "items" in item else ensure_item_container(item, world)
        if container:
            yield container


def _find_and_consume_food(c, world, category="food"):
    """Pulls one matching item out of the character's household's real
    storage, returns the removed item (make_item()'s flat template
    fields -- category/nutrition/etc. -- are already merged onto it, so
    on_consume_complete can read them directly), or None if nothing
    matching exists anywhere in the household."""
    from systems.containers import remove_from_container

    for container in _household_storage_containers(c, world):
        for entry in list(container.get("items", [])):
            if entry.get("category") == category:
                removed = remove_from_container(container, entry["id"], quantity=1)
                if removed.get("success"):
                    return removed["item"]
    return None


def _take_item_anywhere(c, world, item_id):
    """Removes and returns the item instance matching item_id from
    wherever it actually is -- the character's own inventory/held_stack,
    a household storage container, or a bare placed item. Used by the
    "eat"/"drink_alcohol"/"have_drink" LLM-direct actions
    (action_router.py::_route_eat and friends) to resolve+consume the
    one specific item the LLM referenced -- unlike
    _find_and_consume_food() above, which picks ANY matching-category
    item rather than a pre-chosen id."""
    for pool in (c.get("inventory", []), c.get("held_stack", [])):
        for i, item in enumerate(pool):
            if item.get("id") == item_id:
                return pool.pop(i)

    from systems.containers import remove_from_container
    for container in _household_storage_containers(c, world):
        removed = remove_from_container(container, item_id)
        if removed.get("success"):
            return removed["item"]

    placed = world.get("placed_items", {})
    if item_id in placed:
        return placed.pop(item_id)

    return None


_GLASS_TEMPLATE_IDS = ("glass_water", "glass_wine", "glass_rocks")


def _find_clean_glass(c):
    """A character's own clean drinking glass (pocket/held/worn) -- see
    the DRINK completion branch below. Not removed/consumed -- glasses
    are reusable, just marked dirty until washed (systems/activities.py's
    existing wash_dishes activity)."""
    for pool in (c.get("inventory", []), c.get("held_stack", [])):
        for item in pool:
            if item.get("template_id") in _GLASS_TEMPLATE_IDS and not item.get("states", {}).get("dirty"):
                return item
    for item in (c.get("worn") or {}).values():
        if item and item.get("template_id") in _GLASS_TEMPLATE_IDS and not item.get("states", {}).get("dirty"):
            return item
    return None


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
    # ADVANCE ACTIVITY QUEUE
    # =====================================

    from systems.activity_queue import mark_queue_task_done
    mark_queue_task_done(c, activity_type, success=True)

    # Expectation completion -- must read _active_hobby_params BEFORE the
    # "HOBBY SESSION" block below pops it. No-ops instantly if this
    # activity wasn't dispatched for an expectation (the common case).
    from systems.expectation_planner import on_expectation_activity_complete
    on_expectation_activity_complete(c, world, c.get("_active_hobby_params"))

    # =====================================
    # HOBBY SESSION — consume item uses
    # and queue put-away for organized chars
    # =====================================

    if activity_type == "hobby_session" or c.get("_active_hobby_params"):
        hobby_params = c.pop("_active_hobby_params", None) or act
        from systems.hobby_planner import consume_hobby_uses
        consume_hobby_uses(c, world, hobby_params)
        # Stand up if the character was seated for this hobby
        if c.get("seat_prop_id"):
            _finish_seated(c, world)

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

    from systems.body import (
        on_sleep_complete, on_shower_complete, on_bath_complete,
        on_brush_teeth_complete, on_wash_hands_complete,
        on_eat_complete, on_drink_complete, on_toilet_complete,
    )

    if activity_type == "sleep":
        duration = c.get("activity", {}).get("duration", 28800) / 60
        on_sleep_complete(c, duration, world=world)
        # Posture bookkeeping — set_posture() also writes a transient
        # "lying_to_standing" animation_state, but the very next line in
        # the caller (the "using" phase's completion branch) immediately
        # overwrites it with the "finishing" phase's wake_up clip, so the
        # transition key itself is never actually rendered here. That's
        # fine: promote_pending_posture() no-ops safely once it sees
        # animation_state no longer matches what it armed (see its guard),
        # and wake_up -> idle already carries the character to a sane
        # resting animation via finish_activity() a tick later.
        from systems.posture import set_posture
        set_posture(c, world, "standing")

    # =====================================
    # TOILET
    # =====================================

    elif activity_type in ("use_toilet", "use_toilet_bowels"):
        on_toilet_complete(c)
        if activity_type == "use_toilet_bowels" and random.random() < 0.35:
            try:
                from systems.reactions import trigger_reaction
                trigger_reaction(c, world, "gas_release", tick=world.get("tick", 0))
            except Exception:
                pass

    # =====================================
    # SHOWER / BATH
    # =====================================

    elif activity_type == "take_shower":
        on_shower_complete(c)

    elif activity_type == "take_bath":
        on_bath_complete(c)

    # =====================================
    # TEETH / HANDS
    # =====================================

    elif activity_type == "brush_teeth":
        on_brush_teeth_complete(c)

    elif activity_type == "wash_hands":
        on_wash_hands_complete(c)

    # =====================================
    # DRINK
    # =====================================

    elif activity_type in ("drink", "drink_water"):
        # Tap water at a sink -- see strategy.py::resolve_thirst_strategy
        # and the new "drink" anchor on kitchen_sink/bathroom_sink.
        # Properly filling and drinking from a glass hydrates well; no
        # clean glass on hand still works (cupped hands), just less
        # effectively -- never a hard block, so a character can't get
        # soft-locked out of hydrating entirely.
        glass = _find_clean_glass(c)
        if glass:
            glass.setdefault("states", {})["dirty"] = True
            on_drink_complete(c, hydration_value=35, volume=20)
        else:
            on_drink_complete(c, hydration_value=15)

    elif activity_type in ("drink_alcohol", "have_drink"):
        from systems.body import on_consume_complete
        target_id = act.get("target_id")
        item = _take_item_anywhere(c, world, target_id) if target_id else None
        if item:
            on_consume_complete(c, world, item)
        else:
            on_drink_complete(c, hydration_value=35)

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
                from systems.body import on_consume_complete
                on_consume_complete(c, world, meal)
                meal["servings"] -= 1
                if meal["servings"] <= 0:
                    remove_household_resource(household, meal, 1)
                elif meal["servings"] > 0:
                    from systems.resource_runtime import convert_meal_to_leftovers
                    convert_meal_to_leftovers(meal)

    # =====================================
    # COOK
    # =====================================
    elif activity_type == "cook_recipe":

        from systems.cooking_process import start_cooking_process, choose_recipe

        household = world["households"].get(c.get("household_id"))

        if household:
            recipe_id = choose_recipe(c, world, household)
            if recipe_id:
                start_cooking_process(c, household, recipe_id, world)

    # =====================================
    # LAUNDRY — hand off to the household-scoped process engine
    # =====================================
    elif activity_type == "do_laundry_fill":

        from systems.task_process import start_process, resolve_stages

        household = world["households"].get(c.get("household_id"))

        if household:
            chore = (world.get("definitions") or {}).get("chore_templates", {}).get("laundry_load")
            if chore:
                stages = resolve_stages(world, chore["stages"])
                # If this fill was the result of an accepted chore
                # proposal (systems/proposals.py), the resolved
                # participant list is waiting in this single-slot
                # hand-off cache — consume it here. Falls back to solo
                # (just this character) for the ordinary un-proposed path,
                # unchanged from before.
                pending = household.pop("_pending_chore", None)
                if pending and pending.get("chore_id") == "laundry_load":
                    participants = pending.get("participants") or [c["id"]]
                else:
                    participants = [c["id"]]
                start_process(household, world, "laundry", "laundry_load", stages,
                               prop_id=act.get("target_id"), participants=participants)

    # =====================================
    # DISHES — manual (sink) and machine (dishwasher) variants, same
    # hand-off shape as laundry above. Manual's per-item wash/rinse/dry/
    # put-away group is repeated once per real dirty dish (see
    # systems/chores.py::dish_count_for_wash()) rather than being a fixed
    # stage count.
    # =====================================
    elif activity_type in ("wash_dishes", "load_dishwasher"):

        from systems.task_process import start_process, resolve_stages
        from systems.chores import dish_count_for_wash, kitchen_zone_key

        household = world["households"].get(c.get("household_id"))

        if household:
            manual = activity_type == "wash_dishes"
            template_id = "wash_dishes_manual" if manual else "wash_dishes_machine"
            chore = (world.get("definitions") or {}).get("chore_templates", {}).get(template_id)
            if chore:
                stage_defs = list(chore.get("stages", []))
                if manual:
                    n = dish_count_for_wash(household)
                    stage_defs = stage_defs + list(chore.get("per_item_stages", [])) * n
                stages = resolve_stages(world, stage_defs)
                pending = household.pop("_pending_chore", None)
                if pending and pending.get("chore_id") == template_id:
                    participants = pending.get("participants") or [c["id"]]
                else:
                    participants = [c["id"]]
                start_process(household, world, "dishes_manual" if manual else "dishes_machine",
                               template_id, stages, prop_id=act.get("target_id"),
                               participants=participants,
                               zone_key=kitchen_zone_key(world, household))

    # =====================================
    # ZONE CLEANING — floors / surfaces. Not prop-anchored (see
    # action_router.py's _route_clean_floors/_route_dust_and_wipe --
    # these are scaffolded actions, not ACTIVITIES-dict entries, since
    # "clean wherever you currently are" has no single prop to walk to).
    # =====================================
    elif activity_type in ("clean_floors", "dust_and_wipe"):

        from systems.task_process import start_process, resolve_stages
        from systems.chores import zone_key_for_character, surface_count_in_zone

        household = world["households"].get(c.get("household_id"))
        zone_key = zone_key_for_character(c)

        if household and zone_key:
            chore = (world.get("definitions") or {}).get("chore_templates", {}).get(activity_type)
            if chore:
                stage_defs = list(chore.get("stages", []))
                if activity_type == "dust_and_wipe":
                    n = surface_count_in_zone(world, zone_key)
                    stage_defs = stage_defs + list(chore.get("per_item_stages", [])) * max(1, n)
                stages = resolve_stages(world, stage_defs)
                pending = household.pop("_pending_chore", None)
                if pending and pending.get("chore_id") == activity_type:
                    participants = pending.get("participants") or [c["id"]]
                else:
                    participants = [c["id"]]
                process_type = "floors" if activity_type == "clean_floors" else "dusting"
                start_process(household, world, process_type, activity_type, stages,
                               participants=participants, zone_key=zone_key)

    # =====================================
    # INDIVIDUAL WAIT — microwave
    # =====================================
    elif activity_type == "start_microwave":

        wait_minutes = act.get("state", {}).get("wait_minutes", 3)
        c["character_wait"] = {
            "type":               "microwave",
            "prop_id":            act.get("target_id"),
            "ready_at_tick":      world.get("tick", 0) + wait_minutes * 60,
            "resume_interaction": "take_out_of_microwave",
            "ready":              False,
        }
        # c["activity"] clears normally via finish_activity() right after
        # this branch returns — the character is genuinely free from here,
        # unlike household chores/recipes where a background process
        # object keeps ticking; here it's just this one timer.

    elif activity_type == "take_out_of_microwave":

        wait = c.get("character_wait")
        if wait and wait.get("type") == "microwave":
            from systems.household_storage import create_household_resource
            household = world["households"].get(c.get("household_id"))
            if household:
                create_household_resource(household, "MEAL", quantity=1, servings=1,
                                           nutrition=0.5, quality=0.5, container="held")
        c["character_wait"] = None

    # =====================================
    # SNACK
    # =====================================

    elif activity_type == "eat_snack":
        from systems.body import on_consume_complete
        item = _find_and_consume_food(c, world, category="food")
        if item:
            on_consume_complete(c, world, item)
        else:
            on_eat_complete(c, nutrition=0.05)

    # =====================================
    # EXERCISE — jog/sit_ups/chin_ups/lift_weights (action_router.py) all
    # land here. hobby_id maps into the pre-existing but previously-
    # unreachable systems/exercise.py pipeline via satisfy_lt_need();
    # jog/lift_weights reuse the existing running/weightlifting registry
    # entries, sit_ups/chin_ups are new balanced-type entries.
    # =====================================

    elif activity_type in ("jog", "sit_ups", "chin_ups", "lift_weights"):
        hobby_id = {
            "jog":          "running",
            "sit_ups":      "sit_ups",
            "chin_ups":     "chin_ups",
            "lift_weights": "weightlifting",
        }[activity_type]
        has_companion = any(
            other.get("building_id") == c.get("building_id") and other["id"] != c["id"]
            for other in world.get("characters", {}).values()
        )
        from systems.lt_needs import satisfy_lt_need
        satisfy_lt_need(c, "exercise", world, hobby_id=hobby_id, has_companion=has_companion)

    # =====================================
    # PHONE — the phone actions (action_router.py) set the phone's
    # location to "held" for the duration; put it back in the pocket
    # once the activity finishes. retrieve_phone re-acquires a phone
    # that was set down/forgotten (systems/phone.py) and clears the
    # location memory -- pick_up_item already sets location="pocket".
    # =====================================

    elif activity_type in ("phone_call", "phone_answer", "phone_send_text",
                            "phone_check", "phone_read_text"):
        from systems.personal_items import get_phone
        phone = get_phone(c)
        if phone:
            phone["location"] = "pocket"

    elif activity_type == "retrieve_phone":
        from systems.phone import ensure_phone_state
        from systems.personal_items import pick_up_item
        state = ensure_phone_state(c)
        loc = state.get("last_known_location")
        if loc and loc.get("prop_id"):
            pick_up_item(c, loc["prop_id"], world)
        state["last_known_location"] = None
        state["forgotten"] = False

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

            sort_household_mail(household, world)

    # =====================================
    # ADULT CONTENT — porn habit + sexism drift
    # =====================================
    if activity_type in ("watch_porn", "masturbate"):
        try:
            from systems.harassment import on_porn_session
            on_porn_session(c, world)
        except Exception:
            pass

        # Discoverable history if a shared household computer was used
        # for this -- see action_router.py::_route_check_computer_history.
        # No granular per-session device tracking exists yet (watch_porn's
        # compatible_devices are computer/tv/phone, not distinguished at
        # completion time), so this logs whenever the character has
        # computer access at all -- real, if slightly opportunistic.
        if activity_type == "watch_porn":
            try:
                from systems.personal_items import get_computer
                computer = get_computer(c, world)
                if computer:
                    history = computer.setdefault("states", {}).setdefault("history", [])
                    history.append({
                        "tick":   world.get("tick", 0),
                        "viewer": c["id"],
                        "label":  "adult content",
                    })
                    del history[:-20]
            except Exception:
                pass

    # =====================================
    # SPORTS BROADCAST — a watch_tv session carrying a watching_game tag
    # (see systems/sports.py::kickoff_scheduled_games) resolves its
    # outcome/mood/reaction the same way an off-grid game attendee does.
    # =====================================
    if activity_type == "watch_tv" and act.get("watching_game"):
        try:
            from systems.sports import resolve_watch_party
            resolve_watch_party(c, world, act["watching_game"])
        except Exception:
            pass

    # =====================================
    # EAT (LLM-driven "eat" action, action_router.py::_route_eat) — the one
    # real item-targeted consumption path an LLM can pick directly
    # (target: any item; covers food, drinks, and drug items alike). The
    # "eat_meal"/"eat_snack"/"drink" branches above are the separate body-
    # need-strategy dispatch (start_activity/ACTIVITIES), whose target_id
    # is always a PROP (fridge/counter/sink), never a consumable item --
    # on_consume_complete already routes alcohol_units/drug_id/
    # addiction_type generically, so this one branch covers every item
    # category.
    # =====================================
    elif activity_type == "eat":
        target_id = act.get("target_id")
        item = _take_item_anywhere(c, world, target_id) if target_id else None
        if item:
            from systems.body import on_consume_complete
            on_consume_complete(c, world, item)

    elif activity_type == "convenience_store_checkout":
        from systems.convenience_store import resolve_checkout
        resolve_checkout(c, world, act)

    elif activity_type == "use_atm":
        from systems.convenience_store import resolve_atm_use
        resolve_atm_use(c, world, act)

    elif activity_type == "get_dressed":
        from systems.dressing import resolve_get_dressed
        resolve_get_dressed(c, world, act)

    # =====================================
    # RECORD HABIT
    # Every completed activity reinforces a time-of-day habit so future
    # intention sorting will slightly prefer it at the same hour.
    # =====================================
    from systems.habits import record_habit
    record_habit(c, activity_type, world)

    from core.event_bus import emit
    emit("activity_completed", {"character_id": c["id"], "activity_type": activity_type})


# =========================================================
# FINISH ACTIVITY
# =========================================================

def finish_activity(c, world):
    """Clear a completed activity so the character is free to decide again.

    complete_activity() already ran the completion side-effects (habit
    recording, body-need resolution, queue advancement) one phase earlier
    (from the "using" -> "finishing" transition); this just releases the
    activity slot once the finishing animation's single tick has played.
    """
    activity_type = (c.get("activity") or {}).get("type")

    # Reading a physical newspaper naturally ending (as opposed to being
    # interrupted by a debate -- see systems/reading_process.py's own
    # put-away call on that path) still needs the paper put down.
    process = c.get("active_process")
    if process and process.get("type") == "reading_news":
        from systems.reading_process import put_away_reading_item
        put_away_reading_item(c, world)
        c["active_process"] = None

    c["activity"] = None
    c["current_intention"] = None
    c["animation_state"] = "idle"

    # Wake the character now that it's actually free to decide again — see
    # brain/cognition_scheduler.py. activity_phase_changed (fired one tick
    # earlier, at the using->finishing transition) already woke it for a
    # brief-mode think(), but that think() would have hit the still-truthy
    # c["activity"] gate in agent_loop.py and bounced straight to
    # execute_activity(); this is the actual free-to-act moment.
    from core.event_bus import emit
    from brain.cognition_scheduler import wake_character
    emit("activity_finished", {"character_id": c["id"], "activity_type": activity_type})
    wake_character(c, world, "activity_finished")
