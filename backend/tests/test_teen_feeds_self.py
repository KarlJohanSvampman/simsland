"""
A teenager doesn't ask leave to feed themselves (brain/plans.py::_asks_leave_to_eat). Live (2026-11): Carol (14) kept
meaning to "ask Brenda for permission to make food"; the THEN line became a visit to Brenda, who didn't answer, and
Carol stayed hungry. For anyone old enough to cook (systems/food_habits.can_cook, 13+) that plan is a plan to eat; a
younger child still goes and asks. The teen prompt says so too (definitions.json, the teen cognition description).

Run inside the backend container:   python tests/test_teen_feeds_self.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from house_world import make_world
from brain.plans import intentions_from_plan
from brain.llm_brain import _then_steps

w = make_world()
w["tick"] = 20000
k, r = w["characters"]["kathleen"], w["characters"]["robert"]
r.update(age=42, sex="male")


def plan(line):
    return [(i.get("type"), i.get("target_id")) for i in intentions_from_plan(k, w, _then_steps(line))]


k.update(age=14, age_group="teen", active_intentions=[])
for line in ("ask Robert for permission to make food", "ask Dad if I can make a sandwich",
             "ask Robert if I can cook something"):
    check(f"14: {line!r} -> eat", plan(line) == [("eat_food", None)], str(plan(line)))
check("14: other asks still go to the person", plan("ask Dad if I can go to the park") == [("visit_person", "robert")])
check("14: the rest of the plan stays", plan("ask Robert for permission to make food, then play with Susan")
      == [("eat_food", None), ("play_with_friend", "susan")])
k["active_intentions"] = [{"type": "eat_food", "reason": "very_hungry"}]
check("14: already meaning to eat: nothing added", plan("ask Robert if I can make a snack") == [])

k.update(age=10, age_group="child", active_intentions=[])
check("10: a child still asks", plan("ask Dad if I can make a sandwich") == [("visit_person", "robert")])

check("the teen prompt says they can make themselves food",
      "make yourself something to eat, or cook, without asking anyone first"
      in open("/data/simulations/default/definitions.json", encoding="utf-8").read())

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
