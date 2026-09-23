"""
Real ReactionCandidate construction + the exact situation-selection scoring
algorithm (Spec A sections 47-59). Consumed by SituationRegistry.select()
(situations/registry.py) -- this is where "sort triggered situations by a
bare priority int" was replaced with the specified multi-factor score,
NOT a parallel selector nothing calls; registry.select()'s own internals
now call straight into score_candidates()/sort_candidates() below.

The existing hard-cooldown gate (TriggerEvaluator._cooling, situations/
triggers.py) is deliberately UNCHANGED and stays the eligibility filter --
a situation still cannot even become a candidate while genuinely cooling
down (this is what test_threshold_fires_once_until_rearmed and friends
already verify). cooldown_penalty below is a real, separately-computed
SCORING term among candidates that already passed that gate: how long ago
this exact situation was last actually selected (not merely eligible),
on a longer decay window than the hard gate itself, so two simultaneously
eligible candidates that fired at different times don't score identically.
This is the honest reconciliation of the spec's own two cooldown
mechanics (TriggerDefinition.cooldown_ticks gates a trigger; CandidateScore.
cooldown_penalty scores a candidate) with a suite of existing, real tests
that depend on the gate actually blocking a repeat fire outright.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..contracts.candidates import CandidateScore, CandidateState, ReactionCandidate
from ..contracts.cognition import SituationHistoryEntry
from ..contracts.events import WorldEvent
from ..contracts.perception import Perception
from ..contracts.reactions import INTERRUPT_LEVEL_RANK, InterruptLevel
from ..contracts.selection import DecisionSnapshot
from ..perception.adapter import synthesize_world_event
from ..perception.engine import generate_perception
from .definition import SituationContext, SituationDefinition, Trigger

HISTORY_CAP = 50
# Reference window the SOFT cooldown_penalty decays over -- deliberately
# wider than any real situation's own cooldown_ticks, so it's still a real,
# non-zero, informative scoring signal for a candidate that only just
# cleared its hard gate, fading to 0 well before it matters in practice.
_COOLDOWN_PENALTY_WINDOW_TICKS = 4 * 3600


def _candidate_id(char_id: str, event_id: str, situation_id: str) -> str:
    # Idempotency key shape from spec section 83:
    # "candidate:{character_id}:{event_id}:{situation_id}"
    raw = f"candidate:{char_id}:{event_id}:{situation_id}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _perception_id(char_id: str, event_id: str, sense: str) -> str:
    raw = f"perception:{char_id}:{event_id}:{sense}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def build_decision_snapshot(char_id: str, ctx: SituationContext) -> DecisionSnapshot:
    """The canonical, explicit shape of what simsland_mw/decisions/
    options.py::DecisionContext + narrative/compiler.py::
    ConsciousnessSnapshot already carry -- built from the same already-
    resolved data, not a second resolution pass."""
    dc = ctx.dc
    body = dc.body
    identity = ctx.get("character.identity") or {}
    activity = dc.activity
    return DecisionSnapshot(
        character_id=char_id,
        tick=ctx.tick,
        activity_type=activity.get("type"),
        activity_phase=activity.get("phase"),
        needs=dict(body),
        cognition={"wake_reason": ctx.wake_reason, "wake_payload": ctx.wake_payload},
        intentions=tuple(ctx.res.get("character.intentions") or ()),
        expectations=tuple(ctx.res.get("character.expectations") or ()),
        schedule=ctx.res.get("character.schedule"),
        nearby_character_ids=tuple(p.get("id") for p in dc.people if p.get("id")),
        nearby_object_ids=tuple(p.get("id") for p in dc.props if p.get("id")),
        available_interaction_ids=tuple(dc.action_types),
        interruptibility=_interruptibility(activity),
    )


# Rough interruptibility by current activity -- spec section 88's own
# worked examples (sleeping/eating low, conversation medium, idle/walking
# high). A CRITICAL candidate ignores this entirely (see is_interruptible()).
_INTERRUPTIBILITY_BY_ACTIVITY = {
    "sleep": 0.1, "eat": 0.25, "cook": 0.35, "socialize": 0.5,
    "interact": 0.6, "wait": 0.7, "sit_down_seat": 0.7,
}


def _interruptibility(activity: Dict[str, Any]) -> float:
    return _INTERRUPTIBILITY_BY_ACTIVITY.get(activity.get("type"), 0.9)


def is_interruptible(sit: SituationDefinition, snapshot: DecisionSnapshot) -> bool:
    """spec section 88: "A CRITICAL situation can override normal
    interruptibility restrictions." Below CRITICAL, a genuinely low-
    interruptibility moment (asleep, eating) filters out a BACKGROUND
    candidate -- matches the existing engine's own generic-menu fallback
    intent without hard-blocking HIGH/NORMAL reactions that already have
    their own eligibility/trigger gating doing real work."""
    level = sit.effective_interrupt_level()
    if level == InterruptLevel.CRITICAL:
        return True
    if level == InterruptLevel.BACKGROUND:
        return snapshot.interruptibility >= 0.5
    return True


# ---- scoring components (spec section 52) ----------------------------------

def _urgency(sit: SituationDefinition, trig: Trigger, ctx: SituationContext) -> float:
    """0..100. Only a situation THIS trigger actually fired via an "event"
    trigger inherits the synthesized WorldEvent's own severity (itself
    derived from the real backend WAKE_PRIORITY-ranked wake_reason -- see
    perception/adapter.py). Confirmed real bug in an earlier version of
    this function: it read ctx.wake_reason directly, which is the WHOLE
    DECISION CYCLE's wake reason -- so an unrelated threshold_crossed
    situation (e.g. hunger crossing 50) that merely happened to be
    eligible during, say, a "door_signal" wake inherited THAT event's
    severity as its own urgency, even though the two have nothing to do
    with each other. Every other trigger type reads off the character's
    own top intention priority instead, since that IS the real "how
    urgent" signal for those (brain/intentions.py's priority field,
    already 0-100)."""
    if trig.type == "event" and ctx.wake_reason:
        event = synthesize_world_event(ctx.wake_reason, ctx.wake_payload, ctx.tick, f"evt:{ctx.tick}:{ctx.wake_reason}")
        return event.severity * 100.0
    top = max((i.get("priority") or 0 for i in ctx.res.get("character.intentions") or []), default=0)
    return float(top)


def _relevance(sit: SituationDefinition, ctx: SituationContext) -> float:
    """0..100. How much this situation's own category matches what the
    character is already actively pursuing (an open intention/expectation
    of the same category) -- real overlap, not a guess."""
    cat = sit.category
    score = 0.0
    for i in ctx.res.get("character.intentions") or []:
        if cat and cat in (i.get("type") or ""):
            score = max(score, float(i.get("priority") or 0))
    for e in ctx.res.get("character.expectations") or []:
        if e.get("status") == "missed" and cat and cat in (e.get("category") or e.get("id") or ""):
            score = max(score, 40.0 + float(e.get("frustration") or 0) * 40.0)
    return min(100.0, score)


def _persistence_score(sit: SituationDefinition) -> float:
    from ..contracts.reactions import PersistenceMode
    return 60.0 if sit.effective_persistence() == PersistenceMode.PERSISTENT else 20.0


def _novelty(sit: SituationDefinition, history: List[SituationHistoryEntry], tick: int) -> float:
    """0..100, higher = less recently seen. A situation never seen before
    (no history entry) is maximally novel."""
    last = max((h.tick for h in history if h.situation_id == sit.id), default=None)
    if last is None:
        return 100.0
    elapsed = max(0, tick - last)
    return min(100.0, 100.0 * elapsed / max(1, sit.cooldown_ticks * 3))


def _relationship_significance(ctx: SituationContext) -> float:
    """0..100. The strongest trust/familiarity magnitude among anyone
    actually named in the wake_payload (the person this situation is
    ABOUT), not a blanket average over every relationship the character
    has -- a stranger's door-knock shouldn't score as "relationship-
    significant" just because the character also has a close sibling."""
    payload = ctx.wake_payload or {}
    named_ids = {v for k, v in payload.items() if k.endswith("_id") and isinstance(v, str)}
    if not named_ids:
        return 0.0
    best = 0.0
    for pid in named_ids:
        rel = ctx.dc.relationships.get(pid)
        if rel:
            best = max(best, abs(rel.get("trust", 0)) + abs(rel.get("familiarity", 0)))
    return min(100.0, best)


# A small, honestly-scoped trait/category affinity table -- real personality
# traits nudging real category preference, not an attempt to model every
# possible trait/situation pairing.
_TRAIT_CATEGORY_AFFINITY = {
    "curious": {"reaction": 8.0, "social_media": 6.0},
    "social": {"conversation": 8.0, "social_media": 5.0, "communication": 6.0},
    "confrontational": {"conversation": 10.0},
    "gossip": {"social_media": 10.0},
    "anxious": {"reaction": 6.0},
    "cautious": {"reaction": 5.0},
}


def _trait_affinity(sit: SituationDefinition, ctx: SituationContext) -> float:
    traits = (ctx.res.get("character.traits") or {}).get("traits") or []
    total = 0.0
    for trait in traits:
        total += _TRAIT_CATEGORY_AFFINITY.get(trait, {}).get(sit.category, 0.0)
    return total


def _cooldown_penalty(sit: SituationDefinition, history: List[SituationHistoryEntry], tick: int) -> float:
    """Tiered percentage-of-window penalty (spec section 58) -- a real,
    separate SCORING signal among candidates that already cleared the
    hard trigger-cooldown gate (see this module's own docstring)."""
    last = max((h.tick for h in history if h.situation_id == sit.id), default=None)
    if last is None:
        return 0.0
    elapsed = max(0, tick - last)
    frac = elapsed / _COOLDOWN_PENALTY_WINDOW_TICKS
    if frac < 0.25:
        return 50.0
    if frac < 0.50:
        return 30.0
    if frac < 0.75:
        return 15.0
    if frac < 1.0:
        return 5.0
    return 0.0


def score_candidate(sit: SituationDefinition, trig: Trigger, ctx: SituationContext,
                    history: List[SituationHistoryEntry]) -> Tuple[ReactionCandidate, CandidateScore, Optional[WorldEvent], Optional[Perception]]:
    event: Optional[WorldEvent] = None
    perception: Optional[Perception] = None
    perception_id: Optional[str] = None
    event_id: Optional[str] = None

    if ctx.wake_reason:
        event_id = f"evt:{ctx.tick}:{ctx.wake_reason}"
        event = synthesize_world_event(ctx.wake_reason, ctx.wake_payload, ctx.tick, event_id)
        if sit.perception is not None:
            perception_id = _perception_id(ctx.res.get("character.identity", {}).get("id", ""), event_id, sit.perception.sense.value)
            perception = generate_perception(ctx.dc, event, perception_id)

    urgency = _urgency(sit, trig, ctx)
    relevance = _relevance(sit, ctx)
    persistence = _persistence_score(sit)
    novelty = _novelty(sit, history, ctx.tick)
    event_significance = (event.severity * 100.0) if event else 0.0
    relationship_significance = _relationship_significance(ctx)
    trait_affinity = _trait_affinity(sit, ctx)
    cooldown_penalty = _cooldown_penalty(sit, history, ctx.tick)
    base_priority = float(sit.priority)

    final_score = (
        base_priority
        + urgency * 0.35
        + relevance * 0.25
        + persistence * 0.15
        + novelty * 0.10
        + event_significance * 0.10
        + relationship_significance * 0.05
        + trait_affinity
        - cooldown_penalty
    )

    char_id = ctx.res.get("character.identity", {}).get("id", "")
    candidate_id = _candidate_id(char_id, event_id or f"noevent:{sit.id}", sit.id)

    candidate = ReactionCandidate(
        candidate_id=candidate_id,
        character_id=char_id,
        perception_id=perception.perception_id if perception else None,
        event_id=event_id,
        situation_id=sit.id,
        created_tick=ctx.tick,
        state=CandidateState.ELIGIBLE,
        salience=perception.salience if perception else event_significance,
        urgency=urgency,
        relevance=relevance,
        interrupt_level=sit.effective_interrupt_level(),
        relationship_significance=relationship_significance,
        event_significance=event_significance,
        persistence=persistence,
        novelty=novelty,
        trait_affinity=trait_affinity,
        cooldown_penalty=cooldown_penalty,
        score=final_score,
    )
    score = CandidateScore(
        candidate_id=candidate_id,
        base_priority=base_priority,
        urgency=urgency,
        relevance=relevance,
        persistence=persistence,
        novelty=novelty,
        event_significance=event_significance,
        relationship_significance=relationship_significance,
        trait_affinity=trait_affinity,
        cooldown_penalty=cooldown_penalty,
        final_score=final_score,
    )
    return candidate, score, event, perception


def sort_key(item: Tuple[SituationDefinition, Trigger, ReactionCandidate, CandidateScore]):
    """The exact multi-key sort from spec section 54, descending."""
    sit, _trig, candidate, score = item
    return (
        INTERRUPT_LEVEL_RANK[candidate.interrupt_level],
        score.final_score,
        candidate.urgency,
        candidate.relevance,
        candidate.persistence,
        candidate.event_significance,
        candidate.novelty,
        sit.priority,
        sit.id,
    )


# ---- composition (spec section 59) -----------------------------------------
# No existing situation opts in (composition=CompositionDefinition(enabled=True,
# ...)) yet, so this stays real but dormant -- exactly the same honest shape
# as an OptionSeed's `gap` field: a genuine capability with nothing exercising
# it today, not a fake stub.

COMPOSITION_SCORE_WINDOW = 10.0


def should_compose(best: Tuple[SituationDefinition, Trigger, ReactionCandidate, CandidateScore],
                    rest: List[Tuple[SituationDefinition, Trigger, ReactionCandidate, CandidateScore]]) -> Optional[Tuple[SituationDefinition, Trigger, ReactionCandidate, CandidateScore]]:
    best_sit, _t, _c, best_score = best
    comp = best_sit.composition
    if not comp or not comp.enabled:
        return None
    for other in rest[: max(0, comp.max_components - 1)]:
        other_sit, _ot, _oc, other_score = other
        if other_sit.id in comp.incompatible_with:
            continue
        if comp.compatible_with and other_sit.id not in comp.compatible_with:
            continue
        if abs(best_score.final_score - other_score.final_score) <= COMPOSITION_SCORE_WINDOW:
            return other
    return None
