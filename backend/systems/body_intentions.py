"""
body_intentions.py — converts physical body state into high-priority intentions.

These override scheduled activities when the body demands attention.
"""

from brain.intentions import add_intention as _add_intention_raw
from systems.body import get_odor_label, get_breath_label


# Every type this function can add. It's the sole, unconditional (every
# tick, every character -- see brain/agent_loop.py::update_internal_state)
# owner of all of them, but it only ever ADDS one when its threshold is
# crossed -- nothing ever removed one once the underlying stat dropped
# back down. Confirmed live bug: two characters sharing one bathroom got
# stuck in an endless swap because a satisfied "use_toilet" intention
# (bowels reset to ~1 by on_toilet_complete()) was never cleared from
# active_intentions -- the very next tick picked the same stale entry
# right back up (add_intention()'s same-type replace only refreshes an
# intention while it keeps getting re-added; it does nothing for one that
# simply stops being re-added). Wiping these types at the top of every
# call and letting the checks below re-add only what's still actually
# true keeps this list a live reflection of body state instead of a
# historical log of every threshold ever crossed.
_MANAGED_INTENTION_TYPES = {
    "use_toilet", "sleep", "take_nap", "take_shower",
    "brush_teeth", "drink", "eat_food", "seek_caffeine_or_rest",
    "seek_shelter", "seek_warmer_clothes",
}


def generate_body_intentions(c, world=None):
    b = c.get("body", {})
    tr = c.get("traits", [])

    # Confirmed live bug (player-visible: every body-need intention's
    # "Created At" always reads "0s ago", no matter how long the need has
    # actually been active): the wipe-then-readd pattern right below this
    # comment (needed for the toilet-swap fix documented above) deletes
    # the existing entry BEFORE add_intention() ever runs, so its own
    # "preserve the original created_at when one already exists" lookup
    # always finds nothing and always stamps a fresh "now" -- every
    # single tick, for every managed type. Snapshot each managed type's
    # real original created_at first, so it can be threaded back in
    # explicitly (add_intention() honors an explicit created_at and skips
    # its own now-useless lookup) when re-added below.
    _original_created_at = {
        i["type"]: i["created_at"]
        for i in c.get("active_intentions", [])
        if i.get("type") in _MANAGED_INTENTION_TYPES and "created_at" in i
    }

    # Local shadow of the real add_intention for the rest of this function
    # only -- every call site below stays unchanged, but now transparently
    # carries forward the real original created_at (when this type was
    # already active) instead of always minting a fresh "now".
    def add_intention(c, intention):
        preserved = _original_created_at.get(intention["type"])
        if preserved is not None and "created_at" not in intention:
            intention["created_at"] = preserved
        _add_intention_raw(c, intention)

    c["active_intentions"] = [
        i for i in c.get("active_intentions", [])
        if i.get("type") not in _MANAGED_INTENTION_TYPES
    ]

    # Live bug report: characters were sleeping full multi-hour sessions
    # in the middle of the day just as readily as at night -- this
    # function had no access to world/the calendar at all, so the
    # fatigue-driven "sleep" intention below couldn't have been time-aware
    # even in principle. systems/scheduling.py already models a real
    # 23:00-07:00 nighttime sleep block, but that's a separate, uncoordinated
    # system -- this mirrors its exact window as the boundary here too, so
    # "is it night" means the same thing in both places.
    hour = (world or {}).get("calendar", {}).get("hour")
    is_night = hour is None or hour >= 23 or hour < 7

    # ── BLADDER ──────────────────────────────────────────────────────────────
    bladder = b.get("bladder", 0)
    if bladder > 85:
        add_intention(c, {
            "type":       "use_toilet",
            "category":   "survival",
            "priority":   97,
            "interrupts": True,
            "reason":     "bladder_urgent"
        })
    elif bladder > 70:
        add_intention(c, {
            "type":     "use_toilet",
            "category": "survival",
            "priority": 80,
            "reason":   "bladder_full"
        })

    # ── BOWELS ───────────────────────────────────────────────────────────────
    if b.get("bowels", 0) > 80:
        add_intention(c, {
            "type":       "use_toilet",
            "category":   "survival",
            "priority":   95,
            "interrupts": True,
            "reason":     "bowels_urgent"
        })

    # ── SLEEP / FATIGUE ──────────────────────────────────────────────────────
    fatigue    = b.get("fatigue", 0)
    sleep_debt = b.get("sleep_debt", 0)

    # Daytime requires genuinely extreme exhaustion (95 vs. night's 90)
    # before forcing a real multi-hour sleep, and at a lower priority so
    # it competes more fairly with work/social intentions instead of
    # always winning outright -- still allowed to happen (collapsing from
    # real exhaustion during the day is realistic), just rarer.
    critical_threshold = 90 if is_night else 95
    if fatigue > critical_threshold:
        add_intention(c, {
            "type":       "sleep",
            "category":   "survival",
            "priority":   98 if is_night else 85,
            "interrupts": True,
            "reason":     "exhausted"
        })
    elif fatigue > 75:
        if is_night:
            # Lazy/depressed characters cave earlier
            priority = 70 if ("lazy" not in tr and "apathetic" not in tr) else 80
            add_intention(c, {
                "type":     "sleep",
                "category": "survival",
                "priority": priority,
                "reason":   "very_tired"
            })
        else:
            # Daytime: a real nap instead of a full sleep session at this
            # tier -- shorter, less disruptive, and this is exactly what
            # take_nap already exists for (see the sleep_debt block below,
            # merged into the same intention rather than adding a second
            # competing one).
            add_intention(c, {
                "type":     "take_nap",
                "category": "health",
                "priority": 65,
                "reason":   "very_tired"
            })

    # Sleep debt makes them want a nap even when not fully fatigued
    if sleep_debt > 50 and fatigue > 55:
        add_intention(c, {
            "type":     "take_nap",
            "category": "health",
            "priority": 55,
            "reason":   "sleep_debt"
        })

    # ── EXTENDED WAKEFULNESS ("whiny") ───────────────────────────────────────
    # A real, escalating nag distinct from the hard fatigue-based sleep/nap
    # triggers above -- starts well before those (fatigue now takes a real
    # 48h awake, unmedicated, to max out -- see systems/body.py's rescaled
    # AWAKE_FATIGUE_RATE_PER_TICK), never interrupts, and naturally goes
    # away once the character either gets real sleep or a real stimulant
    # (coffee/energy drink -- see body.py's _stimulant_until_tick window).
    hours_awake = b.get("hours_awake", 0)
    stimulant_active = world is not None and world.get("tick", 0) < b.get("_stimulant_until_tick", 0)
    if hours_awake >= 16 and not stimulant_active and fatigue <= critical_threshold:
        priority = min(65, 20 + (hours_awake - 16) * 3)
        add_intention(c, {
            "type":     "seek_caffeine_or_rest",
            "category": "health",
            "priority": priority,
            "reason":   f"You've been awake {int(hours_awake)}h -- it's starting to wear on you. Coffee or getting to bed soon would help."
        })

    # ── HYGIENE / SHOWER ─────────────────────────────────────────────────────
    hygiene = b.get("hygiene", 100)
    odor    = b.get("odor", 0)

    # Lazy/apathetic characters have higher threshold before showering
    shower_threshold = 30
    if "lazy" in tr or "apathetic" in tr:
        shower_threshold = 18
    if "vain" in tr or "disciplined" in tr:
        shower_threshold = 50

    if hygiene < shower_threshold:
        priority = 65
        if odor > 60:
            priority = 75   # strong smell = more urgent
        add_intention(c, {
            "type":     "take_shower",
            "category": "health",
            "priority": priority,
            "reason":   "hygiene_low"
        })

    # ── TEETH BRUSHING ───────────────────────────────────────────────────────
    mouth = b.get("mouth_hygiene", 100)
    if mouth < 40:
        add_intention(c, {
            "type":     "brush_teeth",
            "category": "health",
            "priority": 45,
            "reason":   "mouth_hygiene_low"
        })

    # ── DRINK ────────────────────────────────────────────────────────────────
    if b.get("hydration", 100) < 30:
        add_intention(c, {
            "type":       "drink",
            "category":   "survival",
            "priority":   85,
            "interrupts": True,
            "reason":     "dehydrated"
        })
    elif b.get("hydration", 100) < 55:
        add_intention(c, {
            "type":     "drink",
            "category": "survival",
            "priority": 60,
            "reason":   "thirsty"
        })

    # ── HUNGER ───────────────────────────────────────────────────────────────
    hunger = b.get("hunger", 0)
    if hunger > 80:
        add_intention(c, {
            "type":       "eat_food",
            "category":   "survival",
            "priority":   88,
            "interrupts": True,
            "reason":     "very_hungry"
        })
    elif hunger > 60:
        add_intention(c, {
            "type":     "eat_food",
            "category": "survival",
            "priority": 65,
            "reason":   "hungry"
        })

    # ── SELF-SMELL AWARENESS ─────────────────────────────────────────────────
    # Characters notice their own smell at very high odor levels
    if odor > 70 and hygiene < 40:
        add_intention(c, {
            "type":     "take_shower",
            "category": "social",
            "priority": 70,
            "reason":   "self_conscious_about_smell"
        })

    # ── WEATHER EXPOSURE (systems/weather.py) ────────────────────────────────
    # seek_shelter (get inside) is the same "go somewhere" want regardless of
    # cold or heat -- getting indoors fixes both. seek_warmer_clothes only
    # makes sense for cold (there's no equivalent "put on lighter clothes"
    # item stat yet, and taking clothes OFF in public has its own
    # nudity-perception consequences elsewhere, so heat doesn't get a
    # matching clothing want here).
    cold_exposure = b.get("cold_exposure", 0)
    heat_exposure = b.get("heat_exposure", 0)
    worst_exposure = max(cold_exposure, heat_exposure)
    if worst_exposure > 60:
        add_intention(c, {
            "type":       "seek_shelter",
            "category":   "survival",
            "priority":   int(60 + (worst_exposure - 60) * 0.8),
            "interrupts": worst_exposure > 85,
            "reason":     "too_cold" if cold_exposure >= heat_exposure else "too_hot"
        })
    elif cold_exposure > 30:
        add_intention(c, {
            "type":     "seek_warmer_clothes",
            "category": "survival",
            "priority": 40,
            "reason":   "getting_cold"
        })
