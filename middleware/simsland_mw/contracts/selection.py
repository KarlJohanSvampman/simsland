"""
Situation selection contracts (spec sections 50-51, 55-57).

DecisionSnapshot mirrors simsland_mw/decisions/options.py::DecisionContext
+ simsland_mw/narrative/compiler.py::ConsciousnessSnapshot, which already
carry this exact information (needs, intentions, expectations, schedule,
nearby ids, activity, location, interruptibility) -- built here as the
canonical, explicit shape for anything that wants it without depending on
those two internal classes directly. See simsland_mw/situations/
candidates.py::build_decision_snapshot().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .candidates import CandidateScore, ReactionCandidate
from .events import WorldLocation


@dataclass(frozen=True)
class DecisionSnapshot:
    character_id: str
    tick: int
    location: Optional[WorldLocation] = None
    activity_type: Optional[str] = None
    activity_phase: Optional[str] = None
    needs: Dict[str, float] = field(default_factory=dict)
    cognition: Dict[str, Any] = field(default_factory=dict)
    intentions: Tuple[dict, ...] = ()
    expectations: Tuple[dict, ...] = ()
    schedule: Optional[dict] = None
    nearby_character_ids: Tuple[str, ...] = ()
    nearby_object_ids: Tuple[str, ...] = ()
    recent_event_ids: Tuple[str, ...] = ()
    current_interaction: Optional[dict] = None
    available_interaction_ids: Tuple[str, ...] = ()
    interruptibility: float = 1.0
    current_situation_id: Optional[str] = None


@dataclass(frozen=True)
class SituationSelectionRequest:
    character_id: str
    tick: int
    wake_reason: Optional[str]
    snapshot: DecisionSnapshot
    candidates: Tuple[ReactionCandidate, ...]


@dataclass(frozen=True)
class SituationSelectionResult:
    character_id: str
    tick: int
    selected_candidate_id: Optional[str]
    composed_candidate_ids: Tuple[str, ...]
    reason: str
    score: Optional[float]


@dataclass(frozen=True)
class SelectionDecision:
    character_id: str
    tick: int
    selected_candidate_id: Optional[str]
    rejected_candidate_ids: Tuple[str, ...]
    score_breakdowns: Tuple[CandidateScore, ...]
    composition_used: bool
    composition_candidate_ids: Tuple[str, ...]
    reason: str
