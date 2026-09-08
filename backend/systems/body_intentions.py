"""
body_intentions.py — converts physical body state into high-priority intentions.

These override scheduled activities when the body demands attention.
"""

from brain.intentions import add_intention
from systems.body import get_odor_label, get_breath_label


def generate_body_intentions(c, world=None):
    b = c.get("body", {})
    tr = c.get("traits", [])

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
