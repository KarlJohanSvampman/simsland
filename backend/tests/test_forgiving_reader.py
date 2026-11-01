"""
The model's reply is read forgivingly: an action line that is slightly off the format is still an action, not "The reply had
no ACTION line" and a lost turn spent waiting (brain/llm_brain.py::_parse_compact_envelope / _find_loose_action_line).

The broken replies below are real ones from Kathleen Okafor's memory log (2026-11-01, llama3.1).

Run inside the backend container:   python tests/test_forgiving_reader.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from brain import llm_brain as lb

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def action(raw):
    env = lb._parse_compact_envelope(raw)
    return None if env is None else env["action"]


# ---- the real broken replies -------------------------------------------------------------------------------------
a = action("<examine> | the big kitchen cabinet | it's got cookbooks and dishes and other kitchen thin")
check("'<examine> | ...' (no ACTION:, template brackets copied) is an examine",
      a and a["type"] == "examine" and a["target_description"] == "the big kitchen cabinet", str(a))

a = action(" | the kitchen cabinet | for cookbooks, dishes, and other kitchen supplies REMARK:")
check("' | target | ...' (no action word) still acts on the target, REMARK run-on cut off",
      a and a["type"] == "move" and a["target_description"] == "the kitchen cabinet"
      and a["detail"] == "for cookbooks, dishes, and other kitchen supplies", str(a))

a = action("MOVE | to the bathroom to brush my teeth | I need to get rid of this yucky taste")
check("'MOVE | ...' (the action word as the label) is a move",
      a and a["type"] == "move" and a["target_description"] == "to the bathroom to brush my teeth", str(a))

env = lb._parse_compact_envelope("I take a closer look at the kitchen cabinet.\n | the kitchen cabinet")
check("no action word, but the narration says what: examine",
      env and env["action"]["type"] == "examine" and env["narration"] == "I take a closer look at the kitchen cabinet.",
      str(env))

a = action("ACTION: <examine> | the sink")
check("'ACTION: <examine>' -- the brackets are dropped", a and a["type"] == "examine", str(a))
a = action("**Jog to** | Susan Moreau's house")
check("'**Jog to**' -> jog_to", a and a["type"] == "jog_to", str(a))

env = lb._parse_compact_envelope("examine | the fridge\nSAY: Anyone want a snack?\nTHEN: make a sandwich")
check("the other lines still read normally around a loose action line",
      env and env["action"]["type"] == "examine" and env["say"] == "Anyone want a snack?"
      and env["then"] == "make a sandwich", str(env))

# ---- unchanged: the proper format, and what must NOT become an action --------------------------------------------
env = lb._parse_compact_envelope("I look around the kitchen.\nACTION: examine | sink")
check("the proper format reads as before",
      env["action"] == {"type": "examine", "target_description": "sink", "detail": ""}
      and env["narration"] == "I look around the kitchen.", str(env))
check("narration with a '|' that isn't an action stays unreadable",
      lb._parse_compact_envelope("I think | maybe I should wait") is None)
check("a SAY line with a '|' isn't an action", lb._parse_compact_envelope("SAY: left | right") is None)
check("plain prose is still no action", lb._parse_compact_envelope("I examine the bathroom_sink to assess hygiene.") is None)
check("an empty reply is still no action", lb._parse_compact_envelope("") is None)

# ---- all the way to a decision -----------------------------------------------------------------------------------
decision = lb._to_legacy_decision(lb._parse_compact_envelope(
    "<examine> | the big kitchen cabinet | it's got cookbooks"), char_id=None)
check("the forgiving reading gives a real decision, not the fallback wait",
      decision["action"]["type"] == "examine" and not decision["action"].get("fallback"), str(decision["action"]))

# ---- THEN: one intention, from one step ----------------------------------------------------------------------------
live_then = ("try to talk to Kathleen and see if she wants to play, then think about how to actually apologize to Dad "
             "and make it right.")
check("a THEN line is split into its steps",
      lb._then_steps(live_then) == ["try to talk to Kathleen and see if she wants to play",
                                    "think about how to actually apologize to Dad and make it right"],
      str(lb._then_steps(live_then)))
check("'go next door' / 'ask her later' are one step each",
      lb._then_steps("go next door to see Susan") == ["go next door to see Susan"]
      and lb._then_steps("ask her later") == ["ask her later"])
d = lb._to_legacy_decision(lb._parse_compact_envelope("ACTION: wait\nTHEN: " + live_then), char_id=None)
check("the live case: the apology intention carries only the apology step (no playing with Kathleen in it)",
      d["intention"] == {"type": "apologize", "reason": "think about how to actually apologize to Dad and make it right",
                         "priority": 40, "source": "own_plan"}, str(d.get("intention")))
d = lb._to_legacy_decision(lb._parse_compact_envelope("ACTION: wait\nTHEN: take a shower, then go to sleep"), char_id=None)
check("only one intention: the first step that is a real activity", d["intention"]["type"] == "take_shower"
      and d["intention"]["reason"] == "take a shower", str(d.get("intention")))
d = lb._to_legacy_decision(lb._parse_compact_envelope("ACTION: wait\nTHEN: ponder life"), char_id=None)
check("a step that is no activity gives no intention", not d.get("intention"))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
