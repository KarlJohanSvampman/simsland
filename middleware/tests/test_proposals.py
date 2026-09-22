import json

import pytest

from conftest import ScriptedLLM
from simsland_mw.cognition.engine import CognitionEngine


def wake(w, reason, payload=None):
    w["meta"]["cognition"] = {"wake_reason": reason, "wake_payload": payload or {}}


def eng(sim, *replies):
    return CognitionEngine(sim, ScriptedLLM(*replies))


@pytest.mark.asyncio
async def test_proposal_received_fires_but_only_think_about_it_without_the_action_offered(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "proposal_received", {"from_name": "Dennis", "from_id": "den",
                                      "kind": "social_ask", "topic": "help with groceries",
                                      "proposal_id": "prop_1"})
    p = await eng(sim).prepare("kim", "proposal_received")
    assert p.situation.situation.id == "contract.proposal_received"
    assert "Dennis has proposed" in p.situation.description
    ids = [o.id for o in p.options]
    assert ids == ["think_about_it"]   # respond_social isn't in the mock world's action_types


@pytest.mark.asyncio
async def test_proposal_received_offers_accept_decline_counter_when_respond_social_available(sim, world):
    world["character"]["body"]["hunger"] = 10
    world["available_actions"]["action_types"].append("respond_social")
    wake(world, "proposal_received", {"from_name": "Dennis", "from_id": "den",
                                      "kind": "social_ask", "topic": "help with groceries",
                                      "proposal_id": "prop_1"})
    e = eng(sim, json.dumps({"choice": "accept_it"}))
    p = await e.prepare("kim", "proposal_received")
    ids = [o.id for o in p.options]
    assert {"accept_it", "decline_it", "counter_offer", "think_about_it"} <= set(ids)
    rec = await e.decide("kim", "proposal_received", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "respond_social"
    assert d["action"]["proposal_id"] == "prop_1" and d["action"]["response"] == "accept"


@pytest.mark.asyncio
async def test_proposal_received_omits_counter_for_recurring_offer(sim, world):
    world["character"]["body"]["hunger"] = 10
    world["available_actions"]["action_types"].append("respond_chore")
    wake(world, "proposal_received", {"from_name": "Dennis", "from_id": "den",
                                      "kind": "recurring_offer", "topic": "board_game_night",
                                      "proposal_id": "prop_2"})
    p = await eng(sim).prepare("kim", "proposal_received")
    ids = [o.id for o in p.options]
    assert "accept_it" in ids and "counter_offer" not in ids


@pytest.mark.asyncio
async def test_proposal_countered_reuses_the_same_situation(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "proposal_countered", {"from_name": "Dennis", "from_id": "den",
                                       "kind": "chore", "topic": "clean_kitchen",
                                       "proposal_id": "prop_3"})
    p = await eng(sim).prepare("kim", "proposal_countered")
    assert p.situation.situation.id == "contract.proposal_received"


@pytest.mark.asyncio
async def test_proposal_resolved_is_move_on_only_for_multi_recipient_proposals(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "proposal_resolved", {"kind": "chore", "topic": "clean_kitchen",
                                      "outcome_summary": "2 accepted, 1 declined",
                                      "proposal_id": "prop_1"})
    p = await eng(sim).prepare("kim", "proposal_resolved")
    assert p.situation.situation.id == "contract.proposal_resolved"
    assert "2 accepted, 1 declined" in p.situation.description
    ids = [o.id for o in p.options]
    assert ids == ["move_on"]


@pytest.mark.asyncio
async def test_proposal_resolved_offers_real_followup_with_a_single_known_other_party(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "proposal_resolved", {"kind": "social_ask", "topic": "help with groceries",
                                      "outcome_summary": "declined", "proposal_id": "prop_1",
                                      "other_id": "den", "other_name": "Dennis"})
    e = eng(sim, json.dumps({"choice": "ask_why", "speech": "Why not?"}))
    p = await e.prepare("kim", "proposal_resolved")
    ids = [o.id for o in p.options]
    assert {"thank_them", "ask_why", "move_on"} <= set(ids)
    rec = await e.decide("kim", "proposal_resolved", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "speak" and d["action"]["target"] == "den"
    assert d["speech"]["speech_act"] == "ask" and d["speech"]["utterance"] == "Why not?"
