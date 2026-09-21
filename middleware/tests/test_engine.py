import json

import pytest

from conftest import ScriptedLLM
from simsland_mw.cognition.engine import CognitionEngine
from simsland_mw.situations import SituationRegistry


def engine(sim, llm):
    return CognitionEngine(sim, llm, situations=SituationRegistry())  # legacy menu: engine mechanics only


async def test_happy_path_executes_the_chosen_outcome(sim):
    llm = ScriptedLLM('{"choice": "eat_at_home"}')
    rec = await engine(sim, llm).decide("kim", "urgent_need", dry_run=False)
    assert rec.executed and rec.choice_id == "eat_at_home" and rec.via == "id"
    sent = sim.executed[0]
    assert sent["char_id"] == "kim" and sent["wake_reason"] == "urgent_need"
    assert sent["decision"]["action"]["target"] == "prop_fridge"
    assert sent["decision"]["thought"] is None      # middleware never invents a memory
    assert rec.profile == "needs"                    # urgent need -> smaller prompt


async def test_llm_sees_descriptions_only_and_is_constrained_to_ids(sim):
    llm = ScriptedLLM('{"choice": "do_nothing_for_now"}')
    await engine(sim, llm).decide("kim", dry_run=True)
    call = llm.calls[0]
    prompt = call["messages"][1]["content"]
    assert "Look through the refrigerator" in prompt
    assert "prop_fridge" not in prompt and "open_fridge" not in prompt   # private mapping stays private
    assert "eat_at_home" in call["option_ids"]


async def test_dry_run_never_touches_the_simulation(sim):
    rec = await engine(sim, ScriptedLLM('{"choice": "eat_at_home"}')).decide("kim", dry_run=True)
    assert not rec.executed and sim.executed == []
    assert rec.action["type"] == "interact"


async def test_invalid_reply_is_retried_once_with_a_correction(sim):
    llm = ScriptedLLM('{"choice": "steal_money_from_bank"}', '{"choice": "ask_dennis_about_buy_groceries"}')
    rec = await engine(sim, llm).decide("kim", dry_run=False)
    assert rec.choice_id == "ask_dennis_about_buy_groceries" and not rec.fallback
    assert len(rec.rejections) == 1 and len(llm.calls) == 2
    assert "rejected" in llm.calls[1]["messages"][-1]["content"]
    assert sim.executed[0]["decision"]["speech"]["utterance"] == "Dennis, did you buy groceries?"


async def test_model_that_never_complies_degrades_to_best_rule_option(sim):
    llm = ScriptedLLM("nonsense", '{"choice": 12345}')
    rec = await engine(sim, llm).decide("kim", dry_run=False)
    assert rec.fallback and rec.via == "fallback" and rec.choice_id == "eat_at_home"
    assert len(sim.executed) == 1


async def test_single_option_skips_the_model_call(sim):
    sim.world["character"]["body"].update({"hunger": 0, "fatigue": 0})
    sim.world["environment"]["visible_people"] = []
    sim.world["character"]["expectations"] = {}
    sim.world["character"]["grievances"] = []
    sim.world["character"]["active_intentions"] = []
    llm = ScriptedLLM()
    rec = await engine(sim, llm).decide("kim", dry_run=False)
    assert rec.via == "only_option" and rec.choice_id == "do_nothing_for_now" and llm.calls == []


async def test_session_remembers_choices_for_next_prompt(sim):
    eng = engine(sim, ScriptedLLM('{"choice": "ask_dennis_about_buy_groceries"}', '{"choice": "do_nothing_for_now"}'))
    await eng.decide("kim", dry_run=False)
    p = await eng.prepare("kim")
    assert "Earlier you decided to: ask Dennis about it" in p.messages[1]["content"]
    assert eng.sessions.get("kim").to_dict()["recent_choices"][0]["option_id"] == "ask_dennis_about_buy_groceries"


async def test_simsland_rejecting_the_action_is_reported_not_hidden(sim):
    sim.invalid_action = {"type": "interact"}
    rec = await engine(sim, ScriptedLLM('{"choice": "eat_at_home"}')).decide("kim", dry_run=False)
    assert rec.simsland_response["invalid_action"] == {"type": "interact"}


async def test_partial_data_failure_still_produces_a_decision(sim):
    class Flaky(type(sim)):
        async def snapshot(self, char_id, sections):
            if "household" in set(sections):
                raise RuntimeError("household endpoint down")
            return await super().snapshot(char_id, sections)

    flaky = Flaky(sim.world)
    rec = await engine(flaky, ScriptedLLM('{"choice": "eat_at_home"}')).decide("kim", dry_run=True)
    assert "household.members" in rec.errors and rec.choice_id == "eat_at_home"


async def test_missing_identity_aborts_rather_than_guessing(sim):
    class Down(type(sim)):
        async def snapshot(self, char_id, sections):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="cannot decide"):
        await engine(Down(sim.world), ScriptedLLM()).decide("kim", dry_run=True)
