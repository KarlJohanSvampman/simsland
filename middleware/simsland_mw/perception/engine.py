"""
Perception generation (spec sections 20-38).

generate_perception() implements the real subset of the spec's 12-step
pipeline (section 37) that this middleware can actually do something with,
given what's already resolved this decision cycle (simsland_mw/data/
resolver.py's Resolution -- nearby people with real distances,
relationships with real trust/familiarity, already filtered through the
same character-knowledge boundary simsland_mw/narrative/perception.py
enforces):

  1. Check spatial relationship      -> distance from dc.people, if the
                                         event names a source character
  2. Check sensory compatibility     -> _sense_for_category()
  5. Calculate clarity               -> _clarity_from_distance()
  6. Determine recognition           -> is the source in dc.people /
                                         dc.relationships at all?
  8. Calculate salience              -> severity * clarity, 0..100
  9. Apply perception threshold      -> caller compares against a
                                         PerceptionRequirement.minimum_salience
  10. Create perception               -> real Perception object, below

Steps 3 (line-of-sight/environmental propagation), 4 (character-specific
access beyond relationship/co-location), 7 (recognition beyond "do I know
this person"), 11 (deduplication) and 12 (aggregation) are NOT built this
pass -- named here rather than silently skipped. The character-knowledge
boundary itself (never leaking another character's private state) is
already real and enforced elsewhere (simsland_mw/narrative/perception.py's
sanitize_person/assert_no_leak) and this function never reads anything
beyond what that boundary already permits.

The middleware must never assume an event was perceived simply because it
happened nearby (spec section 37's own closing line) -- this is why
generate_perception() is only ever called for the ONE character Simsland
already decided to wake (see synthesize_world_event()'s own docstring):
that decision -- who gets to know something happened at all -- remains
Simsland's, never re-derived here from raw proximity.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..contracts.events import EventCategory, WorldEvent
from ..contracts.perception import (
    Perception, PerceptionKnowledgeScope, PerceptionMetadata,
    PerceptionSense, PerceptionState,
)

_SENSE_BY_CATEGORY: Dict[EventCategory, PerceptionSense] = {
    EventCategory.SOCIAL: PerceptionSense.SIGHT,
    EventCategory.COMMUNICATION: PerceptionSense.HEARING,
    EventCategory.ENVIRONMENT: PerceptionSense.ENVIRONMENTAL,
    EventCategory.DIGITAL: PerceptionSense.DIGITAL,
    EventCategory.DANGER: PerceptionSense.SIGHT,
    EventCategory.NEED: PerceptionSense.ENVIRONMENTAL,
    EventCategory.WORK: PerceptionSense.ENVIRONMENTAL,
    EventCategory.CHARACTER: PerceptionSense.SIGHT,
    EventCategory.COGNITION: PerceptionSense.ENVIRONMENTAL,
    EventCategory.SYSTEM: PerceptionSense.ENVIRONMENTAL,
}


def _sense_for(event: WorldEvent) -> PerceptionSense:
    if event.visibility.audible:
        return PerceptionSense.HEARING
    if event.visibility.digitally_observable:
        return PerceptionSense.DIGITAL
    if event.visibility.visible:
        return PerceptionSense.SIGHT
    return _SENSE_BY_CATEGORY.get(event.category, PerceptionSense.ENVIRONMENTAL)


def _clarity_from_distance(distance: Optional[float]) -> float:
    """1.0 close-up, falling off linearly to a 0.15 floor by 15 distance
    units -- close enough for a life-sim's room-scale distances without
    pretending to model real acoustic/optical falloff."""
    if distance is None:
        return 1.0    # no known distance (e.g. a digital/system event) -- full clarity, nothing to attenuate
    return max(0.15, min(1.0, 1.0 - (distance / 15.0) * 0.85))


def generate_perception(dc: Any, event: WorldEvent, perception_id: str) -> Perception:
    """`dc` is a simsland_mw.decisions.options.DecisionContext (duck-typed
    here, not imported, to avoid situations/ <-> perception/ import
    coupling -- both already depend on data/resolver.py, neither should
    depend on the other)."""
    source_id = event.source.id if event.source else None

    # DETECTION ("I see someone there") vs RECOGNITION ("I recognize
    # Sarah") are deliberately distinct (spec section 38) -- confirmed
    # real bug in an earlier version of this function: it treated mere
    # presence in dc.people (detection -- gives distance, nothing else)
    # as recognition too, which is exactly the leak simsland_mw/narrative/
    # perception.py::describe_person_nearby() already guards against
    # elsewhere in this codebase ("known = p.get('id') in relationships,"
    # never just co-presence). Recognition here uses that same signal.
    distance = None
    if source_id:
        person = next((p for p in dc.people if p.get("id") == source_id), None)
        if person is not None:
            distance = person.get("distance")
    recognized = bool(source_id) and source_id in dc.relationships

    clarity = _clarity_from_distance(distance)
    salience = round(event.severity * 100.0 * clarity, 1)
    certainty = 1.0 if (recognized or source_id is None) else 0.55

    knowledge_scope = PerceptionKnowledgeScope(
        knows_event_occurred=True,
        knows_source=bool(source_id),
        knows_source_identity=recognized,
        knows_target=False,
        knows_target_identity=False,
        knows_cause=event.causation is not None,
        knows_cause_identity=False,
        knows_location=event.location is not None,
        knows_exact_location=False,
        knows_content=bool(event.observable.generic),
        knows_content_identity=recognized,
        certainty=certainty,
    )

    return Perception(
        schema_version="1.0",
        perception_id=perception_id,
        character_id=dc.res.get("character.identity", {}).get("id") if hasattr(dc, "res") else "",
        event_id=event.event_id,
        tick=event.tick,
        state=PerceptionState.CREATED,
        sense=_sense_for(event),
        source_type=(event.source.type.value if event.source else None),
        source_id=source_id,
        location=event.location,
        distance=distance,
        direction=None,
        clarity=clarity,
        salience=salience,
        certainty=certainty,
        observable_facts=tuple(event.metadata.tags),
        recognized_character_ids=(source_id,) if recognized and source_id else (),
        recognized_object_ids=(),
        knowledge_scope=knowledge_scope,
        created_tick=event.tick,
        metadata=PerceptionMetadata(
            perception_provider="synthesized_from_wake_payload",
            generated_tick=event.tick,
            source_event_tick=event.tick,
            deduplication_key=f"perception:{event.event_id}:{_sense_for(event).value}",
        ),
    )
