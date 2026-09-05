"""
systems/confiding.py

Generalizes "commit dramatic events to memory" with a specific emotional
NEED attached to the memory, mirroring how systems/mental_health_effects.py
rolls a per-character-consistent depression sub-profile once and reuses it
(rather than re-rolling per event): a character's tendency to want
VALIDATION ("tell me I did the right thing, what would you have done in
my situation") versus COMFORT ("just let me be upset about it") when
something dramatic happens is a stable personality lean, not a coin flip
every time.

tag_dramatic_memory() is the generic entry point any system with real
drama (an argument, a fight, a confrontation) should call instead of a
bare brain.memory.store_memory() -- systems/absence_suspicion.py and the
conflict_resolved handler (core/event_handlers.py) both use it.

Resolution (actually confiding in someone) is deliberately simple: once
daily (the same cadence as most of this session's other social-drama
systems), a character with an unconfided drama memory and a real trusted
contact available gets it resolved -- abstracted as "reached out to them,
in person or by phone," not gated on literal physical co-presence, since
modeling that at this granularity would need perception-tick plumbing
this round doesn't otherwise touch. This is the "jumps on the first
opportunity" behavior at a daily grain rather than a per-tick one.
"""

import random

from brain.memory import store_memory
from systems.persistent_desires import add_desire
from llm.llm_gate import run_llm_call

CONFIDE_VALIDATION_TRAITS = {"insecure", "anxious", "needs_approval", "people_pleaser", "self_doubting"}
CONFIDE_COMFORT_TRAITS = {"dramatic", "emotional", "sensitive", "easily_embarrassed", "sentimental"}

STRESS_RELIEF_VALIDATED = 12.0
STRESS_RELIEF_UNVALIDATED = 4.0
STRESS_RELIEF_COMFORTED = 10.0

_TRUSTED_DESIGNATIONS = {"close_friend", "best_friend"}
_TRUSTED_LABELS = {"parent", "sibling", "spouse", "partner"}


def _confide_style(c):
    """"validation" or "seek_comfort" -- rolled once, cached, matches
    mental_health_effects.py::_depression_profile()'s exact pattern."""
    style = c.get("_confide_style")
    if style is None:
        traits = set(c.get("traits", []) + c.get("personality_traits", []))
        if traits & CONFIDE_VALIDATION_TRAITS and not (traits & CONFIDE_COMFORT_TRAITS):
            style = "seek_validation"
        elif traits & CONFIDE_COMFORT_TRAITS and not (traits & CONFIDE_VALIDATION_TRAITS):
            style = "seek_comfort"
        else:
            style = random.choice(["seek_validation", "seek_comfort"])
        c["_confide_style"] = style
    return style


def tag_dramatic_memory(c, world, text, importance=0.6, people=None, extra_tags=None):
    """Stores a memory tagged "drama" + the character's own confide-style
    tag ("seek_validation"/"seek_comfort"), and raises a real, decaying
    desire to actually go confide in someone about it."""
    style = _confide_style(c)
    tags = ["drama", style] + list(extra_tags or [])
    mem = store_memory(
        c, text, importance=importance, tags=tags, kind="memory",
        tick=world.get("tick", 0), people=people or [],
    )
    mem["confided"] = False
    add_desire(c, "confide_in_someone", target=mem.get("id"), importance=0.5 + importance * 0.3)
    return mem


def _find_confidant(c, world):
    """Highest-trust trusted contact (close/best friend designation, or a
    family/spousal relationship label) who's still alive."""
    chars = world.get("characters", {})
    best = None
    best_trust = -999
    for other_id, rel in c.get("relationships", {}).items():
        qualifies = (
            rel.get("designation") in _TRUSTED_DESIGNATIONS
            or any(l in rel.get("labels", []) for l in _TRUSTED_LABELS)
        )
        if not qualifies:
            continue
        other = chars.get(other_id)
        if not other or not other.get("alive", True):
            continue
        trust = rel.get("trust", 0)
        if trust > best_trust:
            best_trust = trust
            best = other
    return best


def resolve_confide_opportunities(c, world):
    """Daily entry point. Finds this character's unconfided drama
    memories, and if a trusted contact exists, resolves the confiding --
    LLM-judged validation-or-not for seek_validation, straightforward
    stress relief + closeness for seek_comfort."""
    desires = c.get("persistent_desires", [])
    pending = [
        d for d in desires
        if d.get("type") == "confide_in_someone" and d.get("active") and not d.get("resolved")
    ]
    if not pending:
        return

    confidant = _find_confidant(c, world)
    if not confidant:
        return

    memories = {m.get("id"): m for m in c.get("memories", [])}

    for desire in pending:
        mem = memories.get(desire.get("target"))
        if not mem or mem.get("confided"):
            desire["resolved"] = True
            desire["active"] = False
            continue
        _do_confide(c, confidant, mem, world)
        mem["confided"] = True
        mem.setdefault("told_to", []).append(confidant["id"])
        desire["resolved"] = True
        desire["active"] = False


def _do_confide(c, confidant, mem, world):
    style = "seek_validation" if "seek_validation" in mem.get("tags", []) else "seek_comfort"
    rel = c.setdefault("relationships", {}).setdefault(confidant["id"], {})

    if style == "seek_validation":
        from llm.validation_scenario import generate_validation_response
        session = c.setdefault("llm_session", {"history": []})
        try:
            result = run_llm_call(
                generate_validation_response(confidant, c, mem.get("text", ""), world, session)
            )
        except Exception:
            result = None
        approves = bool(result.get("approves")) if result else True

        if approves:
            c["stress"] = max(0.0, c.get("stress", 0.0) - STRESS_RELIEF_VALIDATED)
            rel["trust"] = min(100, rel.get("trust", 0) + 4)
            rel["comfort"] = min(100, rel.get("comfort", 0) + 3)
        else:
            c["stress"] = max(0.0, c.get("stress", 0.0) - STRESS_RELIEF_UNVALIDATED)
            rel["comfort"] = min(100, rel.get("comfort", 0) + 1)
    else:
        c["stress"] = max(0.0, c.get("stress", 0.0) - STRESS_RELIEF_COMFORTED)
        rel["comfort"] = min(100, rel.get("comfort", 0) + 6)
        rel["trust"] = min(100, rel.get("trust", 0) + 2)

    conf_rel = confidant.setdefault("relationships", {}).setdefault(c["id"], {})
    conf_rel["trust"] = min(100, conf_rel.get("trust", 0) + 2)
    conf_rel["familiarity"] = min(100, conf_rel.get("familiarity", 0) + 1)
