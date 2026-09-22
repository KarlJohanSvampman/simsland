import json

import pytest

from conftest import ScriptedLLM
from simsland_mw.cognition.engine import CognitionEngine
from simsland_mw.simulation.mock import MockSimClient, dinner_world


def wake(w, reason, payload=None):
    w["meta"]["cognition"] = {"wake_reason": reason, "wake_payload": payload or {}}


def eng(sim, *replies):
    return CognitionEngine(sim, ScriptedLLM(*replies))


@pytest.mark.asyncio
async def test_hunger_threshold_selects_situation_and_reports_gaps(sim):
    p = await eng(sim).prepare("kim", "urgent_need")
    assert p.situation.situation.id == "need.hunger.noticeable"
    ids = [o.id for o in p.options]
    assert "eat_something_at_home" in ids and "keep_going_for_now" in ids
    assert "order_food_delivery" not in ids and "buy_food_out" not in ids   # never offered
    reasons = dict(p.situation.unresolved)
    assert "food_delivery" in reasons["order_food_delivery"]
    assert "WHAT'S HAPPENING" in p.messages[1]["content"]


@pytest.mark.asyncio
async def test_threshold_fires_once_until_rearmed(sim, world):
    e = eng(sim)
    first = await e.prepare("kim", "urgent_need", commit=True)
    assert first.situation and first.situation.situation.id == "need.hunger.noticeable"
    again = await e.prepare("kim", "urgent_need", commit=True)
    assert not again.situation or again.situation.situation.id != "need.hunger.noticeable"
    world["character"]["body"]["hunger"] = 10          # ate
    await e.prepare("kim", None, commit=True)
    world["character"]["body"]["hunger"] = 80          # hungry again (past cooldown)
    world["tick"] = world["meta"]["tick"] = 1000 + 7200
    third = await e.prepare("kim", "urgent_need", commit=True)
    assert third.situation and third.situation.situation.id == "need.hunger.noticeable"


@pytest.mark.asyncio
async def test_preview_does_not_consume_the_trigger(sim):
    e = eng(sim)
    await e.prepare("kim", "urgent_need")
    again = await e.prepare("kim", "urgent_need")
    assert again.situation.situation.id == "need.hunger.noticeable"


@pytest.mark.asyncio
async def test_noop_option_sends_no_action_but_still_completes_the_wake(sim):
    e = eng(sim, json.dumps({"choice": "keep_going_for_now", "thought": "later"}))
    rec = await e.decide("kim", "urgent_need", dry_run=False)
    assert rec.situation_id == "need.hunger.noticeable"
    assert sim.executed[0]["decision"]["action"] is None and rec.executed
    assert rec.thought == "later"
    assert sim.executed[0]["decision"]["thought"] is None      # private: never persisted by Simsland


@pytest.mark.asyncio
async def test_question_uses_model_speech_and_goes_through_speak(sim, world):
    wake(world, "heard_speech", {"listener_id": "kim", "speaker_id": "den", "speaker_name": "Dennis",
                                 "utterance": "Did you buy the groceries?"})
    world["character"]["body"]["hunger"] = 10
    e = eng(sim, json.dumps({"choice": "answer_honestly", "speech": "Not yet, sorry."}))
    p = await e.prepare("kim", "heard_speech")
    assert p.situation.situation.id == "conversation.question"
    assert "Dennis just asked you" in p.messages[1]["content"]
    assert '"speech"' in p.messages[0]["content"]
    rec = await e.decide("kim", "heard_speech", dry_run=False)
    d = sim.executed[0]["decision"]
    assert d["action"]["type"] == "speak" and d["action"]["target"] == "den"
    assert d["speech"]["utterance"] == "Not yet, sorry." and rec.speech == "Not yet, sorry."


@pytest.mark.asyncio
async def test_speech_is_ignored_for_options_that_do_not_speak(sim):
    e = eng(sim, json.dumps({"choice": "keep_going_for_now", "speech": "I hereby declare war"}))
    await e.decide("kim", "urgent_need", dry_run=False)
    assert sim.executed[0]["decision"]["speech"] is None


@pytest.mark.asyncio
async def test_non_question_speech_is_not_a_question_situation(sim, world):
    wake(world, "heard_speech", {"speaker_id": "den", "utterance": "It's cold."})
    world["character"]["body"]["hunger"] = 10
    p = await eng(sim).prepare("kim", "heard_speech")
    assert not p.situation or p.situation.situation.id != "conversation.question"


@pytest.mark.asyncio
async def test_character_approaches_uses_the_person_who_arrived(sim, world):
    wake(world, "person_entered_view", {"observer_id": "kim", "subject_id": "den", "subject_name": "Dennis"})
    world["character"]["body"]["hunger"] = 10
    p = await eng(sim).prepare("kim", "person_entered_view")
    assert p.situation.situation.id == "social.character_approaches"
    ids = [o.id for o in p.options]
    assert "greet_them" in ids and "avoid_them" not in ids
    assert [o for o in p.options if o.id == "greet_them"][0].outcome["target"] == "den"


@pytest.mark.asyncio
async def test_messy_room_and_quiet_moment(sim, world):
    world["character"]["body"]["hunger"] = 10
    world["meta"]["cognition"] = {"wake_reason": "idle", "wake_payload": {}}
    world["character"]["active_intentions"] = []
    world["available_actions"]["action_types"] += ["clean_floors", "dust_and_wipe", "look_around"]
    world["environment"]["room_cleanliness"] = 15
    e = eng(sim)
    p = await e.prepare("kim", "idle", commit=True)
    assert p.situation.situation.id == "environment.messy_room"
    assert {"sweep_and_scrub_the_floor", "dust_and_wipe_surfaces"} <= {o.id for o in p.options}
    world["environment"]["room_cleanliness"] = 90
    q = await e.prepare("kim", "idle", commit=True)
    assert q.situation.situation.id == "cognition.quiet_moment"
    assert "look_around_the_place" in [o.id for o in q.options]


@pytest.mark.asyncio
async def test_falls_back_to_generic_menu_when_nothing_fires(sim, world):
    world["character"]["body"]["hunger"] = 10
    world["meta"]["cognition"] = {"wake_reason": "noise", "wake_payload": {}}
    p = await eng(sim).prepare("kim", "noise")
    assert p.situation is None and p.options


def test_capability_report_lists_every_gap_with_its_situations():
    from simsland_mw.situations.library import default_registry
    rep = {r["capability"]: r["needed_by"] for r in default_registry().capability_report()}
    assert {"food_delivery", "food_purchase", "avoid_character", "room_navigation",
            "partial_task_progress", "leisure_activity_selection"} <= set(rep)
    assert "need.hunger.noticeable/order_food_delivery" in rep["food_delivery"]


def test_every_situation_has_at_least_4_seeds():
    from simsland_mw.situations.library import default_registry
    for s in default_registry().all():
        assert len(s.options) >= 4 or s.dynamic_options, s.id


@pytest.mark.asyncio
async def test_idle_only_character_gets_real_things_to_do_and_never_a_bare_wait(sim, world):
    world["character"]["body"].update({"hunger": 0, "fatigue": 0})
    world["environment"]["visible_people"] = []
    world["character"]["expectations"] = {}
    world["character"]["grievances"] = []
    world["character"]["active_intentions"] = [{"type": "x", "priority": 90, "reason": "busy"}]
    world["meta"]["cognition"] = {"wake_reason": "idle", "wake_payload": {}}
    world["available_actions"]["action_types"] += ["examine", "practice_juggling"]
    p = await eng(sim).prepare("kim", "idle")
    assert p.situation.situation.id == "cognition.quiet_moment"
    assert len(p.options) <= 6 and "sit_quietly" in [o.id for o in p.options]
    assert all((o.outcome or {}).get("type") != "wait" for o in p.options)
    assert all((o.outcome or {}).get("type") != "interact" or o.outcome.get("target") for o in p.options)


@pytest.mark.asyncio
async def test_does_not_restart_the_interaction_already_in_progress(sim, world):
    world["character"]["activity"] = {"type": "interact", "target_id": "prop_fridge",
                                      "interaction": "open_fridge", "phase": "using"}
    p = await eng(sim).prepare("kim", "urgent_need")
    assert "eat_something_at_home" not in [o.id for o in p.options]


@pytest.mark.asyncio
async def test_executor_refuses_targetless_interact_and_conditionless_wait(sim):
    from simsland_mw.decisions.executor import check_action
    assert check_action({"type": "interact"}) == ["interact without a target"]
    assert check_action({"type": "wait"}) == ["wait without a condition"]
    assert check_action({"type": "wait", "waiting_for": {"kind": "person", "ref": "den"}}) == []
    assert check_action({"type": "interact", "target": "p"}) == []


def _agenda_world(world, age=34):
    world["character"]["age"] = age
    world["character"]["body"].update({"hunger": 10, "fatigue": 0})
    world["environment"]["visible_people"] = []
    world["meta"]["cognition"] = {"wake_reason": "idle", "wake_payload": {}}
    world["character"]["emotion"] = "anxious"
    world["character"]["active_intentions"] = [
        {"type": "creative_outlet", "priority": 40, "reason": "You want a creative outlet."},
        {"type": "expectation:make_dinner", "priority": 80, "reason": "Dinner is due."},
        {"type": "outdoor_time", "priority": 70, "reason": "You want fresh air."},
        {"type": "eat_food", "priority": 60, "reason": "You're hungry."},
    ]
    world["available_actions"]["action_types"] += ["make_drawing"]
    world["environment"]["visible_props"][0]["interactions"].append("cook_meal")


@pytest.mark.asyncio
async def test_idle_agenda_orders_options_by_priority_and_reports_gaps(sim, world):
    _agenda_world(world)
    p = await eng(sim).prepare("kim", "idle")
    assert p.situation.situation.id == "cognition.idle_agenda"
    ids = [o.id for o in p.options]
    assert ids.index("agenda_expectation_make_dinner") < ids.index("agenda_eat_food") < ids.index("agenda_creative_outlet")
    assert ids[-1] == "just_relax_for_a_while"
    assert dict(p.situation.unresolved)["agenda_outdoor_time"].endswith("outdoor_activity")
    text = p.messages[1]["content"]
    assert "feeling anxious" in text and text.index("Dinner is due") < text.index("You're hungry")


@pytest.mark.asyncio
async def test_options_are_age_aware(sim, world):
    _agenda_world(world, age=6)
    p = await eng(sim).prepare("kim", "idle")
    ids = [o.id for o in p.options]
    assert "agenda_expectation_make_dinner" not in ids
    assert "not for someone aged 6" in dict(p.situation.unresolved)["agenda_expectation_make_dinner"]
    world["character"]["body"]["hunger"] = 80
    q = await eng(sim).prepare("kim", "urgent_need")
    assert "cook_a_proper_meal" not in [o.id for o in q.options]


@pytest.mark.asyncio
async def test_bedtime_offers_sleep_regardless_of_fatigue(sim, world):
    world["character"]["body"].update({"fatigue": 20, "hunger": 10})   # nowhere near the 60 threshold
    world["character"]["active_schedule_block"] = {"activity": "sleep", "source": "schedule"}
    world["meta"]["cognition"] = {"wake_reason": "schedule_block", "wake_payload": {}}
    p = await eng(sim).prepare("kim", "schedule_block")
    assert p.situation.situation.id == "need.energy.tired"
    assert "lie_down_and_sleep" in [o.id for o in p.options]
    assert "bedtime" in p.situation.description


@pytest.mark.asyncio
async def test_non_sleep_schedule_block_does_not_trigger_tired(sim, world):
    world["character"]["body"].update({"fatigue": 20, "hunger": 10})
    world["character"]["active_schedule_block"] = {"activity": "work", "source": "schedule"}
    world["meta"]["cognition"] = {"wake_reason": "schedule_block", "wake_payload": {}}
    p = await eng(sim).prepare("kim", "schedule_block")
    assert not p.situation or p.situation.situation.id != "need.energy.tired"
