"""
habits.py — time-of-day habit tracking

c["habits"] is a dict of  "activity_type@hour" → strength (float).
Strength grows by 1 each time the activity completes at that hour and
decays by 0.1% per tick, so habits fade naturally if broken.

Habit strength biases intention sorting: an activity done at 7am every
day gets a priority boost during the 7am hour, nudging the AI toward
its routine without forcing it.
"""


# =========================================================
# RECORD  (call on activity completion)
# =========================================================

def record_habit(c, activity_type, world):
    """Increment the habit counter for this activity at the current hour."""
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
    hour    = world.get("calendar", {}).get("hour", 0)
    habits  = c.get("habits", {})
    if not habits:
        return

    for intent in c.get("active_intentions", []):
        itype    = intent.get("type", "")
        strength = habits.get(f"{itype}@{hour}", 0)
        if strength > 0:
            boost = 1 + min(0.5, strength * 0.05)  # max +50%
            intent["priority"] = round(intent.get("priority", 50) * boost)


# =========================================================
# DECAY  (call every tick)
# =========================================================

def decay_habits(c):
    """Habits decay slowly — 0.1% per tick. Remove when negligible."""
    for k in list(c.get("habits", {})):
        c["habits"][k] *= 0.999
        if c["habits"][k] < 0.01:
            del c["habits"][k]


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
