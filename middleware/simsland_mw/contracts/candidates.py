"""
ReactionCandidate and its supporting contracts (spec sections 47-48, 53, 82).

Built for real by simsland_mw/situations/candidates.py::build_candidates()
on every selection pass, replacing the previous "sort triggered situations
by a bare priority int" logic with the spec's actual multi-factor scored
queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

from .reactions import InterruptLevel


class CandidateState(str, Enum):
    CREATED = "created"
    ELIGIBLE = "eligible"
    QUEUED = "queued"
    SELECTED = "selected"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


@dataclass
class ReactionCandidate:
    candidate_id: str
    character_id: str
    perception_id: Optional[str]
    event_id: Optional[str]
    situation_id: str
    created_tick: int
    state: CandidateState
    salience: float
    urgency: float
    relevance: float
    interrupt_level: InterruptLevel
    relationship_significance: float
    event_significance: float
    persistence: float
    novelty: float
    trait_affinity: float
    cooldown_penalty: float
    score: Optional[float] = None
    expires_tick: Optional[int] = None
    selected_tick: Optional[int] = None
    resolved_tick: Optional[int] = None
    superseded_by_candidate_id: Optional[str] = None


@dataclass
class CandidateQueue:
    character_id: str
    candidate_ids: Tuple[str, ...] = ()
    updated_tick: int = 0
    version: int = 0


@dataclass(frozen=True)
class CandidateScore:
    candidate_id: str
    base_priority: float
    urgency: float
    relevance: float
    persistence: float
    novelty: float
    event_significance: float
    relationship_significance: float
    trait_affinity: float
    cooldown_penalty: float
    final_score: float
