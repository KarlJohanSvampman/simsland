"""
Central state transition mechanism (spec sections 81, 99).

Every lifecycle change to a Perception/ReactionCandidate/SituationInstance
should go through transition() rather than a bare attribute assignment, so
there's one real, consistent audit trail (a list of StateTransition
records) instead of scattered, unaudited state writes. Validity is checked
against the ALLOWED_TRANSITIONS tables (spec section 82's three lifecycles)
-- an invalid transition raises rather than silently corrupting state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .candidates import CandidateState
from .perception import PerceptionState
from .situation_instance import SituationState


@dataclass(frozen=True)
class StateTransition:
    entity_type: str
    entity_id: str
    from_state: str
    to_state: str
    tick: int
    reason: str
    source_id: Optional[str] = None


class InvalidTransition(ValueError):
    pass


# spec section 82's three lifecycles, as (from -> allowed-to) sets.
ALLOWED_TRANSITIONS: Dict[str, Dict[str, set]] = {
    "Perception": {
        PerceptionState.CREATED.value: {PerceptionState.NOTICED.value, PerceptionState.EXPIRED.value,
                                         PerceptionState.DISCARDED.value},
        PerceptionState.NOTICED.value: {PerceptionState.CONSUMED.value, PerceptionState.EXPIRED.value},
        PerceptionState.CONSUMED.value: set(),   # consumed cannot return to noticed (spec section 22)
        PerceptionState.EXPIRED.value: set(),
        PerceptionState.DISCARDED.value: set(),
    },
    "ReactionCandidate": {
        CandidateState.CREATED.value: {CandidateState.ELIGIBLE.value, CandidateState.REJECTED.value},
        CandidateState.ELIGIBLE.value: {CandidateState.QUEUED.value, CandidateState.REJECTED.value},
        CandidateState.QUEUED.value: {CandidateState.SELECTED.value, CandidateState.SUPERSEDED.value,
                                       CandidateState.EXPIRED.value},
        CandidateState.SELECTED.value: {CandidateState.RESOLVED.value},
        CandidateState.RESOLVED.value: set(),    # resolved cannot return to queued (spec section 98)
        CandidateState.REJECTED.value: set(),
        CandidateState.SUPERSEDED.value: set(),
        CandidateState.EXPIRED.value: set(),
    },
    "SituationInstance": {
        SituationState.CREATED.value: {SituationState.PRESENTED.value, SituationState.CANCELLED.value},
        SituationState.PRESENTED.value: {SituationState.AWAITING_DECISION.value, SituationState.EXPIRED.value},
        SituationState.AWAITING_DECISION.value: {SituationState.DECIDED.value, SituationState.EXPIRED.value,
                                                  SituationState.CANCELLED.value},
        SituationState.DECIDED.value: {SituationState.EXECUTING.value},
        SituationState.EXECUTING.value: {SituationState.COMPLETED.value, SituationState.FAILED.value},
        SituationState.COMPLETED.value: set(),
        SituationState.FAILED.value: set(),
        SituationState.CANCELLED.value: set(),
        SituationState.EXPIRED.value: set(),
    },
}


def validate_transition(entity_type: str, from_state: str, to_state: str) -> None:
    if from_state == to_state:
        return
    table = ALLOWED_TRANSITIONS.get(entity_type)
    if table is None:
        return   # unknown entity type -- nothing to validate against, not an error
    allowed = table.get(from_state)
    if allowed is None or to_state not in allowed:
        raise InvalidTransition(f"{entity_type}: {from_state!r} -> {to_state!r} is not a permitted transition")


def transition(entity: Any, new_state: Any, *, tick: int, reason: str,
                source_id: Optional[str] = None, log: Optional[List[StateTransition]] = None) -> StateTransition:
    """Mutates entity.state in place (matches this codebase's mutable-
    dataclass convention for Perception/ReactionCandidate/SituationInstance)
    and returns (and, if `log` is given, appends) the StateTransition
    record. `log` is typically simsland_mw/situations/candidates.py's
    per-registry audit list."""
    entity_type = type(entity).__name__
    old_state = entity.state.value if hasattr(entity.state, "value") else entity.state
    new_value = new_state.value if hasattr(new_state, "value") else new_state
    validate_transition(entity_type, old_state, new_value)

    entity.state = new_state

    record = StateTransition(
        entity_type=entity_type,
        entity_id=getattr(entity, "candidate_id", None) or getattr(entity, "perception_id", None)
                  or getattr(entity, "situation_instance_id", None) or "",
        from_state=old_state,
        to_state=new_value,
        tick=tick,
        reason=reason,
        source_id=source_id,
    )
    if log is not None:
        log.append(record)
    return record
