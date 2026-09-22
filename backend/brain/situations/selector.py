"""
brain/situations/selector.py

Deterministic situation selection -- "what deserves this character's
attention right now" -- computed every tick from cheap, already-in-memory
state (c["active_intentions"], already populated by the existing, real
trigger/eligibility logic in systems/body_intentions.py, systems/
lt_needs.py, systems/social_intentions.py, systems/expectations.py, ...).
No LLM call anywhere in this module.

Honest scoping note (see scoring.py's own docstring for the fuller
version): this reuses c["active_intentions"] AS the candidate-situation
pool rather than building the proposal's separate situations/needs.py,
situations/social.py, etc. registry from scratch -- those generators
already do real trigger+eligibility work every tick; duplicating that in
a new shape would mean re-authoring each one a second time for no
behavioral gain. What THIS module adds on top, which genuinely didn't
exist before: interrupt-level short-circuiting, current-activity
interruptibility gating, cooldown/novelty/persistence scoring, composition
of near-tied situations, and a per-character selection history distinct
from real memory.

Also honest: the LLM-facing side of the proposal (a narrow, per-situation
option list built by a dedicated option_builder, replacing the generic
action menu build_available_actions() currently offers every tick) is
NOT implemented here -- that's a genuinely separate, large follow-up
touching action_registry.py/context_builder.py/llm_brain.py's whole
option-presentation contract. What IS wired in (see agent_loop.py's call
site) is the selection result being surfaced into the narrative context
as an explicit "this is what deserves your attention right now" framing,
which is real, working, and already changes what the LLM is told to
prioritize even though it doesn't yet constrain the raw action menu.
"""

from . import history as _history
from . import scoring as _scoring

# If the top two candidates' scores are within this margin, treat the
# situation as genuinely ambiguous and try composing them (proposal step
# 19) rather than arbitrarily picking the nominal "winner".
COMPOSE_MARGIN = 10.0

# Atomic body-need resolutions that ARE the answer to their own need --
# composing "hungry" with "eating" (the situation that satisfies hunger)
# is incoherent, per the proposal's own "eating + hunger -> NO" example.
_NON_COMPOSABLE_TYPES = {
    "sleep", "take_nap", "use_toilet", "use_toilet_bowels",
    "eat_food", "drink", "seek_caffeine_or_rest",
}


def situation_id(intention):
    """Identity for history/novelty/cooldown purposes -- includes the
    target when there is one, so e.g. "compliment_looks toward Dennis"
    and "compliment_looks toward Justin" are tracked as distinct
    situations rather than sharing one cooldown."""
    base = intention.get("type", "unknown")
    target = intention.get("target_id")
    return f"{base}:{target}" if target else base


def _composable(a, b):
    if a.get("type") in _NON_COMPOSABLE_TYPES or b.get("type") in _NON_COMPOSABLE_TYPES:
        return False
    # Only compose ordinary-tier situations -- HIGH/CRITICAL stay solo
    # (proposal: "Critical situations generally cannot be composed with
    # ordinary ones", extended here to HIGH out of the same caution).
    if _scoring.interrupt_level(a) > _scoring.NORMAL or _scoring.interrupt_level(b) > _scoring.NORMAL:
        return False
    return True


def select_situation(c, world):
    """Returns a dict describing the winning situation(s), or None if
    nothing is currently eligible to interrupt/occupy the character
    (they stay on whatever they were already doing):

    {
        "situations": [intention] or [intention, intention2],  # 2 only if composed
        "composed": bool,
        "interrupt_level": int,
        "level_name": str,
        "scores": {situation_id: breakdown_dict, ...},
    }
    """
    tick = world.get("tick", 0)
    candidates = c.get("active_intentions", [])
    if not candidates:
        return None

    # ---- Step: interrupt-level short-circuit ----
    critical = [i for i in candidates if _scoring.interrupt_level(i) == _scoring.CRITICAL]
    if critical:
        best = max(critical, key=lambda i: i.get("priority", 0))
        sid = situation_id(best)
        score, breakdown = _scoring.score_situation(best, sid, c, world, tick)
        _history.record_selection(c, sid, tick)
        return {
            "situations": [best],
            "composed": False,
            "interrupt_level": _scoring.CRITICAL,
            "level_name": _scoring.level_name(_scoring.CRITICAL),
            "scores": {sid: breakdown},
        }

    # ---- Step: interruptibility gating against the current activity ----
    eligible = [i for i in candidates if _scoring.can_interrupt(_scoring.interrupt_level(i), c)]
    if not eligible:
        return None

    # ---- Step: score every remaining candidate ----
    scored = []
    breakdowns = {}
    for i in eligible:
        sid = situation_id(i)
        score, breakdown = _scoring.score_situation(i, sid, c, world, tick)
        breakdowns[sid] = breakdown
        scored.append((i, sid, score))

    # Deterministic tie-break: interrupt level, then score, then the
    # stable situation id -- identical state always produces identical
    # behavior (proposal step 18).
    scored.sort(
        key=lambda entry: (
            _scoring.interrupt_level(entry[0]),
            entry[2],
            entry[1],
        ),
        reverse=True,
    )

    best_i, best_sid, best_score = scored[0]

    situations = [best_i]
    composed = False

    if len(scored) > 1:
        second_i, second_sid, second_score = scored[1]
        if (best_score - second_score) <= COMPOSE_MARGIN and _composable(best_i, second_i):
            situations = [best_i, second_i]
            composed = True

    for i in situations:
        _history.record_selection(c, situation_id(i), tick)

    top_level = max(_scoring.interrupt_level(i) for i in situations)
    return {
        "situations": situations,
        "composed": composed,
        "interrupt_level": top_level,
        "level_name": _scoring.level_name(top_level),
        "scores": breakdowns,
    }
