"""
brain/situations/history.py

Per-character situation-selection history -- separate from Simsland's real
memory system (brain/memory.py's long_term_memory) on purpose: this is
middleware/cognition bookkeeping ("what have I recently asked this
character to focus on"), not something the character themselves
remembers or that should ever surface in their own narrated recollection.

c["_situation_history"] = [
    {"situation_id": str, "tick": int},
    ...
]

situation_id identifies a specific candidate, not just its category/type --
"compliment_looks:char_acbfda9c" and "compliment_looks:char_3c67d4cc" are
different situations for novelty/cooldown purposes (recharging interest in
complimenting one person shouldn't cooldown-block a completely different
one), built by selector.py's situation_id().
"""

HISTORY_CAP = 40

# 1 tick == 1 real sim-second (see systems/lt_needs.py's own doc comment).
TICKS_PER_MINUTE = 60
TICKS_PER_HOUR   = TICKS_PER_MINUTE * 60

# Default cooldown when a situation's own type isn't listed here --
# matches the proposal's "need.hunger.noticeable.cooldown = 30 minutes"
# example order of magnitude.
DEFAULT_COOLDOWN_TICKS = 30 * TICKS_PER_MINUTE

# Per intention-TYPE cooldown overrides. Deliberately short for things
# that should be revisitable quickly once conditions change (a body need
# ticking back up) and longer for social/identity ones that would feel
# pushy or repetitive if re-selected every few minutes.
COOLDOWN_TICKS_BY_TYPE = {
    "use_toilet":            5  * TICKS_PER_MINUTE,
    "sleep":                 60 * TICKS_PER_MINUTE,
    "eat_food":               10 * TICKS_PER_MINUTE,
    "drink":                  10 * TICKS_PER_MINUTE,
    "seek_shelter":            5 * TICKS_PER_MINUTE,
    "seek_warmer_clothes":    10 * TICKS_PER_MINUTE,
    "socialize":              20 * TICKS_PER_MINUTE,
    "seek_solitude":          30 * TICKS_PER_MINUTE,
    "compliment_looks":       45 * TICKS_PER_MINUTE,
    "compliment_character":   45 * TICKS_PER_MINUTE,
    "flirt":                  30 * TICKS_PER_MINUTE,
    "gossip":                 45 * TICKS_PER_MINUTE,
    "apologize":              60 * TICKS_PER_MINUTE,
}


def cooldown_ticks_for(intention_type):
    return COOLDOWN_TICKS_BY_TYPE.get(intention_type, DEFAULT_COOLDOWN_TICKS)


def record_selection(c, situation_id, tick):
    hist = c.setdefault("_situation_history", [])
    hist.append({"situation_id": situation_id, "tick": tick})
    if len(hist) > HISTORY_CAP:
        del hist[:len(hist) - HISTORY_CAP]


def last_selected_tick(c, situation_id):
    """Most recent tick this exact situation_id was selected, or None if
    it never has been (within the retained history window)."""
    hist = c.get("_situation_history") or []
    last = None
    for entry in hist:
        if entry.get("situation_id") == situation_id:
            if last is None or entry["tick"] > last:
                last = entry["tick"]
    return last


# Anchor points for the novelty curve (per the proposal's own example):
#   just selected (~0 ticks ago)   -> 0
#   2 min ago                       -> 0
#   20 min ago                      -> 30
#   2 hours ago                     -> 80
#   never selected                  -> 100
# Piecewise-linear between anchors, clamped [0, 100].
_NOVELTY_ANCHORS_TICKS = [
    (0,                    0),
    (2  * TICKS_PER_MINUTE, 0),
    (20 * TICKS_PER_MINUTE, 30),
    (2  * TICKS_PER_HOUR,   80),
    (8  * TICKS_PER_HOUR,   100),
]


def novelty(c, situation_id, tick):
    last = last_selected_tick(c, situation_id)
    if last is None:
        return 100.0

    elapsed = max(0, tick - last)
    anchors = _NOVELTY_ANCHORS_TICKS
    if elapsed <= anchors[0][0]:
        return float(anchors[0][1])
    for (t0, v0), (t1, v1) in zip(anchors, anchors[1:]):
        if elapsed <= t1:
            frac = (elapsed - t0) / (t1 - t0) if t1 > t0 else 1.0
            return v0 + (v1 - v0) * frac
    return float(anchors[-1][1])


# Cooldown penalty curve (proposal step 15): a soft, decaying penalty
# rather than a hard exclusion, so a recently-selected situation can still
# win if it's become dramatically more urgent since.
_COOLDOWN_PENALTY_CURVE = [
    (0.25, 50),
    (0.50, 30),
    (0.75, 15),
    (1.00, 5),
]


def cooldown_penalty(c, situation_id, situation_type, tick):
    last = last_selected_tick(c, situation_id)
    if last is None:
        return 0.0

    window = cooldown_ticks_for(situation_type)
    if window <= 0:
        return 0.0

    elapsed_fraction = max(0.0, (tick - last)) / window
    if elapsed_fraction >= 1.0:
        return 0.0

    for threshold, penalty in _COOLDOWN_PENALTY_CURVE:
        if elapsed_fraction <= threshold:
            return float(penalty)
    return 0.0
