import json

import pytest

from conftest import ScriptedLLM
from simsland_mw.cognition.engine import CognitionEngine


def wake(w, reason, payload=None):
    w["meta"]["cognition"] = {"wake_reason": reason, "wake_payload": payload or {}}


def eng(sim, *replies):
    return CognitionEngine(sim, ScriptedLLM(*replies))


@pytest.mark.asyncio
async def test_contract_violated_offers_real_speech_options_when_violator_nearby(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "contract_violated", {"violator_id": "den", "violator_name": "Dennis",
                                      "commitment": "buy groceries", "contract_id": "contract_1"})
    e = eng(sim, json.dumps({"choice": "confront_them", "speech": "Where are the groceries?"}))
    p = await e.prepare("kim", "contract_violated")
    assert p.situation.situation.id == "contract.violated"
    assert "Dennis just missed" in p.situation.description
    assert "buy groceries" in p.situation.description
    ids = [o.id for o in p.options]
    assert {"confront_them", "remind_them", "forgive_them", "let_it_go"} <= set(ids)
    rec = await e.decide("kim", "contract_violated", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "speak" and d["action"]["target"] == "den"
    assert d["speech"]["speech_act"] == "challenge"


@pytest.mark.asyncio
async def test_contract_violated_still_fires_without_violator_nearby(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "contract_violated", {"violator_id": "someone_offscreen", "violator_name": "A stranger",
                                      "commitment": "call every Sunday", "contract_id": "contract_2"})
    p = await eng(sim).prepare("kim", "contract_violated")
    assert p.situation.situation.id == "contract.violated"
    ids = [o.id for o in p.options]
    assert ids == ["let_it_go"]   # only the always-available option resolves


@pytest.mark.asyncio
async def test_contract_violated_names_the_renegotiation_gap(sim, world):
    world["character"]["body"]["hunger"] = 10
    wake(world, "contract_violated", {"violator_id": "den", "violator_name": "Dennis",
                                      "commitment": "buy groceries", "contract_id": "contract_1"})
    p = await eng(sim).prepare("kim", "contract_violated")
    reasons = dict(p.situation.unresolved)
    assert "negotiate_contract_not_offered" in reasons["propose_renegotiation"]
