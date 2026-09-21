import re

import pytest

from simsland_mw.cognition import decisions as prompts
from simsland_mw.data.registry import build_default_registry
from simsland_mw.data.resolver import Resolver
from simsland_mw.narrative import perception, semantic
from simsland_mw.narrative.compiler import compile_snapshot


async def _snapshot(sim, profile="general"):
    res = await Resolver(build_default_registry()).resolve(prompts.PROFILES[profile], sim, "kim")
    assert not res.errors, res.errors
    return compile_snapshot(res)


def test_body_numbers_become_language():
    text = semantic.describe_body({"hunger": 78, "fatigue": 43, "hydration": 51})
    assert text == "You are quite hungry and somewhat tired."


def test_body_fine_when_nothing_notable():
    assert semantic.describe_body({"hunger": 5, "fatigue": 5, "hydration": 90, "hygiene": 90}) \
        == "You feel physically fine."


def test_relationship_contrasts_care_with_low_trust():
    text = semantic.describe_relationship(
        "Dennis", {"friendship": 60, "trust": 20, "familiarity": 90, "respect": 55, "labels": ["spouse"]})
    assert "fond of Dennis (your spouse), but you don't really trust them" in text


def test_relationship_with_a_stranger():
    assert semantic.describe_relationship("Sam", {"familiarity": 3}) == "You hardly know Sam."


def test_money_only_mentioned_when_it_matters():
    assert semantic.describe_money({"wealth": 5000, "weekly_expenses": 400, "bills_due": []}) is None
    assert "tight" in semantic.describe_money({"wealth": 100, "weekly_expenses": 400, "bills_due": []})


async def test_prompt_contains_no_raw_state_numbers(sim):
    text = (await _snapshot(sim)).render()
    for leaked in ("hunger", "78", "trust", "42", "friendship", "71", "fatigue"):
        assert leaked not in text.lower(), leaked
    # times legitimately contain digits; nothing else should look like a stat
    assert not re.search(r"\b(?:hunger|energy|trust|friendship)\s*[:=]", text, re.I)


async def test_snapshot_has_the_consciousness_sections(sim):
    text = (await _snapshot(sim)).render()
    for title in ("WHO I AM", "HOW I FEEL", "WHAT I REMEMBER", "WHAT I BELIEVE",
                  "WHAT I'M WORRIED ABOUT", "WHAT I WANT"):
        assert title in text
    assert not re.search(r"fridge a\b", text) and "fridge" in text  # variant suffix stripped


async def test_own_passing_thoughts_are_not_replayed_as_memories(sim):
    assert "Seriously? Again?" not in (await _snapshot(sim)).render()


async def test_other_characters_private_state_never_reaches_prompt(sim):
    # A misbehaving bridge that leaks Dennis's inner life must still not reach the LLM.
    sim.world["environment"]["visible_people"][0].update({
        "memories": [{"text": "I am cheating on Kimberly"}],
        "active_intentions": [{"type": "hide_secret"}],
        "held_beliefs": [{"text": "Kimberly suspects nothing"}],
        "body": {"hunger": 99}, "last_thought": "she must never find out"})
    text = (await _snapshot(sim)).render()
    for secret in ("cheating", "hide_secret", "suspects nothing", "never find out"):
        assert secret not in text


def test_leak_guard_raises_on_private_fields():
    with pytest.raises(perception.LeakError):
        perception.assert_no_leak({"id": "den", "memories": []})


def test_sanitize_person_is_a_whitelist():
    out = perception.sanitize_person({"id": "d", "name": "D", "memories": [1], "body": {}})
    assert out == {"id": "d", "name": "D"}


def test_wake_lines():
    from simsland_mw.narrative.compiler import wake_sentence
    assert wake_sentence("urgent_need", {"need": "bladder"}) == "You urgently need the bathroom."
    assert wake_sentence("idle", {}) is None
    assert wake_sentence("heard_speech", {"speaker_name": "Dennis", "utterance": "Hi"}) \
        == 'Dennis just said to you: "Hi"'
    assert wake_sentence("heard_speech", {}) is None  # missing payload -> no crash
