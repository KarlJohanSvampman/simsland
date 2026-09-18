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

# Relocated from the retired brain/beliefs.py -- the same political-topic
# grouping elections/factions (systems/politics.py) already read, now
# averaging c["opinions"][topic]["stance"] instead of the old module's
# c["beliefs"][topic]["value"]. See compute_political_lean() below.
IDEOLOGY_AXES = {
    "economic":         ["taxes", "economy", "cost_of_living", "welfare"],
    "security":         ["crime", "police", "safety"],
    "social":           ["immigration", "homelessness"],
    "institutional":    ["justice", "government", "media"],
    "personal_conduct": ["honor", "loyalty", "ambition", "integrity", "self_reliance"],
}


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
    mirrors the retired brain/beliefs.py::belief_alignment()'s shape.
    0.5 (neutral) if either character has no opinion formed yet."""
    oa = get_current_opinion(a, topic)
    ob = get_current_opinion(b, topic)
    if oa is None or ob is None:
        return 0.5
    return max(0.0, 1 - abs(oa["stance"] - ob["stance"]) / 2)


# =========================================================
# POLITICAL LEAN -- replaces the retired brain/beliefs.py module.
# Same IDEOLOGY_AXES grouping, same consumers (systems/politics.py's
# elections/factions, brain/relationships.py), now sourced from
# c["opinions"] instead of a separate c["beliefs"] dict -- opinions
# are the one dynamic layer now (seeded from mentality at generation,
# nudged by real events afterward), matching the unified belief ->
# principle -> mentality -> opinion pipeline.
# =========================================================

def compute_political_lean(c):
    """Averages this character's current opinion stance across each
    IDEOLOGY_AXES group's topics. Stored as c["political_lean"]
    (renamed from the old module's c["political_alignment"] to avoid
    confusion with the retired module -- same shape, same consumers)."""
    axes = {}
    for axis, topics in IDEOLOGY_AXES.items():
        vals = []
        for topic in topics:
            op = get_current_opinion(c, topic)
            if op is not None:
                vals.append(op["stance"])
        axes[axis] = sum(vals) / len(vals) if vals else 0.0
    c["political_lean"] = axes
    return axes


def political_similarity(a, b):
    """0..1 whole-of-politics compatibility, mirrors the retired
    brain/beliefs.py::belief_alignment()'s multi-topic-averaging shape,
    now sourced from c["political_lean"] (opinions-derived)."""
    aa = a.get("political_lean") or compute_political_lean(a)
    bb = b.get("political_lean") or compute_political_lean(b)
    keys = set(aa) | set(bb)
    if not keys:
        return 0.5
    return max(0.0, 1 - (sum(abs(aa.get(k, 0) - bb.get(k, 0)) for k in keys) / len(keys) / 2))


def polarize_opinions(c):
    """Replaces the retired brain/beliefs.py::polarization_drift() --
    same math, over the current stance of every opinion topic instead
    of the old c["beliefs"] dict. Mutates the most recent snapshot in
    place (passive background drift, not a new opinion-forming event,
    so this deliberately doesn't grow the capped history every tick)."""
    for history in c.get("opinions", {}).values():
        if not history:
            continue
        entry = history[-1]
        v = entry.get("stance", 0)
        conf = entry.get("confidence", 0)
        if abs(v) > 0.2:
            entry["stance"] = max(-1.0, min(1.0, v + (0.005 * conf if v > 0 else -0.005 * conf)))


def nudge_opinion(c, topic, sentiment, intensity, tick, reasoning=""):
    """Thin wrapper replacing the retired brain/beliefs.py::
    update_belief() at its 4 real call sites (systems/politics.py's
    election-winner reinforcement, systems/influence.py's news/peer
    nudges) -- replicates its exact sentiment-to-delta math so those
    call sites needed no behavioral change, just an import swap. Shifts
    an existing opinion (the normal case, since every political topic
    gets seeded at generation by the mentality-compilation sweep) or
    creates a fresh one as a defensive fallback for an edge-case
    character whose compilation hasn't run yet."""
    delta = 0.2 * float(intensity)
    if sentiment in ("negative", "anti"):
        delta = -abs(delta)
    elif sentiment in ("positive", "pro"):
        delta = abs(delta)
    else:
        delta = delta * 0.2

    shifted = shift_opinion(c, topic, delta, tick, reasoning=reasoning)
    if shifted is None:
        shifted = update_opinion(c, topic, delta, 0.1, reasoning, [], tick)
    return shifted
