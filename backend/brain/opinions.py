"""
brain/opinions.py

Per-character opinions on free-form topics/questions, informed by
c["values"] (systems/schema_defaults.py's 12-category VALUE_CATEGORIES).
Deliberately separate from brain/beliefs.py -- that module is fixed to
IDEOLOGY_AXES (political/policy topics) and consumed by systems/politics.py's
election/faction code; mixing personal-values topics into it would
conflict with that. This module mirrors its math shape instead (certainty-
gated resistance to change, similarity scoring) for the new topic space.

c["opinions"][topic] is a capped history of past-formed-opinion snapshots
(mirrors systems/offgrid_narrative.py's offgrid_category_memory two-level
dict-of-capped-lists pattern) -- "all opinions formed in the past," not
just current state:
    {"tick": int, "stance": -1.0..1.0, "confidence": 0.0..1.0,
     "reasoning": str, "relevant_values": [category, ...]}
"""

_OPINION_HISTORY_CAP = 6


def update_opinion(c, topic, stance, confidence, reasoning, relevant_values, tick):
    """Append a new opinion snapshot for `topic`, capped to the last
    _OPINION_HISTORY_CAP entries. Returns the new entry."""
    entry = {
        "tick":            tick,
        "stance":          max(-1.0, min(1.0, float(stance))),
        "confidence":      max(0.0, min(1.0, float(confidence))),
        "reasoning":       reasoning or "",
        "relevant_values": list(relevant_values or []),
    }
    history = c.setdefault("opinions", {}).setdefault(topic, [])
    history.append(entry)
    del history[:-_OPINION_HISTORY_CAP]
    return entry


def get_current_opinion(c, topic):
    """Most recent opinion snapshot on `topic`, or None if never formed."""
    history = c.get("opinions", {}).get(topic)
    return history[-1] if history else None


def shift_opinion(c, topic, delta, tick, reasoning="", relevant_values=None):
    """
    Nudge an EXISTING opinion by `delta` (signed, typically a persuasion
    result from systems/action_router.py's make_argument resolution),
    applying beliefs.py::update_belief()'s exact resistance/confidence
    math: stronger existing confidence resists the stance shift more, and
    confidence itself moves up when the shift agrees with the current
    stance's sign, down when it contradicts it.

    Returns the new snapshot, or None if the character has no existing
    opinion on this topic to shift (callers should trigger opinion
    formation instead in that case -- see systems/reflection.py's
    "form_opinion" kind).
    """
    current = get_current_opinion(c, topic)
    if current is None:
        return None

    confidence = current.get("confidence", 0.1)
    resistance = 1 - confidence
    old_stance = current["stance"]
    new_stance = max(-1.0, min(1.0, old_stance + delta * resistance))

    if (old_stance >= 0 and delta >= 0) or (old_stance <= 0 and delta <= 0):
        new_confidence = min(1.0, confidence + 0.04 * abs(delta))
    else:
        new_confidence = max(0.0, confidence - 0.03 * abs(delta))

    return update_opinion(
        c, topic, new_stance, new_confidence,
        reasoning or current.get("reasoning", ""),
        relevant_values or current.get("relevant_values", []),
        tick,
    )


def opinion_alignment(a, b, topic):
    """0..1 similarity between two characters' current stance on `topic`,
    mirrors beliefs.py::belief_alignment()'s shape. 0.5 (neutral) if
    either character has no opinion formed yet."""
    oa = get_current_opinion(a, topic)
    ob = get_current_opinion(b, topic)
    if oa is None or ob is None:
        return 0.5
    return max(0.0, 1 - abs(oa["stance"] - ob["stance"]) / 2)
