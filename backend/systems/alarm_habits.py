"""
systems/alarm_habits.py

Whether a character proactively sets their own phone alarm the night
before a scheduled work block -- a real, trait-modulated background
roll (mirrors systems/retirement.py::maybe_retire()'s "safe to call
every time, cheap no-op most of the time" shape), not something
surfaced as a player-visible LLM decision every night. The player/LLM
still has the manual set_phone_alarm_clock action for direct control;
this is what makes an unmanaged character behave sensibly on their own.

Only rolls at all when it would actually matter: if tonight's already-
rolled sleep duration (systems/activities.py::compute_duration_ticks)
would already have the character up before tomorrow's work start, there
is no risk either way and nothing here does anything -- "how long the
computed sleep duration is" is the real gate, not a flat nightly coin
flip.
"""

import random

from systems.scheduling import WEEKDAYS

ALARM_BASE_REMEMBER_CHANCE = 0.85

# Signed modifiers -- documented as tuned approximations, easy to
# retune. forgetful/disorganized/unstructured/routineless make
# remembering a deliberate nightly habit less likely; early_bird (an
# already-morning-oriented person) more likely; night_owl slightly less
# (mornings aren't their natural mode); deep_sleeper only slightly less
# (they know they need it, same base memory -- their real risk is
# sleeping THROUGH it, handled separately in brain/agent_loop.py).
_TRAIT_REMEMBER_MODIFIERS = {
    "forgetful":     -0.35,
    "disorganized":  -0.20,
    "unstructured":  -0.25,
    "routineless":   -0.25,
    "night_owl":     -0.10,
    "early_bird":     0.15,
    "deep_sleeper":  -0.05,
}

DEFAULT_PREP_BUFFER_MINUTES = 45


def _tomorrow_weekday(world):
    today = (world.get("calendar", {}).get("weekday") or "").lower()
    if today not in WEEKDAYS:
        return None
    idx = WEEKDAYS.index(today)
    return WEEKDAYS[(idx + 1) % 7]


def _tomorrows_work_start_minute(c, world):
    tomorrow = _tomorrow_weekday(world)
    if not tomorrow:
        return None
    blocks = c.get("schedule", {}).get("week", {}).get(tomorrow, [])
    work = next((b for b in blocks if b.get("activity") == "work"), None)
    if not work:
        return None
    h, m = work["start"].split(":")
    return int(h) * 60 + int(m)


def _wake_target_minute(c, world, work_start_minute):
    """Prefer tomorrow's own pre-work hygiene block (scheduling.py's
    real, generated pre-work slot) as the natural "needs to be up by"
    moment -- falls back to a flat buffer before work start if no
    hygiene block exists for tomorrow (e.g. an older/unmigrated
    schedule, or a work day scheduling.py didn't attach one to)."""
    tomorrow = _tomorrow_weekday(world)
    blocks = c.get("schedule", {}).get("week", {}).get(tomorrow, [])
    hygiene = next((b for b in blocks if b.get("activity") == "hygiene"), None)
    if hygiene:
        h, m = hygiene["start"].split(":")
        return int(h) * 60 + int(m)
    return max(0, work_start_minute - DEFAULT_PREP_BUFFER_MINUTES)


def _projected_wake_minute(c, world):
    """Where tonight's just-started sleep activity's already-rolled
    duration would put the character's wake time-of-day, if it runs
    uninterrupted to natural completion."""
    act = c.get("activity") or {}
    duration_ticks = act.get("duration", 0)
    start_tick = act.get("phase_started_tick", world.get("tick", 0))
    end_tick = start_tick + duration_ticks
    elapsed_minutes = max(0, end_tick - world.get("tick", 0)) // 60
    now_minute = world.get("calendar", {}).get("minute_of_day", 0)
    return (now_minute + elapsed_minutes) % 1440


def _remember_chance(c):
    chance = ALARM_BASE_REMEMBER_CHANCE
    traits = set(c.get("traits", [])) | set(c.get("physical_traits", []))
    for trait, mod in _TRAIT_REMEMBER_MODIFIERS.items():
        if trait in traits:
            chance += mod
    return max(0.02, min(0.99, chance))


def maybe_set_alarm_for_tomorrow(c, world):
    """Call once, right as a character's real nightly sleep activity
    begins (see activities.py's "using"-phase transition for sleep).
    Cheap no-op for anyone unemployed, without a real work block
    tomorrow, or whose natural wake time is already early enough."""
    if not c.get("employed"):
        return

    work_start = _tomorrows_work_start_minute(c, world)
    if work_start is None:
        return

    wake_target = _wake_target_minute(c, world, work_start)
    projected_wake = _projected_wake_minute(c, world)

    if projected_wake <= wake_target:
        return  # wakes up naturally in time -- no risk either way

    existing = c.get("phone_alarm")
    if existing and existing.get("minute_of_day") == wake_target:
        return  # already correctly set, nothing to roll

    from systems.action_router import _require_phone, _set_alarm_for_minute
    if not _require_phone(c):
        return  # no working phone to set an alarm on at all

    if random.random() < _remember_chance(c):
        _set_alarm_for_minute(c, wake_target)
