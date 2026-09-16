"""
systems/memory_detail.py

Shared "how much detail actually sticks" logic for the memory-writing
call sites (dialogue_memory.py, social_memory.py) -- per the user's
explicit ask: real memory is imperfect. Which details survive (and how
many) is randomized, not fixed, weighted toward keeping MORE for a
genuinely salient moment (violence, threats, illegal activity, fights/
arguments, accidents, someone crying or angry) and toward keeping FEWER
for routine, forgettable ones.
"""

import random

# Reused directly rather than re-declared -- these are the exact sets
# debug_log.py already classifies as violent/illegal for the debug-bubble
# purple category; the same moments are exactly the ones that should
# stick harder in memory too.
from systems.debug_log import VIOLENT_OR_ILLEGAL_ACTIONS, VIOLENT_OR_ILLEGAL_ACTIVITIES

_STRONG_EMOTIONS = {"angry", "furious", "afraid", "terrified", "distressed", "devastated", "enraged"}
_STRONG_REACTIONS = {"cry", "sob", "distressed", "shout", "scream", "flinch"}


def compute_salience(action_type=None, activity_type=None, reaction_type=None,
                      conversation_type=None, emotion=None, other_emotion=None,
                      category=None):
    """True = a strong, sticky moment (keep most/all details). False =
    routine (keep only a random handful)."""
    if category == "violation":
        return True
    if conversation_type == "argument":
        return True
    if reaction_type in _STRONG_REACTIONS:
        return True
    if emotion in _STRONG_EMOTIONS or other_emotion in _STRONG_EMOTIONS:
        return True
    if action_type in VIOLENT_OR_ILLEGAL_ACTIONS or activity_type in VIOLENT_OR_ILLEGAL_ACTIVITIES:
        return True
    return False


def relationship_closeness(c, other_id):
    """0-1 -- per the user's explicit ask: someone you're close to gets
    remembered in more detail, the way real attention/memory actually
    works. Averages the three core, always-present relationship stats
    (brain/relationships.py::ensure_relationship) rather than "respect"
    (which can run high for a rival too, not just someone you're close
    to) or anything more situational."""
    if not other_id:
        return 0.0
    rel = (c.get("relationships") or {}).get(other_id, {})
    if not rel:
        return 0.0
    score = (rel.get("familiarity", 0) + rel.get("trust", 0) + rel.get("friendship", 0)) / 3.0
    return max(0.0, min(100.0, score)) / 100.0


def compute_drop_probability(high_salience, closeness=0.0):
    """0-100 (%) -- stamped onto the memory itself (store_memory()'s
    **extra passthrough) so systems/memory_consolidation.py's random
    forgetting pass can weight BY the individual memory, not just apply
    one flat rate to everything. A salient moment and/or someone you're
    close to should survive forgetting passes much more reliably."""
    base = 20 if high_salience else 60
    reduction = round(closeness * 30)
    return max(5, base - reduction)


def select_details(fields, high_salience, closeness=0.0):
    """fields: {name: value_or_None}. Returns a dict subset of whichever
    survive -- real, randomized forgetting, not a fixed formula. A
    salient moment usually keeps everything (occasionally drops one
    anyway -- even a vivid memory loses a detail sometimes); a routine
    one normally keeps only one or two of whatever was available, but a
    close relationship (see relationship_closeness above) raises how
    much of a routine moment actually sticks."""
    available = [(k, v) for k, v in fields.items() if v]
    if not available:
        return {}
    n = len(available)
    if high_salience:
        keep_n = n if random.random() < 0.7 else max(1, n - 1)
    else:
        boosted_max = min(n, min(2, n) + round(closeness * 2))
        keep_n = random.randint(1, max(1, boosted_max))
    random.shuffle(available)
    return dict(available[:keep_n])


def location_label(char, world):
    """A short, best-effort "where" -- off-grid reason, a resolvable
    household name, or nothing (callers already treat a falsy location
    as simply not remembered, matching the imperfect-memory framing)."""
    if char.get("off_grid"):
        return (char.get("off_grid_reason") or "out").replace("_", " ")
    building_id = char.get("building_id")
    if not building_id:
        return None
    for hh in world.get("households", {}).values():
        if hh.get("home_id") == building_id:
            name = hh.get("name")
            return f"at {name}" if name else "at home"
    return "out in town"
