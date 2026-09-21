from simsland_mw.data.registry import build_default_registry
from simsland_mw.data.resolver import Resolver
from simsland_mw.cognition import decisions as prompts
from simsland_mw.decisions.options import OptionGenerator


async def _options(sim, mutate=None):
    if mutate:
        mutate(sim.world)
    res = await Resolver(build_default_registry()).resolve(prompts.PROFILES["general"], sim, "kim")
    return OptionGenerator().generate(res)


def _ids(opts):
    return [o.id for o in opts]


async def test_dinner_scenario_offers_the_expected_menu(sim):
    ids = _ids(await _options(sim))
    assert ids[0] == "eat_at_home"
    assert {"ask_den_about_buy_groceries", "sit_and_rest", "tell_den_frustrated", "wait"} <= set(ids)


async def test_option_outcomes_map_to_real_simsland_actions(sim):
    by_id = {o.id: o for o in await _options(sim)}
    assert by_id["eat_at_home"].outcome == {"type": "interact", "target": "prop_fridge",
                                            "interaction": "open_fridge"}
    ask = by_id["ask_den_about_buy_groceries"]
    assert ask.outcome["type"] == "speak" and ask.outcome["target"] == "den"
    assert ask.outcome["utterance"] == "Dennis, did you buy groceries?"
    assert ask.speech["speech_act"] == "ask"


async def test_public_view_hides_the_outcome(sim):
    for o in await _options(sim):
        assert set(o.public()) == {"id", "description"}


async def test_options_gated_by_what_simsland_says_is_possible(sim):
    def no_interact(w):
        w["available_actions"]["action_types"].remove("interact")
        w["available_actions"]["action_types"].remove("speak")
    ids = _ids(await _options(sim, no_interact))
    assert "eat_at_home" not in ids and not any(i.startswith("ask_") for i in ids)
    assert "wait" in ids


async def test_no_food_source_no_eat_option(sim):
    def no_fridge(w):
        w["environment"]["visible_props"] = [p for p in w["environment"]["visible_props"]
                                             if p["id"] != "prop_fridge"]
    assert "eat_at_home" not in _ids(await _options(sim, no_fridge))


async def test_only_blamed_and_present_people_get_confronted(sim):
    def dennis_left(w):
        w["environment"]["visible_people"] = []
    ids = _ids(await _options(sim, dennis_left))
    assert not any("den" in i for i in ids)


async def test_exhaustion_offers_sleep(sim):
    def exhausted(w):
        w["character"]["body"]["fatigue"] = 88
    by_id = {o.id: o for o in await _options(sim, exhausted)}
    assert by_id["go_to_sleep"].outcome == {"type": "sleep", "target": "prop_sofa"}


async def test_wait_is_always_available_and_ids_are_unique(sim):
    opts = await _options(sim)
    assert "wait" in _ids(opts) and len(set(_ids(opts))) == len(opts)


async def test_custom_rule_extends_generator_without_touching_others(sim):
    from simsland_mw.decisions.options import DEFAULT_RULES, Option
    res = await Resolver(build_default_registry()).resolve(prompts.PROFILES["general"], sim, "kim")
    extra = lambda dc: [Option("order_pizza", "Order a pizza.", {"type": "wait"}, priority=99)]
    opts = OptionGenerator([*DEFAULT_RULES, extra]).generate(res)
    assert opts[0].id == "order_pizza"
