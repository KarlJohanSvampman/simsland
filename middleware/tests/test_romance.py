import json

import pytest

from conftest import ScriptedLLM
from simsland_mw.cognition.engine import CognitionEngine


def wake(w, reason, payload=None):
    w["meta"]["cognition"] = {"wake_reason": reason, "wake_payload": payload or {}}


def eng(sim, *replies):
    return CognitionEngine(sim, ScriptedLLM(*replies))


@pytest.mark.asyncio
async def test_romantic_proposal_received_offers_accept_and_decline(sim, world):
    world["character"]["body"]["hunger"] = 10
    world["available_actions"]["action_types"].append("respond_romantic")
    wake(world, "proposal_received", {"from_id": "den", "from_name": "Dennis",
                                       "kind": "romantic", "topic": "ask_out",
                                       "proposal_id": "p1"})
    e = eng(sim, json.dumps({"choice": "accept_it"}))
    p = await e.prepare("kim", "proposal_received")
    assert p.situation.situation.id == "romance.romantic_proposal_received"
    ids = [o.id for o in p.options]
    assert {"accept_it", "decline_it", "think_about_it"} <= set(ids)
    rec = await e.decide("kim", "proposal_received", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "respond_romantic" and d["action"]["response"] == "accept"


@pytest.mark.asyncio
async def test_confession_gets_distinct_framing_from_ask_out(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "proposal_received", {"from_id": "den", "from_name": "Dennis",
                                       "kind": "romantic", "topic": "confess_love",
                                       "proposal_id": "p2"})
    e = eng(sim, json.dumps({"choice": "think_about_it"}))
    p = await e.prepare("kim", "proposal_received")
    assert "feelings for you" in p.situation.description


@pytest.mark.asyncio
async def test_romantic_proposal_answered_accepted(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "proposal_resolved", {"kind": "romantic", "topic": "ask_out",
                                       "outcome_summary": "accepted",
                                       "other_id": "den", "other_name": "Dennis",
                                       "proposal_id": "p1"})
    e = eng(sim, json.dumps({"choice": "tell_them_youre_glad",
                              "speech": "I'm really glad you said yes."}))
    p = await e.prepare("kim", "proposal_resolved")
    assert p.situation.situation.id == "romance.romantic_proposal_answered"
    assert "said yes" in p.situation.description
    ids = [o.id for o in p.options]
    assert "tell_them_youre_glad" in ids
    rec = await e.decide("kim", "proposal_resolved", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "speak" and d["action"]["target"] == "den"


@pytest.mark.asyncio
async def test_romantic_proposal_answered_declined_offers_different_options(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "proposal_resolved", {"kind": "romantic", "topic": "ask_out",
                                       "outcome_summary": "declined",
                                       "other_id": "den", "other_name": "Dennis",
                                       "proposal_id": "p1"})
    e = eng(sim, json.dumps({"choice": "sit_with_it"}))
    p = await e.prepare("kim", "proposal_resolved")
    assert "said no" in p.situation.description
    ids = [o.id for o in p.options]
    assert "accept_the_answer" in ids
    assert "tell_them_youre_glad" not in ids


@pytest.mark.asyncio
async def test_partner_flirted_with_someone_else_offers_confrontation(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "partner_flirted_with_someone_else", {
        "partner_id": "den", "partner_name": "Dennis",
        "flirted_with_id": "someone_else", "flirted_with_name": "a stranger",
    })
    e = eng(sim, json.dumps({"choice": "confront_partner",
                              "speech": "What was that with her?"}))
    p = await e.prepare("kim", "partner_flirted_with_someone_else")
    assert p.situation.situation.id == "romance.partner_flirted_with_someone_else"
    ids = [o.id for o in p.options]
    assert "confront_partner" in ids
    reasons = dict(p.situation.unresolved)
    assert "bring_it_up_later" in reasons
    rec = await e.decide("kim", "partner_flirted_with_someone_else", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "speak" and d["action"]["target"] == "den"


@pytest.mark.asyncio
async def test_partner_broke_up_with_me_offers_ask_why(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "partner_broke_up_with_me", {
        "initiator_id": "den", "initiator_name": "Dennis", "reason": "grew_apart",
    })
    e = eng(sim, json.dumps({"choice": "ask_why"}))
    p = await e.prepare("kim", "partner_broke_up_with_me")
    assert p.situation.situation.id == "romance.partner_broke_up_with_me"
    ids = [o.id for o in p.options]
    assert {"ask_why", "take_time_alone"} <= set(ids)
    reasons = dict(p.situation.unresolved)
    assert "reach_out_to_a_friend" in reasons
