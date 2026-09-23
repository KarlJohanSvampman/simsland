import json

import pytest

from conftest import ScriptedLLM
from simsland_mw.cognition.engine import CognitionEngine


def wake(w, reason, payload=None):
    w["meta"]["cognition"] = {"wake_reason": reason, "wake_payload": payload or {}}


def eng(sim, *replies):
    return CognitionEngine(sim, ScriptedLLM(*replies))


@pytest.mark.asyncio
async def test_threatened_offers_stand_up_and_back_away(sim, world):
    world["character"]["body"]["hunger"] = 10
    world["available_actions"]["action_types"].append("turn_and_run")
    wake(world, "provoked", {
        "actor_id": "den", "actor_name": "Dennis", "verb_phrase": "threatened",
        "reaction_hint": "Your gut reaction: mostly fear.",
        "provocation_type": "threaten", "outcome": "hit", "incident_id": None,
    })
    e = eng(sim, json.dumps({"choice": "stand_up_to_them", "speech": "Don't threaten me."}))
    p = await e.prepare("kim", "provoked")
    assert p.situation.situation.id == "violence.threatened"
    ids = [o.id for o in p.options]
    assert {"stand_up_to_them", "back_away", "back_down"} <= set(ids)
    assert "call_for_help" not in ids  # no incident_id supplied
    rec = await e.decide("kim", "provoked", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "speak" and d["action"]["target"] == "den"


@pytest.mark.asyncio
async def test_threatened_offers_call_911_when_incident_exists(sim, world):
    world["character"]["body"]["hunger"] = 10
    world["available_actions"]["action_types"].append("call_911")
    wake(world, "provoked", {
        "actor_id": "den", "actor_name": "Dennis", "verb_phrase": "threatened",
        "reaction_hint": "Your gut reaction: mostly fear.",
        "provocation_type": "threaten", "outcome": "hit", "incident_id": "inc_9",
    })
    e = eng(sim, json.dumps({"choice": "call_for_help"}))
    p = await e.prepare("kim", "provoked")
    ids = [o.id for o in p.options]
    assert "call_for_help" in ids
    rec = await e.decide("kim", "provoked", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "call_911" and d["action"]["target_id"] == "inc_9"


@pytest.mark.asyncio
async def test_attacked_hit_vs_evaded_framing(sim, world):
    world["character"]["body"]["hunger"] = 10

    wake(world, "provoked", {
        "actor_id": "den", "actor_name": "Dennis", "verb_phrase": "punched",
        "reaction_hint": "Your gut reaction: mostly fear.",
        "provocation_type": "punch", "outcome": "hit", "incident_id": None,
    })
    e = eng(sim, json.dumps({"choice": "run_away"}))
    p = await e.prepare("kim", "provoked")
    assert p.situation.situation.id == "violence.attacked"
    assert "punched you" in p.situation.description

    wake(world, "provoked", {
        "actor_id": "den", "actor_name": "Dennis", "verb_phrase": "punched",
        "reaction_hint": "Your gut reaction: mostly fear.",
        "provocation_type": "punch", "outcome": "evaded", "incident_id": None,
    })
    e2 = eng(sim, json.dumps({"choice": "freeze"}))
    p2 = await e2.prepare("kim", "provoked")
    assert "weren't hit" in p2.situation.description


@pytest.mark.asyncio
async def test_attacked_offers_push_run_freeze_and_confront(sim, world):
    world["character"]["body"]["hunger"] = 10
    world["available_actions"]["action_types"].append("shove")
    world["available_actions"]["action_types"].append("turn_and_run")
    wake(world, "provoked", {
        "actor_id": "den", "actor_name": "Dennis", "verb_phrase": "shoved",
        "reaction_hint": "Your gut reaction: mostly anger.",
        "provocation_type": "shove", "outcome": "hit", "incident_id": None,
    })
    e = eng(sim, json.dumps({"choice": "push_them_away"}))
    p = await e.prepare("kim", "provoked")
    ids = [o.id for o in p.options]
    assert {"push_them_away", "run_away", "freeze", "confront_them"} <= set(ids)
    rec = await e.decide("kim", "provoked", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "shove"


@pytest.mark.asyncio
async def test_witnessed_violence_offers_step_in_and_check_on_them(sim, world):
    world["character"]["body"]["hunger"] = 10
    world["environment"]["visible_people"].append(
        {"id": "mika", "name": "Mika", "distance": 5, "description": "a woman", "activity": None})
    wake(world, "witnessed_violence", {
        "actor_id": "den", "actor_name": "Dennis",
        "target_id": "mika", "target_name": "Mika",
        "action": "punch", "incident_id": None,
    })
    e = eng(sim, json.dumps({"choice": "step_in", "speech": "Hey! Knock it off!"}))
    p = await e.prepare("kim", "witnessed_violence")
    assert p.situation.situation.id == "violence.witnessed_violence"
    assert "Dennis just punch Mika" in p.situation.description
    ids = [o.id for o in p.options]
    assert {"step_in", "check_on_them", "stay_back"} <= set(ids)
    rec = await e.decide("kim", "witnessed_violence", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "speak" and d["action"]["target"] == "den"


@pytest.mark.asyncio
async def test_witnessed_violence_stay_back_always_available():
    from simsland_mw.situations.library import default_registry
    reg = default_registry()
    sit = reg.get("violence.witnessed_violence")
    assert sit.priority == 62
    ids = [o.id for o in sit.options]
    assert "stay_back" in ids
