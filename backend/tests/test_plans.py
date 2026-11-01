"""
A THEN line becomes one intention per step (brain/plans.py). Live (2026-11-01): Susan Moreau's "try to talk to Kathleen
and see if she wants to play, then think about how to actually apologize to Dad and make it right" became ONE "apologize"
intention carrying both plans as its reason.

Run inside the backend container:   python tests/test_plans.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from brain import llm_brain as lb
from brain.plans import intentions_from_plan
from brain import intentions as intents
from brain.agent_loop import process_decision


def person(cid, name, age, sex, hid):
    first, last = name.split()
    return {"id": cid, "name": name, "first_name": first, "family_name": last, "age": age, "sex": sex,
            "age_group": "child" if age < 13 else ("teen" if age < 18 else "adult"), "household_id": hid}


world = {"tick": 5000, "characters": {
    "susan": person("susan", "Susan Moreau", 11, "female", "mor"),
    "steven": person("steven", "Steven Moreau", 31, "male", "mor"),
    "donna": person("donna", "Donna Moreau", 44, "female", "mor"),
    "kathleen": person("kathleen", "Kathleen Okafor", 10, "female", "oka"),
    "robert": person("robert", "Robert Okafor", 41, "male", "oka"),
}, "households": {"mor": {"id": "mor", "members": ["susan", "steven", "donna"]},
                  "oka": {"id": "oka", "members": ["kathleen", "robert"]}}}
susan = world["characters"]["susan"]

LIVE = ("try to talk to Kathleen and see if she wants to play, then think about how to actually apologize to Dad and "
        "make it right.")
got = intentions_from_plan(susan, world, lb._then_steps(LIVE))
check("the live THEN line is two intentions", [i["type"] for i in got] == ["play_with_friend", "apologize"], str(got))
check("... playing, with Kathleen, carrying only the playing step",
      got and got[0]["target_id"] == "kathleen" and got[0]["reason"] == "try to talk to Kathleen and see if she wants to play")
check("... and apologizing, to Dad (her household's man: Steven), carrying only the apology step",
      len(got) > 1 and got[1]["target_id"] == "steven"
      and got[1]["reason"] == "think about how to actually apologize to Dad and make it right", str(got[1:]))
check("the first plan is the more pressing one", got and got[0]["priority"] > got[1]["priority"])

got = intentions_from_plan(susan, world, ["call Kathleen Okafor"])
check("call someone -> call_person, aimed at them", got == [{"type": "call_person", "reason": "call Kathleen Okafor",
                                                           "source": "own_plan", "priority": 40, "category": "social",
                                                           "target_id": "kathleen"}], str(got))
got = intentions_from_plan(susan, world, ["go over to Kathleen's to see her"])
check("visit someone -> visit_person", got and got[0]["type"] == "visit_person" and got[0]["target_id"] == "kathleen")
got = intentions_from_plan(susan, world, ["play the piano"])
check("'play the piano' (nobody named) is not a play date", all(i["type"] != "play_with_friend" for i in got), str(got))
got = intentions_from_plan(world["characters"]["robert"], world, ["apologize to Dad"])
check("an adult's 'Dad' isn't guessed", got and "target_id" not in got[0], str(got))
got = intentions_from_plan(susan, world, ["ponder the meaning of life"])
check("a step that is no activity and names nobody: no intention", got == [], str(got))
got = intentions_from_plan(susan, world, ["take a shower", "take a shower again"])
check("one intention per type", [i["type"] for i in got] == ["take_shower"], str(got))

# ---- through process_decision ------------------------------------------------------------------------------------
intents.set_current_tick(5000)
susan.update(active_intentions=[], memories=[])
decision = lb._to_legacy_decision(lb._parse_compact_envelope("ACTION: wait\nTHEN: " + LIVE), char_id=None)
process_decision(susan, world, decision)
types = sorted(i["type"] for i in susan["active_intentions"])
check("stored on the character as two separate intentions", types == ["apologize", "play_with_friend"], str(types))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
