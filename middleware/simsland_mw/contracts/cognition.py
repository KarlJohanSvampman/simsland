"""
Cognition-adjacent contracts (spec sections 77-80, 94).

MemoryCandidate/BeliefCandidate are the shape a chosen option's
thought/speech should be packaged into before crossing into Simsland's own
memory/belief systems (backend/brain/memory.py, backend/brain/opinions.py)
-- the middleware itself never writes a memory or belief directly (spec
section 65's "the LLM cannot directly create memories/modify beliefs"
invariant); it's Simsland's cognition_processor (backend-side) that decides
whether a candidate actually becomes one. PerceptionAggregate/
SituationHistoryEntry/CharacterSession are the audit/continuity records
already covered in spirit by simsland_mw/sessions/session.py (recent
choices/thoughts) and the registry's per-character cooldown/crossed state
(simsland_mw/situations/registry.py::SituationRegistry._state) -- these
are the canonical, explicit shapes for the same data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class MemoryCandidate:
    character_id: str
    source_event_ids: Tuple[str, ...]
    source_perception_ids: Tuple[str, ...]
    text: str
    importance: float
    kind: str
    people: Tuple[str, ...] = ()
    tick: int = 0
    emotional_significance: float = 0.0
    novelty: float = 0.0


@dataclass(frozen=True)
class BeliefCandidate:
    character_id: str
    subject: str
    proposition: str
    confidence: float
    supporting_memory_ids: Tuple[str, ...] = ()
    contradicting_memory_ids: Tuple[str, ...] = ()
    source: str = ""
    created_tick: int = 0


@dataclass
class PerceptionAggregate:
    aggregate_id: str
    character_id: str
    perception_type: str
    source_ids: Tuple[str, ...]
    count: int
    first_tick: int
    last_tick: int
    salience: float
    observable_facts: Tuple[str, ...] = ()
    state: str = "active"   # ACTIVE | CONSUMED | EXPIRED | DISCARDED


@dataclass
class SituationHistoryEntry:
    situation_id: str
    tick: int
    trigger: str
    option_selected: Optional[str] = None


@dataclass
class CharacterSession:
    character_id: str
    llm_session: str = ""
    recent_thoughts: List[str] = field(default_factory=list)
    recent_conversations: List[str] = field(default_factory=list)
    recent_interpretations: List[str] = field(default_factory=list)
    last_cognition_time: int = 0
    next_cognition_time: int = 0
    pending_situation_id: Optional[str] = None
