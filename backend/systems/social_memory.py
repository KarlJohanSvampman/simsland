"""
systems/social_memory.py

Once per real calendar day, the FIRST time character c actually sees
another specific character, pull up what c remembers about them (the
same {other_id in memory["people"]} filter systems/reflection.py::
revisit_related_memories() already uses -- see brain/memory.py::
store_memory()'s people= field) and review whether either of them owes
the other something under an active social contract (systems/
social_contracts.py).

Hooked from brain/perception.py::perceive(), the exact same place
systems/behavior_patterns.py's per-tick observation logging already
lives -- same try/except-wrapped, best-effort call shape.

No real per-day "have I seen them yet" tracker existed anywhere before
this (confirmed via grep -- brain/relationships.py's own "last_seen" is
a raw wall-clock timestamp, not day-keyed) -- a new relationship field,
"_last_sighting_review_day", is added here rather than repurposing that
existing one, since other systems already read it for other purposes.
"""

import random

MEMORY_RECALL_LIMIT = 6
TICKS_PER_DAY = 24            # matches health.py/plants.py/refurnishing.py's convention
VIOLATION_RECENCY_DAYS = 30   # only worth bringing up while it's still fresh
RECALL_NARRATION_WINDOW_TICKS = 60   # how long a fresh sighting stays worth narrating into context

# Same shape as systems/chores.py's _wants_to_nag -- personality-leaning
# coin flip, not a hard rule.
_APOLOGY_LEANING_TRAITS = {"diplomatic", "forgiving", "calm", "patient"}
_STUBBORN_TRAITS = {"stubborn", "impatient"}


def _wants_to_apologize(c):
    tr = set(c.get("traits", [])) | set(c.get("personality_traits", []))
    if tr & _APOLOGY_LEANING_TRAITS:
        return random.random() < 0.7
    if tr & _STUBBORN_TRAITS:
        return random.random() < 0.2
    return random.random() < 0.45


def _fade_text(text, days_old):
    """The older a memory, the more of its detail is hidden on purpose
    -- deliberately lossy, not a bug. Thresholds are calendar days, not
    ticks."""
    if not text:
        return text
    if days_old < 7:
        return text
    if days_old < 30:
        head = text.split(".")[0].strip()
        return f"{head}..." if head and head != text.rstrip(".") else text
    if days_old < 90:
        return "something happened, though the details are fuzzy now"
    return "barely remembers anything specific"


def memories_about(c, other_id, world, limit=MEMORY_RECALL_LIMIT):
    """Newest first ("oldest last," per spec), each entry's text faded
    by age. Read-only -- doesn't mutate the character's real stored
    memories, just how much of them gets surfaced right now."""
    tick = world.get("tick", 0)
    mine = [m for m in c.get("memories", []) if other_id in (m.get("people") or [])]
    mine.sort(key=lambda m: m.get("tick", 0), reverse=True)

    out = []
    for m in mine[:limit]:
        days_old = max(0, (tick - m.get("tick", tick)) / TICKS_PER_DAY)
        out.append({"text": _fade_text(m.get("text", ""), days_old), "days_old": round(days_old, 1)})
    return out


def _maybe_apologize(c, other, violation):
    if not _wants_to_apologize(c):
        return
    from brain.intentions import add_intention
    add_intention(c, {
        "type":      "apologize",
        "category":  "social",
        "priority":  50,
        "target_id": other["id"],
        "reason":    f"you missed {violation.get('commitment', 'something you agreed to')} with {other.get('name', 'them')}",
    })


def _maybe_inquire(c, other, violation):
    from brain.intentions import add_intention
    add_intention(c, {
        "type":      "inquire_about_contract",
        "category":  "social",
        "priority":  35,
        "target_id": other["id"],
        "reason":    f"{other.get('name', 'they')} missed {violation.get('commitment', 'something they agreed to')} -- you might ask what happened",
    })


def _review_social_contracts(c, other, world):
    from systems.social_contracts import get_contracts_for_character
    other_id = other.get("id")
    tick = world.get("tick", 0)

    for contract in get_contracts_for_character(c["id"], world):
        if other_id not in contract.get("parties", []):
            continue
        for violation in contract.get("violations", []):
            if c["id"] in (violation.get("surfaced") or []):
                continue
            if (tick - violation.get("tick", tick)) / TICKS_PER_DAY > VIOLATION_RECENCY_DAYS:
                continue
            violator = violation.get("violator")
            if violator == c["id"]:
                _maybe_apologize(c, other, violation)
            elif violator == other_id:
                _maybe_inquire(c, other, violation)
            else:
                continue
            # Marked surfaced regardless of whether the personality roll
            # above actually fired an intention -- c noticed it either
            # way, and re-bringing it up every single day forever would
            # be noise, not drama.
            violation.setdefault("surfaced", []).append(c["id"])


def maybe_review_on_sighting(c, other, world):
    """other is the real character dict (world["characters"][id]) --
    same param shape as behavior_patterns.py::log_observation, called
    right alongside it."""
    other_id = other.get("id")
    if not other_id or other_id == c.get("id"):
        return

    from brain.relationships import ensure_relationship
    rel = ensure_relationship(c, other_id)
    cal = world.get("calendar", {})
    today = (cal.get("year"), cal.get("month"), cal.get("day"))
    if rel.get("_last_sighting_review_day") == today:
        return
    rel["_last_sighting_review_day"] = today

    recalled = memories_about(c, other_id, world)
    if recalled:
        c["_last_sighting_recall"] = {
            "other_id":   other_id,
            "other_name": other.get("name", "them"),
            "memories":   recalled,
            "tick":       world.get("tick", 0),
        }

    _review_social_contracts(c, other, world)
