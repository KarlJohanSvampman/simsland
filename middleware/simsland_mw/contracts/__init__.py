"""
Canonical data contracts (Simsland Middleware spec v1.0, "Spec A" -- the
Character Cognition, Perception, Reaction & Decision Middleware
specification, sections 4-98).

This package is the "unambiguous source of truth" the spec asks for: every
dataclass/enum below matches the spec's own field names and types, adapted
only where this codebase's own conventions require it (tick-int timestamps
throughout instead of `datetime`, since every other system in this
simulation is tick-native; `Any`/dict payloads kept where the spec itself
leaves a field intentionally open).

These are not a second, parallel architecture sitting next to the real one.
Per the user's explicit direction ("replace what is" -- not add alongside
it): SituationDefinition (simsland_mw/situations/definition.py) IS this
codebase's concrete authoring form of ReactionDefinition, extended with the
canonical fields directly rather than duplicated into a second class;
Resolution/Registry (simsland_mw/data/resolver.py, data/registry.py)
already implement DataResponse/ProviderDefinition's exact behavior
(dependency-waved, concurrent, cached resolution -- spec section 76) and
are referenced here, not reimplemented; SituationRegistry.select() (spec
section 54's algorithm) now actually computes the specified score and
constructs real ReactionCandidate/CandidateScore objects rather than
sorting by a bare priority int. See simsland_mw/perception/engine.py and
simsland_mw/situations/candidates.py for where these types are actually
built and consumed.
"""

from .events import (
    EventCategory, EventSourceType, EventTargetType,
    EventSource, EventTarget, EventTemporalData, EventVisibility,
    SoundEventData, VisualEventData, SmellEventData, TouchEventData,
    DigitalEventData, EnvironmentalEventData, ObservableEventData,
    EventCausation, EventMetadata, WorldLocation, WorldEvent,
)
from .perception import (
    PerceptionSense, PerceptionState,
    PerceivedSound, PerceivedSight, PerceivedSmell, PerceivedTouch,
    PerceivedDigital, PerceivedEnvironment, PerceivedSensoryDetail,
    PerceptionKnowledgeScope, PerceptionMetadata, Perception,
    PerceptionContext, PerceptionModifiers, CharacterSnapshot,
)
from .reactions import (
    PersistenceMode, InterruptLevel, TriggerType,
    TriggerDefinition, PerceptionRequirement, EligibilityDefinition,
    OptionDefinition, RenderedOption, CooldownDefinition,
    CompositionDefinition, ReactionDefinition,
)
from .candidates import (
    CandidateState, ReactionCandidate, CandidateQueue, CandidateScore,
)
from .selection import (
    DecisionSnapshot, SituationSelectionRequest, SituationSelectionResult,
    SelectionDecision,
)
from .situation_instance import (
    SituationState, SituationInstance, CompositeSituation,
    NarrativeContext, SituationPrompt,
)
from .decisions import (
    LLMDecision, DecisionRecord, ValidatedDecision,
    ActionRequest, ActionResult,
)
from .data_resolution import (
    DataRequest, DataResponse, DataResolutionError, ProviderDefinition,
)
from .cognition import (
    MemoryCandidate, BeliefCandidate, PerceptionAggregate,
    SituationHistoryEntry, CharacterSession,
)
from .transitions import StateTransition, transition

__all__ = [
    "EventCategory", "EventSourceType", "EventTargetType",
    "EventSource", "EventTarget", "EventTemporalData", "EventVisibility",
    "SoundEventData", "VisualEventData", "SmellEventData", "TouchEventData",
    "DigitalEventData", "EnvironmentalEventData", "ObservableEventData",
    "EventCausation", "EventMetadata", "WorldLocation", "WorldEvent",
    "PerceptionSense", "PerceptionState",
    "PerceivedSound", "PerceivedSight", "PerceivedSmell", "PerceivedTouch",
    "PerceivedDigital", "PerceivedEnvironment", "PerceivedSensoryDetail",
    "PerceptionKnowledgeScope", "PerceptionMetadata", "Perception",
    "PerceptionContext", "PerceptionModifiers", "CharacterSnapshot",
    "PersistenceMode", "InterruptLevel", "TriggerType",
    "TriggerDefinition", "PerceptionRequirement", "EligibilityDefinition",
    "OptionDefinition", "RenderedOption", "CooldownDefinition",
    "CompositionDefinition", "ReactionDefinition",
    "CandidateState", "ReactionCandidate", "CandidateQueue", "CandidateScore",
    "DecisionSnapshot", "SituationSelectionRequest", "SituationSelectionResult",
    "SelectionDecision",
    "SituationState", "SituationInstance", "CompositeSituation",
    "NarrativeContext", "SituationPrompt",
    "LLMDecision", "DecisionRecord", "ValidatedDecision",
    "ActionRequest", "ActionResult",
    "DataRequest", "DataResponse", "DataResolutionError", "ProviderDefinition",
    "MemoryCandidate", "BeliefCandidate", "PerceptionAggregate",
    "SituationHistoryEntry", "CharacterSession",
    "StateTransition", "transition",
]
