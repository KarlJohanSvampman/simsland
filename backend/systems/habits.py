"""
habits.py — time-of-day habit tracking

c["habits"] is a dict of  "activity_type@hour" → strength (float).
Strength grows by 1 each time the activity completes at that hour and
fades with a half-life of HABIT_HALF_LIFE_DAYS sim days (tunable in the
environment, default 3), so habits fade naturally if broken. The fade is
lazy (refresh_habits): applied whenever habits are read or written, and the
same however often that happens. It used to be 0.1% per tick, which made
even a strong habit vanish in ~2 hours -- before the hour it belongs to
came round again the next day.

Habit strength biases intention sorting: an activity done at 7am every
day gets a priority boost during the 7am hour, nudging the AI toward
its routine without forcing it.
"""


# =========================================================
# RECORD  (call on activity completion)
# =========================================================

import os

HABIT_HALF_LIFE_SECONDS = float(os.getenv("HABIT_HALF_LIFE_DAYS", "3")) * 86400.0
HABIT_FORGET_BELOW = 0.01


def refresh_habits(c, world):
    """Bring c["habits"] up to now: strength x 0.5 ** (sim seconds since the last refresh / half-life); habits under
    HABIT_FORGET_BELOW are dropped. c["_habits_ts"] is when they were last brought up to date."""
    from core.clock import now_ts
    now = now_ts(world)
    last = c.get("_habits_ts")
    c["_habits_ts"] = now
    habits = c.get("habits")
    if last is None or not habits or now <= last:
        return
    f = 0.5 ** ((now - last) / HABIT_HALF_LIFE_SECONDS)
    for k in list(habits):
        habits[k] *= f
        if habits[k] < HABIT_FORGET_BELOW:
            del habits[k]


def record_habit(c, activity_type, world):
    """Increment the habit counter for this activity at the current hour."""
    refresh_habits(c, world)
    hour = world.get("calendar", {}).get("hour", 0)
    key  = f"{activity_type}@{hour}"
    habits = c.setdefault("habits", {})
    habits[key] = habits.get(key, 0) + 1


# =========================================================
# BIAS  (call before intention sort)
# =========================================================

def apply_habit_bias(c, scores, world):
    """
    Boost scores for activities the character habitually does at this hour.
    scores: dict of {activity_type: numeric_score}
    Returns the same dict with values multiplied by up to 1.5.
    """
    hour = world.get("calendar", {}).get("hour", 0)
    habits = c.get("habits", {})

    for goal in scores:
        strength = habits.get(f"{goal}@{hour}", 0)
        if strength > 0:
            scores[goal] *= (1 + min(0.5, strength * 0.05))

    return scores


def apply_habit_bias_to_intentions(c, world):
    """
    Apply time-of-day habit bias to c["active_intentions"] priorities in-place.
    Intentions whose type matches a habit at the current hour get a priority boost.
    """
    refresh_habits(c, world)
    hour    = world.get("calendar", {}).get("hour", 0)
    habits  = c.get("habits", {})
    if not habits:
        return

    for intent in c.get("active_intentions", []):
        itype    = intent.get("type", "")
        strength = habits.get(f"{itype}@{hour}", 0)
        if strength > 0:
            boost = 1 + min(0.5, strength * 0.05)  # max +50%
            # Confirmed live crash: this used to boost intent["priority"]
            # IN PLACE every single tick this function ran on the same
            # intention -- for one that persists across many ticks (e.g.
            # a real activity's own matching intention, not regenerated
            # fresh each cycle like most need-driven ones), the boost
            # compounded exponentially (priority *= ~1.05 forever) until
            # it overflowed to a ~300-digit number and then float
            # infinity, crashing every single agent tick for that
            # character from then on. Always compute from a stable base
            # (stamped once, never re-derived from an already-boosted
            # value) so repeated calls are idempotent.
            base = intent.setdefault("_base_priority", intent.get("priority", 50))
            intent["priority"] = round(base * boost)


# =========================================================
# DECAY  (lazy -- see refresh_habits)
# =========================================================

def decay_habits(c, world=None):
    """Kept for older callers: the lazy fade (refresh_habits) when a world is given, else nothing."""
    if world is not None:
        refresh_habits(c, world)


# =========================================================
# DOMINANT HABIT FOR AN HOUR  (for systems/worries.py's routine-
# deviation check -- "is what I'm seeing them do right now unusual
# for them at this time of day?")
# =========================================================

def get_dominant_habit_for_hour(c, hour, min_strength=5):
    """Returns (activity_type, strength) for c's strongest habit at
    this hour, or None if nothing there is established enough to
    count as "routine". min_strength=5 is calibrated against
    apply_habit_bias()'s own saturation point (strength~=10 already
    maxes its boost) -- a raw counter, not 0-1, so a single completion
    (strength=1) must NOT read as a routine."""
    suffix = f"@{hour}"
    habits = c.get("habits", {})
    candidates = [
        (key[: -len(suffix)], strength)
        for key, strength in habits.items()
        if key.endswith(suffix)
    ]
    if not candidates:
        return None
    dominant = max(candidates, key=lambda kv: kv[1])
    if dominant[1] < min_strength:
        return None
    return dominant
