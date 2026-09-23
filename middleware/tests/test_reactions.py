import json

import pytest

from conftest import ScriptedLLM
from simsland_mw.cognition.engine import CognitionEngine
from simsland_mw.simulation.mock import MockSimClient


def wake(w, reason, payload=None):
    w["meta"]["cognition"] = {"wake_reason": reason, "wake_payload": payload or {}}


def eng(sim, *replies):
    return CognitionEngine(sim, ScriptedLLM(*replies))


@pytest.mark.asyncio
async def test_door_signal_fires_with_ignore_always_available(sim, world):
    wake(world, "door_signal", {"visitor_name": "Marcus"})
    p = await eng(sim).prepare("kim", "door_signal")
    assert p.situation.situation.id == "communication.door_signal"
    assert "Marcus" in p.situation.description
    ids = [o.id for o in p.options]
    assert "ignore_it" in ids
    reasons = dict(p.situation.unresolved)
    # Neither of these has a real backend capability yet -- named, not silently
    # dropped -- see capability_report().
    assert "answer_door" in reasons["go_answer_the_door"]
    assert "call_out_generic" in reasons["call_out_that_youre_coming"]


@pytest.mark.asyncio
async def test_door_signal_offers_unlock_when_the_action_is_available(sim, world):
    world["available_actions"]["action_types"].append("unlock_door")
    wake(world, "door_signal", {"visitor_name": "Marcus"})
    p = await eng(sim).prepare("kim", "door_signal")
    ids = [o.id for o in p.options]
    assert "unlock_the_door_first" in ids


@pytest.mark.asyncio
async def test_commotion_offers_call_out_when_someone_is_nearby(sim, world):
    world["character"]["body"]["hunger"] = 10   # don't let need.hunger.noticeable also fire/outrank on a tie
    wake(world, "noticed_commotion", {"summary": "A loud metallic crash outside."})
    e = eng(sim, json.dumps({"choice": "call_out_to_check", "speech": "Everything okay out there?"}))
    p = await e.prepare("kim", "noticed_commotion")
    assert p.situation.situation.id == "reaction.commotion"
    assert p.situation.description == "A loud metallic crash outside."
    ids = [o.id for o in p.options]
    assert "keep_investigating" in ids and "call_out_to_check" in ids
    rec = await e.decide("kim", "noticed_commotion", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "speak" and d["action"]["target"] == "den"
    assert d["speech"]["utterance"] == "Everything okay out there?"


@pytest.mark.asyncio
async def test_commotion_without_anyone_nearby_still_offers_keep_or_let_go(sim, world):
    world["character"]["body"]["hunger"] = 10
    world["available_actions"]["nearby_characters"] = []
    world["environment"]["visible_people"] = []
    wake(world, "noticed_commotion", {"summary": "Something crashed somewhere."})
    p = await eng(sim).prepare("kim", "noticed_commotion")
    assert p.situation.situation.id == "reaction.commotion"
    ids = [o.id for o in p.options]
    assert "call_out_to_check" not in ids   # no one to call out to
    assert "keep_investigating" in ids


@pytest.mark.asyncio
async def test_post_about_self_fires_and_names_its_real_gaps(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "post_about_self", {"author_name": "Dennis", "author_id": "den", "post_id": "post_1"})
    p = await eng(sim).prepare("kim", "post_about_self")
    assert p.situation.situation.id == "social_media.post_about_self"
    assert "Dennis" in p.situation.description
    ids = [o.id for o in p.options]
    assert "ignore_it" in ids
    reasons = dict(p.situation.unresolved)
    assert "message_them_about_it" in reasons or "message_them_about_it" not in ids
    assert "comment_publicly" in reasons


@pytest.mark.asyncio
async def test_post_about_self_offers_reading_it_when_computer_is_available(sim, world):
    world["character"]["body"]["hunger"] = 10
    world["available_actions"]["action_types"].append("computer_social_media")
    wake(world, "post_about_self", {"author_name": "Dennis", "author_id": "den", "post_id": "post_1"})
    p = await eng(sim).prepare("kim", "post_about_self")
    ids = [o.id for o in p.options]
    assert "read_it_properly" in ids


@pytest.mark.asyncio
async def test_rumor_about_self_fires_with_confront_when_author_co_present(sim, world):
    world["character"]["body"]["hunger"] = 10
    world["available_actions"]["action_types"].append("post_social_media")
    e = eng(sim, json.dumps({"choice": "confront_them_directly", "speech": "Did you seriously post that about me?"}))
    wake(world, "rumor_about_self", {"author_name": "Dennis", "author_id": "den", "post_id": "post_1"})
    p = await e.prepare("kim", "rumor_about_self")
    assert p.situation.situation.id == "social_media.rumor_about_self"
    assert "Dennis" in p.situation.description
    ids = [o.id for o in p.options]
    assert {"deny_it_publicly", "explain_what_happened", "ignore_it", "confront_them_directly"} <= set(ids)
    reasons = dict(p.situation.unresolved)
    assert "message_them_privately" in reasons
    rec = await e.decide("kim", "rumor_about_self", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "speak" and d["action"]["target"] == "den"
    assert d["speech"]["speech_act"] == "accuse"


@pytest.mark.asyncio
async def test_rumor_about_self_without_author_co_present_still_offers_real_options(sim, world):
    world["character"]["body"]["hunger"] = 10
    world["available_actions"]["nearby_characters"] = []
    world["environment"]["visible_people"] = []
    world["available_actions"]["action_types"].append("post_social_media")
    wake(world, "rumor_about_self", {"author_name": "Someone", "author_id": "stranger_1", "post_id": "post_2"})
    p = await eng(sim).prepare("kim", "rumor_about_self")
    ids = [o.id for o in p.options]
    assert "confront_them_directly" not in ids
    assert "deny_it_publicly" in ids and "ignore_it" in ids


@pytest.mark.asyncio
async def test_rumor_seen_fires_with_ask_when_subject_co_present(sim, world):
    world["character"]["body"]["hunger"] = 10
    world["available_actions"]["action_types"].append("post_social_media")
    e = eng(sim, json.dumps({"choice": "ask_them_directly", "speech": "Hey, is it true what people are saying about you online?"}))
    wake(world, "rumor_seen", {
        "post_id": "post_3", "subject_id": "den", "subject_name": "Dennis",
        "author_id": "stranger_1", "author_name": "Someone",
    })
    p = await e.prepare("kim", "rumor_seen")
    assert p.situation.situation.id == "social_media.rumor_seen"
    assert "Dennis" in p.situation.description
    ids = [o.id for o in p.options]
    assert {"share_it", "defend_them", "ignore_it", "ask_them_directly"} <= set(ids)
    reasons = dict(p.situation.unresolved)
    assert "investigate" in reasons
    rec = await e.decide("kim", "rumor_seen", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "speak" and d["action"]["target"] == "den"
