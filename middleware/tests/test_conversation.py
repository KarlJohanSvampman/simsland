import json

import pytest

from conftest import ScriptedLLM
from simsland_mw.cognition.engine import CognitionEngine


def wake(w, reason, payload=None):
    w["meta"]["cognition"] = {"wake_reason": reason, "wake_payload": payload or {}}


def eng(sim, *replies):
    return CognitionEngine(sim, ScriptedLLM(*replies))


@pytest.mark.asyncio
async def test_insult_from_someone_nearby_fires_with_real_speech_options(sim, world):
    world["character"]["body"]["hunger"] = 10   # don't let need.hunger.noticeable win the tie
    wake(world, "provoked", {"actor_id": "den", "actor_name": "Dennis",
                             "provocation_type": "insult",
                             "reaction_hint": "Your gut reaction: mostly anger, but some hurt too."})
    e = eng(sim, json.dumps({"choice": "challenge_them", "speech": "Watch it."}))
    p = await e.prepare("kim", "provoked")
    assert p.situation.situation.id == "conversation.insult"
    assert "Dennis just insulted you" in p.situation.description
    assert "mostly anger" in p.situation.description
    ids = [o.id for o in p.options]
    assert {"ignore_the_insult", "challenge_them", "insult_them_back",
           "ask_why_theyre_being_like_this", "try_to_calm_things_down"} <= set(ids)
    rec = await e.decide("kim", "provoked", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "speak" and d["action"]["target"] == "den"
    assert d["speech"]["speech_act"] == "challenge" and d["speech"]["utterance"] == "Watch it."


@pytest.mark.asyncio
async def test_insult_names_the_leave_gap(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "provoked", {"actor_id": "den", "actor_name": "Dennis", "provocation_type": "insult"})
    p = await eng(sim).prepare("kim", "provoked")
    reasons = dict(p.situation.unresolved)
    assert "leave_conversation_deliberately" in reasons["walk_away"]


@pytest.mark.asyncio
async def test_other_provocation_types_dont_trigger_the_insult_situation(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "provoked", {"actor_id": "den", "actor_name": "Dennis", "provocation_type": "compliment"})
    p = await eng(sim).prepare("kim", "provoked")
    assert not p.situation or p.situation.situation.id != "conversation.insult"


@pytest.mark.asyncio
async def test_insult_from_someone_not_perceivable_does_not_fire(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "provoked", {"actor_id": "someone_offscreen", "actor_name": "A stranger",
                             "provocation_type": "insult"})
    p = await eng(sim).prepare("kim", "provoked")
    assert not p.situation or p.situation.situation.id != "conversation.insult"
