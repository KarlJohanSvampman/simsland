"""
WorldEvent synthesis (spec section 4: "WorldEvent represents something that
actually happened in Simsland: objective, authoritative, immutable").

Simsland does not hand the middleware a structured WorldEvent object today
-- it hands over a wake_reason string + wake_payload dict (backend/brain/
cognition_scheduler.py::wake_character()), decided entirely on the backend
side by real, authoritative logic (a contract was actually violated, a
door actually chimed, a body need actually crossed its threshold). That
IS Simsland's authoritative signal that something happened; this adapter
only gives it the canonical shape, it never invents world truth of its
own. Rebuilding wake_character()'s ~30 call sites across the backend to
emit a literal WorldEvent dataclass instead would mean rewriting Simsland
itself for a middleware-side type rename -- exactly backwards per spec
section 3's "the middleware must never become a second authoritative
simulation." Building the adapter here keeps Simsland the one source of
truth while still making WorldEvent real, populated, and consumed for
real (see simsland_mw/situations/candidates.py).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..contracts.events import (
    EventCategory, EventSource, EventSourceType, EventTemporalData,
    EventVisibility, EventMetadata, ObservableEventData, WorldEvent,
    WorldLocation,
)

# wake_reason -> (category, base_severity 0..1, visibility flags...)
# base_severity feeds ReactionCandidate.event_significance (spec section 52);
# not authored per-reaction on top of it, since the backend's own
# WAKE_PRIORITY table (brain/cognition_scheduler.py) already IS the
# authoritative "how urgent is this" ranking -- this mirrors its relative
# ordering rather than inventing a second, disconnected one.
_REASON_TABLE: Dict[str, Dict[str, Any]] = {
    "director_attention":  {"category": EventCategory.SYSTEM,        "severity": 1.00, "audible": True},
    "provoked":             {"category": EventCategory.SOCIAL,        "severity": 0.95, "audible": True, "visible": True},
    "heard_speech":          {"category": EventCategory.COMMUNICATION, "severity": 0.80, "audible": True},
    "door_signal":            {"category": EventCategory.COMMUNICATION, "severity": 0.75, "audible": True},
    "urgent_need":             {"category": EventCategory.NEED,          "severity": 0.85},
    "activity_aborted":         {"category": EventCategory.CHARACTER,     "severity": 0.60},
    "noticed_commotion":         {"category": EventCategory.ENVIRONMENT,   "severity": 0.65, "audible": True, "visible": True},
    "contract_violated":          {"category": EventCategory.SOCIAL,        "severity": 0.70},
    "activity_finished":           {"category": EventCategory.CHARACTER,     "severity": 0.30},
    "gave_up_waiting":               {"category": EventCategory.CHARACTER,     "severity": 0.45},
    "waiting_timed_out":              {"category": EventCategory.CHARACTER,     "severity": 0.40},
    "describe_result":                 {"category": EventCategory.COGNITION,     "severity": 0.20},
    "recall_result":                    {"category": EventCategory.COGNITION,     "severity": 0.20},
    "resolution_failed":                 {"category": EventCategory.SYSTEM,        "severity": 0.35},
    "activity_phase_changed":             {"category": EventCategory.CHARACTER,     "severity": 0.25},
    "person_entered_view":                 {"category": EventCategory.SOCIAL,        "severity": 0.35, "visible": True},
    "project_created":                       {"category": EventCategory.SOCIAL,        "severity": 0.35, "digitally_observable": True},
    "rumor_about_self":                       {"category": EventCategory.SOCIAL,        "severity": 0.55, "digitally_observable": True},
    "project_proposal_received":               {"category": EventCategory.SOCIAL,        "severity": 0.32},
    "proposal_countered":                       {"category": EventCategory.SOCIAL,        "severity": 0.30},
    "proposal_received":                         {"category": EventCategory.SOCIAL,        "severity": 0.28},
    "post_about_self":                            {"category": EventCategory.DIGITAL,       "severity": 0.28, "digitally_observable": True},
    "project_invited":                             {"category": EventCategory.DIGITAL,       "severity": 0.26, "digitally_observable": True},
    "rumor_seen":                                    {"category": EventCategory.DIGITAL,       "severity": 0.22, "digitally_observable": True},
    "proposal_resolved":                              {"category": EventCategory.SOCIAL,        "severity": 0.18},
    "schedule_block":                                  {"category": EventCategory.WORK,          "severity": 0.15},
    "wait_ready":                                       {"category": EventCategory.CHARACTER,     "severity": 0.10},
    "idle":                                              {"category": EventCategory.SYSTEM,        "severity": 0.00},
}
_DEFAULT_ENTRY = {"category": EventCategory.SYSTEM, "severity": 0.20}

# The payload keys that plausibly name the acting/authoring character, in
# priority order -- different backend systems this session named theirs
# differently (actor_id, author_id, from_id, ...).
_SOURCE_ID_KEYS = ("actor_id", "author_id", "from_id", "speaker_id")
_SOURCE_NAME_KEYS = ("actor_name", "author_name", "from_name", "speaker_name")


def synthesize_world_event(wake_reason: Optional[str], wake_payload: Dict[str, Any],
                            tick: int, event_id: str,
                            location: Optional[WorldLocation] = None) -> WorldEvent:
    entry = _REASON_TABLE.get(wake_reason or "idle", _DEFAULT_ENTRY)

    source_id = next((wake_payload.get(k) for k in _SOURCE_ID_KEYS if wake_payload.get(k)), None)
    source_name = next((wake_payload.get(k) for k in _SOURCE_NAME_KEYS if wake_payload.get(k)), None)
    source = (
        EventSource(type=EventSourceType.CHARACTER, id=source_id, name=source_name)
        if source_id or source_name else
        EventSource(type=EventSourceType.SYSTEM, id=None, name="simsland")
    )

    participants = tuple(sorted({p for p in (source_id,) if p}))

    return WorldEvent(
        schema_version="1.0",
        event_id=event_id,
        tick=tick,
        type=wake_reason or "idle",
        category=entry["category"],
        source=source,
        location=location,
        participants=participants,
        targets=(),
        observable=ObservableEventData(generic=dict(wake_payload)),
        severity=entry["severity"],
        visibility=EventVisibility(
            audible=entry.get("audible", False),
            visible=entry.get("visible", False),
            smellable=False,
            touchable=False,
            digitally_observable=entry.get("digitally_observable", False),
            environmental=entry.get("environmental", False),
        ),
        temporal=EventTemporalData(start_tick=tick, instantaneous=True),
        causation=None,   # backend systems don't yet expose a structured cause chain -- see EventCausation's own docstring on why this stays honestly unset rather than guessed
        metadata=EventMetadata(
            source_system="simsland_backend",
            created_tick=tick,
            tags=(wake_reason or "idle",),
        ),
    )
