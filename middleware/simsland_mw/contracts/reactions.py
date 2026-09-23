"""
Reaction taxonomy contracts (spec sections 39-46, 58-59).

ReactionDefinition is NOT reimplemented as a second class here.
simsland_mw/situations/definition.py::SituationDefinition IS this
codebase's concrete authoring form of it -- see that module for why (30+
real, tested situations already exist in that shape; duplicating the
concept into a disconnected ReactionDefinition class that nothing actually
builds would be exactly the parallel-state problem this pass is meant to
retire, not add to). What's defined here are the pieces SituationDefinition
was genuinely missing and now carries as real fields: InterruptLevel,
PersistenceMode, PerceptionRequirement, CooldownDefinition (with the
spec's tiered percentage penalty, not a hard gate),
CompositionDefinition. TriggerDefinition/EligibilityDefinition/
OptionDefinition/RenderedOption are provided for completeness and for any
future author who wants the fully explicit canonical shape; the existing
Trigger/OptionSeed classes remain the lighter, working, in-use form (see
simsland_mw/situations/candidates.py for how a Trigger's minimal fields
already satisfy an EligibilityDefinition/PerceptionRequirement check).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from .perception import PerceptionSense


class PersistenceMode(str, Enum):
    TRANSIENT = "transient"
    PERSISTENT = "persistent"


class InterruptLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    BACKGROUND = "background"


# Ordinal rank for sorting/comparison -- CRITICAL > HIGH > NORMAL > BACKGROUND
# (spec section 49). Higher number wins.
INTERRUPT_LEVEL_RANK = {
    InterruptLevel.BACKGROUND: 0,
    InterruptLevel.NORMAL: 1,
    InterruptLevel.HIGH: 2,
    InterruptLevel.CRITICAL: 3,
}


class TriggerType(str, Enum):
    EVENT = "event"
    CONDITION = "condition"
    THRESHOLD_CROSSED = "threshold_crossed"
    TIME = "time"
    SCHEDULE = "schedule"
    EXPECTATION = "expectation"
    RELATIONSHIP_EVENT = "relationship_event"
    MEMORY = "memory"
    INTENTION = "intention"
    IDLE = "idle"
    PERCEPTION = "perception"


@dataclass(frozen=True)
class TriggerDefinition:
    type: TriggerType
    event_types: Tuple[str, ...] = ()
    condition: Optional[str] = None
    threshold_field: Optional[str] = None
    threshold_operator: Optional[str] = None
    threshold_value: Optional[float] = None
    intention_type: Optional[str] = None
    expectation_type: Optional[str] = None
    relationship_event_type: Optional[str] = None
    memory_type: Optional[str] = None
    minimum_salience: Optional[float] = None
    cooldown_ticks: Optional[int] = None


@dataclass(frozen=True)
class PerceptionRequirement:
    sense: PerceptionSense
    minimum_salience: float = 20.0
    minimum_clarity: float = 0.0
    requires_line_of_sight: bool = False
    maximum_distance: Optional[float] = None
    requires_same_room: bool = False
    requires_same_building: bool = False
    requires_outdoor_visibility: bool = False
    aggregation_allowed: bool = False


@dataclass(frozen=True)
class EligibilityDefinition:
    required_traits: Tuple[str, ...] = ()
    excluded_traits: Tuple[str, ...] = ()
    required_relationship: Optional[str] = None
    required_activity: Tuple[str, ...] = ()
    excluded_activity: Tuple[str, ...] = ()
    requires_character_present: bool = False
    requires_target_present: bool = False
    requires_target_relationship: bool = False
    minimum_age: Optional[int] = None
    maximum_age: Optional[int] = None
    custom_conditions: Tuple[str, ...] = ()


@dataclass(frozen=True)
class OptionDefinition:
    id: str
    description: str
    action: Optional[str] = None
    target_type: Optional[str] = None
    requires_target: bool = False
    required_capabilities: Tuple[str, ...] = ()
    eligibility_conditions: Tuple[str, ...] = ()
    composable: bool = True
    ends_situation: bool = True


@dataclass(frozen=True)
class RenderedOption:
    id: str
    description: str
    available: bool
    unavailable_reason: Optional[str] = None
    target_character_id: Optional[str] = None
    target_object_id: Optional[str] = None


@dataclass(frozen=True)
class CooldownDefinition:
    duration_ticks: int
    repeated_trigger_penalty: float = 0.0
    bypass_interrupt_levels: Tuple[InterruptLevel, ...] = (InterruptLevel.CRITICAL,)
    aggregate_repeated_events: bool = False
    aggregation_window_ticks: Optional[int] = None


@dataclass(frozen=True)
class CompositionDefinition:
    enabled: bool = False
    compatible_with: Tuple[str, ...] = ()
    incompatible_with: Tuple[str, ...] = ()
    max_components: int = 2
    priority_mode: str = "highest_priority_primary"


@dataclass(frozen=True)
class ReactionDefinition:
    """The fully explicit canonical shape (spec section 42) -- provided so
    a SituationDefinition can be converted to/inspected as one (see
    SituationDefinition.as_reaction_definition() in
    simsland_mw/situations/definition.py) without requiring every existing
    situation to be re-authored in this shape."""
    id: str
    category: str
    subcategory: str
    priority: int
    persistence: PersistenceMode
    interrupt_level: InterruptLevel
    triggers: Tuple[TriggerDefinition, ...]
    perception: Optional[PerceptionRequirement]
    required_data: Tuple[str, ...]
    eligibility: EligibilityDefinition
    description_template: str
    options: Tuple[OptionDefinition, ...]
    cooldown: Optional[CooldownDefinition] = None
    composition: Optional[CompositionDefinition] = None
