"""
Tests for the Spec A canonical middleware architecture (WorldEvent ->
Perception -> ReactionCandidate -> scored selection): simsland_mw/contracts/,
simsland_mw/perception/, simsland_mw/situations/candidates.py.

The existing test_reactions.py/test_situations.py/... already exercise the
selection algorithm end-to-end through CognitionEngine; these tests target
the new layer directly -- real WorldEvent/Perception construction, the
exact scoring formula, interrupt-level inference, and the state-transition
audit trail -- rather than re-testing what those files already cover.
"""

import json

import pytest

from conftest import ScriptedLLM
from simsland_mw.cognition.engine import CognitionEngine
from simsland_mw.contracts.candidates import CandidateState
from simsland_mw.contracts.events import EventCategory
from simsland_mw.contracts.perception import PerceptionSense
from simsland_mw.contracts.reactions import InterruptLevel
from simsland_mw.perception.adapter import synthesize_world_event
from simsland_mw.perception.engine import generate_perception
from simsland_mw.situations.library import default_registry


def wake(w, reason, payload=None):
    w["meta"]["cognition"] = {"wake_reason": reason, "wake_payload": payload or {}}


def eng(sim, *replies):
    return CognitionEngine(sim, ScriptedLLM(*replies))


# ---- WorldEvent synthesis ---------------------------------------------------

def test_synthesize_world_event_maps_known_reason():
    ev = synthesize_world_event("provoked", {"actor_id": "den", "actor_name": "Dennis"}, 1000, "evt_1")
    assert ev.category == EventCategory.SOCIAL
    assert ev.source.id == "den" and ev.source.name == "Dennis"
    assert ev.visibility.audible and ev.visibility.visible
    assert 0.0 < ev.severity <= 1.0
    assert ev.temporal.start_tick == 1000
    assert ev.metadata.tags == ("provoked",)


def test_synthesize_world_event_falls_back_for_unknown_reason():
    ev = synthesize_world_event("some_totally_new_reason", {}, 500, "evt_2")
    assert ev.category == EventCategory.SYSTEM
    assert ev.source.type.value == "system"
    assert ev.severity == 0.20   # _DEFAULT_ENTRY


def test_world_event_is_immutable():
    ev = synthesize_world_event("idle", {}, 0, "evt_3")
    with pytest.raises(Exception):
        ev.tick = 999   # frozen dataclass -- spec section 4's "immutable"


# ---- Perception generation --------------------------------------------------

class _FakeDC:
    """Minimal duck-typed DecisionContext for generate_perception()'s own
    contract -- .people and .relationships are the only two attributes it
    reads."""
    def __init__(self, people, relationships, char_id="kim"):
        self.people = people
        self.relationships = relationships
        self.res = _FakeRes(char_id)


class _FakeRes:
    def __init__(self, char_id):
        self._char_id = char_id

    def get(self, key, default=None):
        if key == "character.identity":
            return {"id": self._char_id}
        return default


def test_generate_perception_recognized_source_close_by():
    ev = synthesize_world_event("provoked", {"actor_id": "den"}, 1000, "evt_4")
    dc = _FakeDC(people=[{"id": "den", "distance": 2}], relationships={"den": {"trust": 40}})
    p = generate_perception(dc, ev, "perc_1")
    assert p.character_id == "kim"
    assert p.event_id == "evt_4"
    # "provoked" is both audible and visible (_REASON_TABLE) -- _sense_for()
    # deliberately prefers audible first as its tie-break.
    assert p.sense == PerceptionSense.HEARING
    assert p.distance == 2
    assert p.clarity > 0.8            # close -> high clarity
    assert p.knowledge_scope.knows_source_identity is True
    assert p.knowledge_scope.certainty == 1.0
    assert "den" in p.recognized_character_ids


def test_generate_perception_unrecognized_distant_source_is_less_certain():
    ev = synthesize_world_event("provoked", {"actor_id": "stranger_1"}, 1000, "evt_5")
    dc = _FakeDC(people=[{"id": "stranger_1", "distance": 14}], relationships={})
    p = generate_perception(dc, ev, "perc_2")
    assert p.clarity < 0.3            # far away -> low clarity
    assert p.knowledge_scope.knows_source_identity is False
    assert p.knowledge_scope.certainty < 1.0
    assert p.recognized_character_ids == ()


def test_generate_perception_no_source_id_defaults_to_full_clarity():
    """A system/digital event with no named source character (e.g.
    schedule_block) shouldn't read as "far away and unclear" just because
    there's no one to compute a distance from."""
    ev = synthesize_world_event("schedule_block", {}, 1000, "evt_6")
    dc = _FakeDC(people=[], relationships={})
    p = generate_perception(dc, ev, "perc_3")
    assert p.distance is None
    assert p.clarity == 1.0


# ---- SituationDefinition's new canonical fields -----------------------------

def test_interrupt_level_inferred_from_priority():
    reg = default_registry()
    assert reg.get("conversation.accusation").effective_interrupt_level() == InterruptLevel.HIGH   # priority 78
    assert reg.get("social_media.rumor_seen").effective_interrupt_level() == InterruptLevel.NORMAL  # priority 45


def test_as_reaction_definition_round_trips_real_fields():
    reg = default_registry()
    sit = reg.get("communication.door_signal")
    rd = sit.as_reaction_definition()
    assert rd.id == sit.id
    assert rd.priority == sit.priority
    assert rd.cooldown.duration_ticks == sit.cooldown_ticks
    assert len(rd.options) == len(sit.options)


# ---- Real scoring drives selection + state-transition audit trail ----------

@pytest.mark.asyncio
async def test_selection_attaches_real_candidate_and_score(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "provoked", {"actor_id": "den", "actor_name": "Dennis", "provocation_type": "insult"})
    e = eng(sim, json.dumps({"choice": "ignore_the_insult"}))
    p = await e.prepare("kim", "provoked", commit=True)
    assert p.situation is not None
    assert p.situation.situation.id == "conversation.insult"
    cand = p.situation.candidate
    score = p.situation.score
    assert cand is not None and score is not None
    assert cand.state == CandidateState.RESOLVED   # transitioned all the way through by commit=True
    assert cand.interrupt_level == InterruptLevel.HIGH
    assert score.final_score == pytest.approx(
        score.base_priority + score.urgency * 0.35 + score.relevance * 0.25
        + score.persistence * 0.15 + score.novelty * 0.10 + score.event_significance * 0.10
        + score.relationship_significance * 0.05 + score.trait_affinity - score.cooldown_penalty
    )
    # Real state-transition audit trail (spec sections 81, 99) -- not just a
    # returned candidate, an actual logged history of how it got there.
    trail = [t for t in e.situations.transition_log if t.entity_id == cand.candidate_id]
    assert [t.to_state for t in trail] == ["queued", "selected", "resolved"]


@pytest.mark.asyncio
async def test_preview_does_not_advance_candidate_state(sim, world):
    """commit=False (a preview) must not resolve the candidate or append
    to the state-transition log -- mirrors the existing trigger-cooldown
    preview guarantee (test_preview_does_not_consume_the_trigger)."""
    world["character"]["body"]["hunger"] = 10
    wake(world, "door_signal", {"visitor_name": "Marcus"})
    e = eng(sim)
    p = await e.prepare("kim", "door_signal", commit=False)
    assert p.situation is not None
    assert p.situation.candidate.state == CandidateState.ELIGIBLE
    assert e.situations.transition_log == []


@pytest.mark.asyncio
async def test_unrelated_threshold_situation_does_not_inherit_wake_events_urgency(sim, world):
    """Confirmed real bug, fixed in situations/candidates.py::_urgency():
    a threshold_crossed situation eligible during an unrelated event-wake
    used to inherit THAT event's severity as its own urgency just because
    some wake_reason was set this cycle. door_signal (priority 65) must
    still outrank need.hunger.noticeable (priority 60) on its own real
    event urgency, not have hunger artificially inflated to match it."""
    wake(world, "door_signal", {"visitor_name": "Marcus"})   # hunger left at the fixture's own elevated default
    p = await eng(sim).prepare("kim", "door_signal", commit=False)
    assert p.situation is not None
    assert p.situation.situation.id == "communication.door_signal"
