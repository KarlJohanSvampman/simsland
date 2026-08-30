"""
systems/behavior_patterns.py

Characters log every notable observation of another character (what
they were doing, when) as they perceive them (see brain/perception.py's
log_observation() call). At the end of each real calendar day, these
raw observations are aggregated into recurring patterns per person --
same activity, similar hour, re-seen -- incrementing an existing
pattern's count rather than duplicating one, then cleared to start
fresh the next day. A newly-created pattern gets an LLM theory exactly
once (llm/behavior_theory.py); a pessimistic theory feeds systems/
worries.py's real suspicion tracking.

c["behavior_patterns"][other_id] = [{
    "id", "activity", "hour_range": [lo, hi], "count",
    "first_noted_tick", "last_noted_tick", "answer", "theory",
}]
"""

import uuid

OBSERVATION_CAP_PER_DAY = 200
HOUR_MATCH_WINDOW       = 2   # a re-sighting within +/-2 hours counts as "the same pattern"


def _day_key(calendar):
    if not calendar:
        return None
    return f"{calendar.get('year', 0):04d}-{calendar.get('month', 0):02d}-{calendar.get('day', 0):02d}"


def log_observation(c, target, world):
    """Call from brain/perception.py wherever a character is actually
    seen -- rides on that existing scan rather than a separate one."""
    if target.get("id") == c.get("id"):
        return
    activity = (target.get("activity") or {}).get("interaction") or (target.get("activity") or {}).get("type")
    if not activity:
        return
    calendar = world.get("calendar", {})
    obs = c.setdefault("_daily_observations", [])
    obs.append({
        "other_id": target["id"],
        "activity": activity,
        "hour":     calendar.get("hour", 0),
        "tick":     world.get("tick", 0),
    })
    del obs[:-OBSERVATION_CAP_PER_DAY]


def _find_matching_pattern(patterns, activity, hour):
    for p in patterns:
        if p["activity"] != activity:
            continue
        lo, hi = p["hour_range"]
        if lo - HOUR_MATCH_WINDOW <= hour <= hi + HOUR_MATCH_WINDOW:
            return p
    return None


def aggregate_daily_observations(c, world):
    """Day-key-gated (mirrors libido.py/expectations.py's own pattern,
    this session's established "once per real day" idiom) -- call on
    any reasonably frequent cadence; only actually aggregates once per
    real calendar day regardless of how often it's called."""
    calendar = world.get("calendar", {})
    day_key = _day_key(calendar)
    if day_key is None:
        return
    if c.get("_last_pattern_day") == day_key:
        return
    c["_last_pattern_day"] = day_key

    obs = c.get("_daily_observations", [])
    if not obs:
        return

    by_person = {}
    for o in obs:
        by_person.setdefault(o["other_id"], []).append(o)

    patterns_by_person = c.setdefault("behavior_patterns", {})
    tick = world.get("tick", 0)

    for other_id, entries in by_person.items():
        by_activity = {}
        for e in entries:
            by_activity.setdefault(e["activity"], []).append(e["hour"])

        patterns = patterns_by_person.setdefault(other_id, [])
        for activity, hours in by_activity.items():
            hour = hours[0]  # today's representative sighting time
            existing = _find_matching_pattern(patterns, activity, hour)
            if existing:
                existing["count"] += 1
                existing["last_noted_tick"] = tick
                lo, hi = existing["hour_range"]
                existing["hour_range"] = [min(lo, hour), max(hi, hour)]
            else:
                pattern = {
                    "id":               f"pat_{uuid.uuid4().hex[:8]}",
                    "activity":         activity,
                    "hour_range":       [hour, hour],
                    "count":            1,
                    "first_noted_tick": tick,
                    "last_noted_tick":  tick,
                    "answer":           None,
                    "theory":           None,
                }
                patterns.append(pattern)
                _generate_theory_for(c, other_id, pattern, world)

    c["_daily_observations"] = []


def _generate_theory_for(c, other_id, pattern, world):
    other = world.get("characters", {}).get(other_id)
    if not other:
        return
    theory = None
    try:
        from llm.behavior_theory import generate_theory
        theory = generate_theory(c, other, pattern, world)
    except Exception:
        theory = None
    if not theory:
        theory = {"text": f"Probably just {pattern['activity']}.", "valence": "optimistic"}
    pattern["theory"] = theory

    if theory.get("valence") == "pessimistic":
        try:
            from systems.worries import bump_suspicion
            bump_suspicion(c, other_id, 0.15, "behavior_pattern", pattern["activity"], world)
        except Exception:
            pass


def find_pattern(c, other_id, activity=None):
    patterns = c.get("behavior_patterns", {}).get(other_id, [])
    if activity:
        return next((p for p in patterns if p["activity"] == activity), None)
    return patterns


def highest_unanswered_pattern(c, other_id):
    """The pattern c most wants an answer for right now -- Confirmed
    Decision: desire to ask scales with recurrence count."""
    patterns = [p for p in c.get("behavior_patterns", {}).get(other_id, []) if not p.get("answer")]
    if not patterns:
        return None
    return max(patterns, key=lambda p: p["count"])


def answer_pattern(asker, subject_id, activity, answer_text):
    """The person being asked fills in the answer -- writes into the
    ASKER's own tracked pattern (found by subject+activity). Lying into
    this field is a real, valid choice this system doesn't prevent."""
    pattern = find_pattern(asker, subject_id, activity)
    if not pattern:
        return False
    pattern["answer"] = answer_text
    return True
