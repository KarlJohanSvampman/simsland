import random, uuid

from llm.llm_gate import run_llm_call
from llm.offgrid_narration import generate_offgrid_narration


# =========================================================
# NORMALCY ROLL
# =========================================================
# Shared mechanism, caller-owned weights -- each off-grid category tunes
# its own odds (e.g. work vs. jail should feel differently eventful) by
# passing its own weights dict; the roll itself is one implementation.

def roll_normalcy(weights):
    """weights: {"normal": 0.85, "notable": 0.13, "rare": 0.02}-shaped dict
    (need not sum to 1.0 -- random.choices normalizes). Returns one key."""
    tiers = list(weights.keys())
    odds = list(weights.values())
    return random.choices(tiers, weights=odds, k=1)[0]


# =========================================================
# PER-CATEGORY MEMORY
# =========================================================
# Dedicated per-category continuity, separate from off_grid_story_arc
# (which stays as the general flat log for whatever else reads it).
# Lazy setdefault at point of use, same precedent as off_grid_story_arc
# itself (offgrid.py, not centrally registered in schema_defaults.py).

_CATEGORY_MEMORY_CAP = 6


def _record_category_memory(c, category, entry):
    """entry: {"tick": int, "normalcy": str, "summary": str}"""
    bucket = c.setdefault("offgrid_category_memory", {}).setdefault(category, [])
    bucket.append(entry)
    c["offgrid_category_memory"][category] = bucket[-_CATEGORY_MEMORY_CAP:]


# =========================================================
# LIE AWARENESS
# =========================================================

def _find_trip_cover_lie(c, current_tick):
    """
    Most recent active_lies entry seeded by THIS trip's _private_story call,
    or None. Filters on source == "offgrid_private" (excuses.py's own lie
    producer never sets `source`, so this naturally excludes unrelated
    lies) and tick >= current_tick -- the lie is seeded in the same
    process_return() call, at the same world["tick"], immediately before
    this lookup runs.
    """
    candidates = [
        lie for lie in c.get("active_lies", [])
        if lie.get("source") == "offgrid_private" and lie.get("tick", -1) >= current_tick
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda l: l["tick"])[-1]["lie_text"]


# =========================================================
# ENTRY POINT
# =========================================================

def request_offgrid_summary(c, world, category, details, normalcy, enforced_cover_story=None):
    """
    Returns a _story()-shaped dict ({id, summary, emotion, impact, tags})
    on success, or None if the LLM call failed -- caller falls back to the
    existing procedural _story() generator.
    """
    history = c.get("offgrid_category_memory", {}).get(category, [])[-3:]

    narration = run_llm_call(
        generate_offgrid_narration(
            c, world, category, details, normalcy, history,
            enforced_cover_story=enforced_cover_story,
        )
    )
    if not narration:
        return None

    _record_category_memory(
        c, category,
        {"tick": world["tick"], "normalcy": normalcy, "summary": narration},
    )

    return {
        "id": f"story_{uuid.uuid4().hex[:6]}",
        "summary": narration,
        "emotion": "calm" if normalcy == "normal" else ("curious" if normalcy == "notable" else "surprised"),
        "impact": {"stress": 0, "temp": 0} if normalcy == "normal" else {"stress": 2, "temp": 0},
        "tags": [category, f"normalcy_{normalcy}"],
    }
