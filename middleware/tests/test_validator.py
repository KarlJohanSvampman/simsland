import pytest

from simsland_mw.decisions.options import Option
from simsland_mw.decisions.validator import ChoiceRejected, parse_choice

OPTS = [Option("eat_at_home", "Eat.", {"type": "wait"}), Option("ask_den", "Ask.", {"type": "wait"}),
        Option("wait", "Wait.", {"type": "wait"})]


def ok(raw):
    return parse_choice(raw, OPTS)


def test_accepts_id_index_and_numeric_string():
    assert ok('{"choice": "ask_den"}').option.id == "ask_den"
    assert ok('{"choice": 3}').option.id == "wait" and ok('{"choice": 3}').via == "index"
    assert ok('{"choice": "2"}').option.id == "ask_den"
    assert ok('{"choice": " EAT_AT_HOME "}').option.id == "eat_at_home"


def test_accepts_fenced_or_chatty_json():
    assert ok('```json\n{"choice": "wait"}\n```').option.id == "wait"
    assert ok('Sure! {"choice": "wait"} hope that helps').option.id == "wait"


def test_thought_is_kept_and_bounded():
    c = ok('{"choice": "wait", "thought": "' + "x" * 1000 + '"}')
    assert len(c.thought) == 300


@pytest.mark.parametrize("raw", [
    '{"choice": 999999}',                       # out of range
    '{"choice": 0}',
    '{"choice": -1}',
    '{"choice": 1.5}',
    '{"choice": true}',
    '{"choice": null}',
    '{"choice": "steal_money_from_bank"}',      # not offered
    '{"action": "steal_money_from_bank"}',      # invented capability, no choice field
    '{"choice": ["wait"]}',
    '["wait"]',
    'I think I will wait',
    '',
])
def test_rejects_everything_that_is_not_an_offered_option(raw):
    with pytest.raises(ChoiceRejected):
        ok(raw)
