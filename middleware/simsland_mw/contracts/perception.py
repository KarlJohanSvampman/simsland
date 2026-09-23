"""
Perception and its supporting contracts (spec sections 20-38).

A Perception is a character-specific sensory representation of a WorldEvent.
The same WorldEvent can produce a strong perception for one character, a
weak one for another, and none at all for a third -- WorldEvent != Perception,
always. See simsland_mw/perception/engine.py::generate_perception() for the
real implementation that builds these from a WorldEvent + CharacterSnapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .events import WorldLocation


class PerceptionSense(str, Enum):
    HEARING = "hearing"
    SIGHT = "sight"
    SMELL = "smell"
    TOUCH = "touch"
    DIGITAL = "digital"
    ENVIRONMENTAL = "environmental"


class PerceptionState(str, Enum):
    CREATED = "created"
    NOTICED = "noticed"
    EXPIRED = "expired"
    CONSUMED = "consumed"
    DISCARDED = "discarded"


@dataclass(frozen=True)
class PerceivedSound:
    volume: float
    character: Optional[str] = None
    duration_ticks: int = 1
    sudden: bool = False
    direction: Optional[str] = None
    distance: Optional[float] = None
    intelligibility: float = 1.0
    recognizable_source_id: Optional[str] = None


@dataclass(frozen=True)
class PerceivedSight:
    visibility: float
    distance: float = 0.0
    direction: Optional[str] = None
    movement: Optional[str] = None
    recognizable_character_ids: Tuple[str, ...] = ()
    recognizable_object_ids: Tuple[str, ...] = ()
    visual_tags: Tuple[str, ...] = ()
    line_of_sight: bool = True
    obscured: bool = False


@dataclass(frozen=True)
class PerceivedSmell:
    intensity: float
    character: Optional[str] = None
    direction: Optional[str] = None
    distance: Optional[float] = None
    recognizable_source_id: Optional[str] = None
    certainty: float = 1.0


@dataclass(frozen=True)
class PerceivedTouch:
    intensity: float
    temperature: Optional[float] = None
    pressure: Optional[float] = None
    texture: Optional[str] = None
    painful: bool = False
    recognizable_source_id: Optional[str] = None


@dataclass(frozen=True)
class PerceivedDigital:
    platform: str
    communication_type: str
    sender_character_id: Optional[str] = None
    recipient_character_ids: Tuple[str, ...] = ()
    mentioned_character_ids: Tuple[str, ...] = ()
    content_id: Optional[str] = None
    content_accessible: bool = False
    content_visible: bool = False
    notification_received: bool = True
    direct: bool = True
    public: bool = False
    audience_scope: Optional[str] = None


@dataclass(frozen=True)
class PerceivedEnvironment:
    environmental_type: str
    intensity: float
    direction: Optional[str] = None
    distance: Optional[float] = None
    persistence: str = "transient"
    observable_tags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PerceivedSensoryDetail:
    sound: Optional[PerceivedSound] = None
    sight: Optional[PerceivedSight] = None
    smell: Optional[PerceivedSmell] = None
    touch: Optional[PerceivedTouch] = None
    digital: Optional[PerceivedDigital] = None
    environmental: Optional[PerceivedEnvironment] = None


@dataclass(frozen=True)
class PerceptionKnowledgeScope:
    """What the character has actually LEARNED from this perception --
    essential for preventing information leakage (spec section 31, 89-90).
    simsland_mw/narrative/perception.py's sanitize_person()/
    FORBIDDEN_OTHER_KEYS/assert_no_leak already enforce this boundary at
    the narrative-compilation layer; this is the same boundary made an
    explicit, inspectable field on the Perception itself."""
    knows_event_occurred: bool = True
    knows_source: bool = False
    knows_source_identity: bool = False
    knows_target: bool = False
    knows_target_identity: bool = False
    knows_cause: bool = False
    knows_cause_identity: bool = False
    knows_location: bool = False
    knows_exact_location: bool = False
    knows_content: bool = False
    knows_content_identity: bool = False
    certainty: float = 1.0


@dataclass(frozen=True)
class PerceptionMetadata:
    perception_provider: str
    provider_version: str = "1.0"
    generated_tick: int = 0     # spec's `generated_at: datetime` -- see events.py's same note
    source_event_tick: int = 0
    deduplication_key: str = ""
    correlation_id: Optional[str] = None
    debug: Optional[Dict[str, Any]] = None


@dataclass
class Perception:
    schema_version: str

    perception_id: str

    character_id: str
    event_id: str

    tick: int

    state: PerceptionState
    sense: PerceptionSense

    source_type: Optional[str] = None
    source_id: Optional[str] = None

    location: Optional[WorldLocation] = None

    distance: Optional[float] = None
    direction: Optional[str] = None

    clarity: float = 1.0
    salience: float = 0.0
    certainty: float = 1.0

    observable_facts: Tuple[str, ...] = ()

    recognized_character_ids: Tuple[str, ...] = ()
    recognized_object_ids: Tuple[str, ...] = ()

    sensory_detail: PerceivedSensoryDetail = field(default_factory=PerceivedSensoryDetail)

    knowledge_scope: PerceptionKnowledgeScope = field(default_factory=PerceptionKnowledgeScope)

    created_tick: int = 0
    noticed_tick: Optional[int] = None
    consumed_tick: Optional[int] = None
    expires_tick: Optional[int] = None

    aggregation_id: Optional[str] = None

    metadata: PerceptionMetadata = None  # type: ignore[assignment]


@dataclass(frozen=True)
class PerceptionContext:
    character_id: str
    perception: Perception
    relationship_relevance: float = 0.0
    memory_relevance: float = 0.0
    expectation_relevance: float = 0.0
    intention_relevance: float = 0.0
    trait_affinity: float = 0.0
    event_significance: float = 0.0
    current_activity: Optional[str] = None
    interruptibility: float = 1.0
    current_location: Optional[WorldLocation] = None


@dataclass(frozen=True)
class PerceptionModifiers:
    distance: float = 1.0
    clarity: float = 1.0
    environmental: float = 1.0
    relationship: float = 0.0
    memory: float = 0.0
    expectation: float = 0.0
    intention: float = 0.0
    trait: float = 0.0
    danger: float = 0.0


@dataclass(frozen=True)
class CharacterSnapshot:
    """A read-only view of one character at one tick, built from whatever
    the middleware already resolved this decision cycle (simsland_mw/
    data/resolver.py's Resolution) -- not a second copy of the Character
    object Simsland owns."""
    character_id: str
    tick: int
    location: Optional[WorldLocation] = None
    activity_type: Optional[str] = None
    activity_phase: Optional[str] = None
    posture: Optional[str] = None
    traits: Tuple[str, ...] = ()
    physical_traits: Tuple[str, ...] = ()
    relationship_ids: Tuple[str, ...] = ()
    intention_ids: Tuple[str, ...] = ()
    expectation_ids: Tuple[str, ...] = ()
    recent_memory_ids: Tuple[str, ...] = ()
    schedule_state: Optional[str] = None
    cognition_state: Optional[str] = None
    current_interaction_id: Optional[str] = None
    interruptibility: float = 1.0
    off_grid: bool = False
