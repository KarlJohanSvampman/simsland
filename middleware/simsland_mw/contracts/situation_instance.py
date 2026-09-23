"""
SituationInstance and its supporting contracts (spec sections 60-64, 82).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .reactions import RenderedOption


class SituationState(str, Enum):
    CREATED = "created"
    PRESENTED = "presented"
    AWAITING_DECISION = "awaiting_decision"
    DECIDED = "decided"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class SituationInstance:
    situation_instance_id: str
    definition_id: str
    character_id: str
    candidate_id: str
    perception_ids: Tuple[str, ...]
    event_ids: Tuple[str, ...]
    created_tick: int
    state: SituationState
    selected_option_id: Optional[str] = None
    started_tick: Optional[int] = None
    decision_tick: Optional[int] = None
    completed_tick: Optional[int] = None
    expires_tick: Optional[int] = None
    failure_reason: Optional[str] = None


@dataclass
class CompositeSituation:
    situation_instance_id: str
    character_id: str
    primary_candidate_id: str
    component_candidate_ids: Tuple[str, ...]
    component_situation_ids: Tuple[str, ...]
    created_tick: int


@dataclass(frozen=True)
class NarrativeContext:
    character_id: str
    situation: SituationInstance
    semantic_data: Dict[str, Any] = field(default_factory=dict)
    perceptions: Tuple[Any, ...] = ()   # Perception, kept as Any to avoid an import cycle
    subjective_facts: Tuple[str, ...] = ()
    known_facts: Tuple[str, ...] = ()
    uncertain_facts: Tuple[str, ...] = ()
    relevant_memories: Tuple[str, ...] = ()
    relevant_relationships: Tuple[str, ...] = ()
    active_intentions: Tuple[str, ...] = ()
    active_expectations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SituationPrompt:
    situation_id: str
    character_id: str
    narrative: str
    options: Tuple[RenderedOption, ...]
    constraints: Tuple[str, ...] = ()
    response_schema_version: str = "1.0"
