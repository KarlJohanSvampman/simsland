"""
systems/nervosity.py

A shared "does the delivery land or flop" dice-roll gate for any speech
act that's really an attempt to influence, convince, or impress someone
through a risky social move -- a joke, a guilt trip, or a persuasive
argument (see conversation_analysis.py's "joke"/"guilt_trip" branches
and action_router.py::_route_make_argument). Each of these already has
its own narrative content (the LLM decides what's actually said); this
adds a real, deterministic chance the delivery itself succeeds, so a
rattled, unprepared character visibly fumbles more often than a calm,
practiced one -- not just flavor text.

difficulty = (stress + stakes) - preparation, each roughly 0-1, clamped
into a [0.05, 0.95] window before becoming the real FAILURE chance
(bounded so nothing is ever a guaranteed win or a guaranteed flop).
Reuses this codebase's existing bare random.random()-compare dice-roll
idiom rather than introducing a new resolution engine.

Deliberately NOT wired into the shared hostile-action resolver
(threaten/punch/etc, action_router.py::_route_hostile_action) this
round -- that resolver is combat-calibrated and shared with several
other systems (crime, conflict escalation, gang violence); scaring
someone via genuine intimidation belongs in this same difficulty model
eventually, but retrofitting it needs its own careful pass, not a
drive-by change here.
"""

import random

# Traits that make a risky social move easier (reduce difficulty) or
# harder (raise it) -- confirmed real, pickable trait_templates entries,
# not invented content (see definitions.json).
_PREP_TRAITS = {"confident": 0.15, "charismatic": 0.15, "manipulative": 0.1}
_PENALTY_TRAITS = {"nervous": 0.2}

# Authored base "how much is riding on this" per attempt type -- higher
# stakes means a steadier nerve is needed to pull it off.
STAKES = {
    "make_argument": 0.4,   # a real persuasive case in an active disagreement
    "joke":          0.15,  # low risk, but can still land flat
    "guilt_trip":    0.3,   # manipulative, real relationship risk if it backfires
}


def compute_preparation(actor, target=None, extra=0.0):
    """0-1ish bonus that lowers difficulty -- trait-driven confidence/
    charisma/manipulativeness, plus a small bonus for already knowing
    the target well (an unfamiliar audience is harder to read)."""
    traits = set(actor.get("traits", []) + actor.get("personality_traits", []))
    bonus = sum(v for t, v in _PREP_TRAITS.items() if t in traits)
    penalty = sum(v for t, v in _PENALTY_TRAITS.items() if t in traits)
    fam_bonus = 0.0
    if target:
        rel = actor.get("relationships", {}).get(target.get("id"), {})
        fam_bonus = min(0.15, rel.get("familiarity", 0) / 100.0 * 0.15)
    return max(0.0, bonus - penalty + fam_bonus + extra)


def compute_difficulty(actor, stakes, preparation):
    stress_component = actor.get("stress", 0) / 100.0
    return max(0.05, min(0.95, stress_component + stakes - preparation))


def attempt_influence(actor, action_type, target=None, extra_preparation=0.0):
    """Returns (success: bool, difficulty: float) -- a real dice roll
    against the computed difficulty (the chance of failure -- see module
    docstring for why higher difficulty means a lower success chance)."""
    stakes = STAKES.get(action_type, 0.3)
    preparation = compute_preparation(actor, target, extra_preparation)
    difficulty = compute_difficulty(actor, stakes, preparation)
    success = random.random() >= difficulty
    return success, difficulty
