"""
WorldEvent and its supporting contracts (spec sections 4-19).

WorldEvent represents something that actually happened in Simsland: objective,
authoritative, immutable, independent of whether anyone perceived it. It is
never a thought, belief, narrative, perception, or interpretation.

Tick-int timestamps throughout (start_tick etc.) instead of the spec's
`datetime` for EventMetadata.created_at -- every other system in this
simulation is tick-native (see simsland_mw/situations/definition.py's own
tick field), so a real wall-clock datetime would be the odd one out with no
consumer that could use it meaningfully. Recorded as `created_tick: int`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class EventCategory(str, Enum):
    CHARACTER = "character"
    SOCIAL = "social"
    COMMUNICATION = "communication"
    OBJECT = "object"
    ENVIRONMENT = "environment"
    MOVEMENT = "movement"
    NEED = "need"
    WORK = "work"
    HOUSEHOLD = "household"
    RELATIONSHIP = "relationship"
    MEMORY = "memory"
    COGNITION = "cognition"
    DANGER = "danger"
    DIGITAL = "digital"
    SYSTEM = "system"


class EventSourceType(str, Enum):
    CHARACTER = "character"
    OBJECT = "object"
    BUILDING = "building"
    ROOM = "room"
    HOUSEHOLD = "household"
    SYSTEM = "system"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class EventTargetType(str, Enum):
    CHARACTER = "character"
    OBJECT = "object"
    BUILDING = "building"
    ROOM = "room"
    HOUSEHOLD = "household"
    LOCATION = "location"


@dataclass(frozen=True)
class EventSource:
    type: EventSourceType
    id: Optional[str] = None
    name: Optional[str] = None


@dataclass(frozen=True)
class EventTarget:
    type: EventTargetType
    id: str
    role: str = "target"   # actor | recipient | victim | observer | target | owner | speaker | listener


@dataclass(frozen=True)
class EventTemporalData:
    start_tick: int
    end_tick: Optional[int] = None
    duration_ticks: Optional[int] = None
    instantaneous: bool = True
    recurring: bool = False
    recurrence_key: Optional[str] = None


@dataclass(frozen=True)
class EventVisibility:
    audible: bool = False
    visible: bool = False
    smellable: bool = False
    touchable: bool = False
    digitally_observable: bool = False
    environmental: bool = False


@dataclass(frozen=True)
class SoundEventData:
    volume: float
    frequency: Optional[float] = None
    character: Optional[str] = None
    duration_ticks: int = 1
    sudden: bool = False
    continuous: bool = False
    direction: Optional[str] = None
    source_distance: Optional[float] = None


@dataclass(frozen=True)
class VisualEventData:
    visibility: float
    size: Optional[float] = None
    movement: Optional[str] = None
    color: Optional[str] = None
    brightness: Optional[float] = None
    direction: Optional[str] = None
    distance: Optional[float] = None
    line_of_sight_required: bool = True
    recognizable_character_ids: Tuple[str, ...] = ()
    recognizable_object_ids: Tuple[str, ...] = ()
    visual_tags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SmellEventData:
    intensity: float
    character: Optional[str] = None
    distance: Optional[float] = None
    direction: Optional[str] = None
    persistent: bool = False


@dataclass(frozen=True)
class TouchEventData:
    intensity: float
    temperature: Optional[float] = None
    pressure: Optional[float] = None
    texture: Optional[str] = None
    painful: bool = False
    source_object_id: Optional[str] = None


@dataclass(frozen=True)
class DigitalEventData:
    platform: str
    communication_type: str
    sender_character_id: Optional[str] = None
    recipient_character_ids: Tuple[str, ...] = ()
    mentioned_character_ids: Tuple[str, ...] = ()
    content_id: Optional[str] = None
    public: bool = False
    audience_type: Optional[str] = None
    notification_generated: bool = True
    direct: bool = True
    reply_to_content_id: Optional[str] = None


@dataclass(frozen=True)
class EnvironmentalEventData:
    environmental_type: str
    intensity: float
    affected_area: Optional[float] = None
    indoor: Optional[bool] = None
    outdoor: Optional[bool] = None
    persistent: bool = False
    tags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ObservableEventData:
    sound: Optional[SoundEventData] = None
    sight: Optional[VisualEventData] = None
    smell: Optional[SmellEventData] = None
    touch: Optional[TouchEventData] = None
    digital: Optional[DigitalEventData] = None
    environmental: Optional[EnvironmentalEventData] = None
    generic: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EventCausation:
    parent_event_ids: Tuple[str, ...] = ()
    cause_type: Optional[str] = None
    cause_entity_id: Optional[str] = None
    confidence: float = 1.0


@dataclass(frozen=True)
class EventMetadata:
    source_system: str
    source_version: Optional[str] = None
    created_tick: int = 0             # spec's `created_at: datetime` -- see module docstring
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    tags: Tuple[str, ...] = ()
    debug: Optional[Dict[str, Any]] = None   # never exposed to the LLM


@dataclass(frozen=True)
class WorldLocation:
    x: float = 0.0
    y: float = 0.0
    building_id: Optional[str] = None
    room_id: Optional[str] = None
    floor: Optional[int] = None
    zone_id: Optional[str] = None
    outdoor: Optional[bool] = None


@dataclass(frozen=True)
class WorldEvent:
    """Objective, authoritative, immutable. Independent of whether anyone
    perceived it (spec section 4). Simsland remains its sole author --
    see simsland_mw/events/adapter.py::synthesize_world_event() for how
    this middleware constructs one from what Simsland already told it
    (wake_reason/wake_payload), never inventing world truth of its own."""
    schema_version: str

    event_id: str
    tick: int

    type: str
    category: EventCategory

    source: Optional[EventSource]
    location: Optional[WorldLocation]

    participants: Tuple[str, ...]
    targets: Tuple[EventTarget, ...]

    observable: ObservableEventData

    severity: float
    visibility: EventVisibility

    temporal: EventTemporalData

    causation: Optional[EventCausation]

    metadata: EventMetadata
