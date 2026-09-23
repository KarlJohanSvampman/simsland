import json

import pytest

from conftest import ScriptedLLM
from simsland_mw.cognition.engine import CognitionEngine


def wake(w, reason, payload=None):
    w["meta"]["cognition"] = {"wake_reason": reason, "wake_payload": payload or {}}


def eng(sim, *replies):
    return CognitionEngine(sim, ScriptedLLM(*replies))


@pytest.mark.asyncio
async def test_bill_trouble_fires_and_offers_real_discussion(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "household_bill_trouble", {"amount_owed": 340.0, "household_wealth": 12.0})
    e = eng(sim, json.dumps({"choice": "discuss_with_household",
                            "speech": "We need to talk about money -- we're behind on bills."}))
    p = await e.prepare("kim", "household_bill_trouble")
    assert p.situation.situation.id == "household.bill_trouble"
    assert "340" in p.situation.description
    ids = [o.id for o in p.options]
    assert "discuss_with_household" in ids
    reasons = dict(p.situation.unresolved)
    assert "ask_for_help" in reasons
    rec = await e.decide("kim", "household_bill_trouble", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "speak" and d["action"]["target"] == "den"


@pytest.mark.asyncio
async def test_plant_needs_water_offers_real_watering_action(sim, world):
    world["character"]["body"]["hunger"] = 10
    world["available_actions"]["action_types"].append("water_plants")
    e = eng(sim, json.dumps({"choice": "water_it"}))
    wake(world, "plant_needs_water", {"plant_id": "plant_1", "plant_name": "the tomato plant", "moisture": 15})
    p = await e.prepare("kim", "plant_needs_water")
    assert p.situation.situation.id == "household.plant_needs_water"
    ids = [o.id for o in p.options]
    assert {"water_it", "water_all_the_plants_while_im_at_it", "leave_it_for_now"} <= set(ids)
    rec = await e.decide("kim", "plant_needs_water", dry_run=False)
    assert sim.executed[0]["decision"]["action"]["type"] == "water_plants"


@pytest.mark.asyncio
async def test_appliance_broken_fires_with_real_description():
    from simsland_mw.situations.library import default_registry
    reg = default_registry()
    sit = reg.get("household.appliance_broken")
    assert sit.priority == 47
    assert len(sit.options) >= 2


@pytest.mark.asyncio
async def test_intimate_object_discovered_offers_mention_when_owner_co_present(sim, world):
    world["character"]["body"]["hunger"] = 10
    e = eng(sim, json.dumps({"choice": "pretend_not_to_notice"}))
    wake(world, "intimate_object_discovered", {"owner_id": "den", "owner_name": "Dennis"})
    p = await e.prepare("kim", "intimate_object_discovered")
    assert p.situation.situation.id == "household.intimate_object_discovered"
    ids = [o.id for o in p.options]
    assert {"pretend_not_to_notice", "put_it_back_and_forget_it", "mention_it_to_them"} <= set(ids)
    reasons = dict(p.situation.unresolved)
    assert "tell_someone_else" in reasons
