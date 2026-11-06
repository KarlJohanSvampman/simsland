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
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND

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
    d = _confide_desire(c, create=True, importance=0.5 + importance * 0.3)
    if mem.get("id") and mem["id"] not in d["about"]:
        d["about"].append(mem["id"])
        del d["about"][:-ABOUT_KEPT]
    return mem


# One wish to confide, not one per thing that happened (live 2026-11-06: 70+ identical "confide in someone" desires on
# one character, each at frustration 1.0, and those whose memory had since been forgotten could never resolve). The
# desire lists what they want to get off their chest; told or forgotten things drop off; with nothing left it is over.
ABOUT_KEPT = 10


def _confide_desire(c, create=False, importance=0.5):
    """The character's single confide_in_someone desire (older saves' copies are merged into it), or None."""
    desires = c.setdefault("persistent_desires", [])
    mine = [d for d in desires if d.get("type") == "confide_in_someone" and d.get("active") and not d.get("resolved")]
    if not mine and not create:
        return None
    if not mine:
        d = add_desire(c, "confide_in_someone", target=None, importance=importance)
        d.update(active=True, resolved=False)
        d.setdefault("about", [])
        return d
    keep = mine[0]
    about = list(keep.get("about") or [])
    for d in mine:
        for mid in ([d.get("target")] if d.get("target") else []) + list(d.get("about") or []):
            if mid not in about:
                about.append(mid)
        keep["importance"] = max(keep.get("importance", 0), d.get("importance", 0))
        keep["frustration"] = max(keep.get("frustration", 0), d.get("frustration", 0))
    keep["about"], keep["target"] = about[-ABOUT_KEPT:], None
    keep["importance"] = max(keep["importance"], importance if create else 0)
    if len(mine) > 1:
        drop = {id(d) for d in mine[1:]}
        c["persistent_desires"] = [d for d in desires if id(d) not in drop]
    return keep


def _still_to_tell(c, d):
    """The memories this desire is about that are still remembered and not yet told -- pruning the rest."""
    memories = {m.get("id"): m for m in c.get("memories", [])}
    d["about"] = [mid for mid in d.get("about") or [] if mid in memories and not memories[mid].get("confided")]
    return [memories[mid] for mid in d["about"]]


def _close(d):
    d["resolved"], d["active"] = True, False


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
    desire = _confide_desire(c)
    if not desire:
        return
    to_tell = _still_to_tell(c, desire)
    if not to_tell:
        _close(desire)                       # everything was told or has been forgotten
        return

    confidant = _find_confidant(c, world)
    if not confidant:
        return                               # nobody they trust enough: the wish stays (once)

    for mem in to_tell:
        _do_confide(c, confidant, mem, world)
        mem["confided"] = True
        mem.setdefault("told_to", []).append(confidant["id"])
    desire["about"] = []
    _close(desire)


def _do_confide(c, confidant, mem, world):
    style = "seek_validation" if "seek_validation" in mem.get("tags", []) else "seek_comfort"
    rel = c.setdefault("relationships", {}).setdefault(confidant["id"], {})

    if style == "seek_validation":
        from llm.validation_scenario import generate_validation_response
        session = c.setdefault("llm_session", {"history": []})
        try:
            result = run_llm_call(
                generate_validation_response(confidant, c, mem.get("text", ""), world, session),
                priority=PRIORITY_BACKGROUND,
            )
        except Exception:
            result = None
        # generate_validation_response() always returns a real
        # {"approves", "text"} dict (it has its own fallback), except when
        # run_llm_call() itself resolves to {"error": ...} for a
        # preempted/cancelled call -- that dict is also truthy, and
        # result.get("approves") on it silently comes back None/False
        # rather than actually falling back to the coin-flip default below.
        if isinstance(result, dict) and "error" in result:
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


# ── Narrative context (brain/context_builder.py) ───────────────────────────

def get_confiding_context(c, world):
    """Surfaces an active, unconfided confide_in_someone desire -- "you've
    been wanting to talk to someone about X" -- so the LLM can bring it
    up organically with a trusted contact rather than it only ever
    resolving silently through the daily resolve_confide_opportunities()
    sweep."""
    desire = _confide_desire(c)
    if not desire:
        return []
    to_tell = _still_to_tell(c, desire)
    if not to_tell:
        _close(desire)
        return []
    first = to_tell[-1].get("text", "something that happened")
    more = f" (and {len(to_tell) - 1} other thing{'s' if len(to_tell) > 2 else ''})" if len(to_tell) > 1 else ""
    return [f"You've been wanting to talk to someone about this: \"{first}\"{more}"]
