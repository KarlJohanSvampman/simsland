import json

import pytest

from conftest import ScriptedLLM
from simsland_mw.cognition.engine import CognitionEngine


def wake(w, reason, payload=None):
    w["meta"]["cognition"] = {"wake_reason": reason, "wake_payload": payload or {}}


def eng(sim, *replies):
    return CognitionEngine(sim, ScriptedLLM(*replies))


@pytest.mark.asyncio
async def test_child_placement_relative_offers_ask_where_parent_is(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "child_placement", {
        "placement_type": "relative",
        "caregiver_id": "den", "caregiver_name": "Dennis",
        "placed_with_id": "den", "placed_with_name": "Dennis",
    })
    e = eng(sim, json.dumps({"choice": "ask_where_parent_is",
                              "speech": "When is my parent coming back?"}))
    p = await e.prepare("kim", "child_placement")
    assert p.situation.situation.id == "legal.child_placement"
    assert "gone to stay with Dennis" in p.situation.description
    ids = [o.id for o in p.options]
    assert {"ask_where_parent_is", "stay_with_caretaker", "ask_for_parent", "stay_quiet"} <= set(ids)
    rec = await e.decide("kim", "child_placement", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "speak" and d["action"]["target"] == "den"


@pytest.mark.asyncio
async def test_child_placement_cps_has_no_perceivable_target(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "child_placement", {
        "placement_type": "cps",
        "caregiver_id": "den", "caregiver_name": "Dennis",
        "placed_with_id": None, "placed_with_name": "Child Protective Services",
    })
    e = eng(sim, json.dumps({"choice": "stay_quiet"}))
    p = await e.prepare("kim", "child_placement")
    assert "Child Protective Services" in p.situation.description
    ids = [o.id for o in p.options]
    assert "ask_where_parent_is" not in ids
    assert "stay_quiet" in ids


@pytest.mark.asyncio
async def test_took_in_relative_child_offers_welcome(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "took_in_relative_child", {
        "child_id": "den", "child_name": "Dennis Jr.",
        "caregiver_id": "someone", "caregiver_name": "their dad",
    })
    e = eng(sim, json.dumps({"choice": "welcome_them",
                              "speech": "You're safe here."}))
    p = await e.prepare("kim", "took_in_relative_child")
    assert p.situation.situation.id == "legal.took_in_relative_child"
    ids = [o.id for o in p.options]
    assert {"welcome_them", "figure_out_logistics", "feel_overwhelmed"} <= set(ids)
    rec = await e.decide("kim", "took_in_relative_child", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "speak" and d["action"]["target"] == "den"


@pytest.mark.asyncio
async def test_reunified_with_caregiver_offers_express_relief(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "reunified_with_caregiver", {
        "caregiver_id": "den", "caregiver_name": "Dennis",
    })
    e = eng(sim, json.dumps({"choice": "express_relief", "speech": "I'm glad to be home."}))
    p = await e.prepare("kim", "reunified_with_caregiver")
    assert p.situation.situation.id == "legal.reunified_with_caregiver"
    assert "Dennis is able to" in p.situation.description
    ids = [o.id for o in p.options]
    assert {"express_relief", "settle_back_in"} <= set(ids)
    rec = await e.decide("kim", "reunified_with_caregiver", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "speak" and d["action"]["target"] == "den"


@pytest.mark.asyncio
async def test_legal_situations_registered_with_expected_priorities():
    from simsland_mw.situations.library import default_registry
    reg = default_registry()
    assert reg.get("legal.child_placement").priority == 80
    assert reg.get("legal.took_in_relative_child").priority == 68
    assert reg.get("legal.reunified_with_caregiver").priority == 60
