"""
Pressing intentions: check-ins that record what the character was doing, the "why am I not doing this?" question in the
prompt, and a parent who feeds or reminds a child without waiting for the model (systems/doing.py, brain/intentions.py,
brain/context_builder.py::_sec_pressing_intentions, systems/child_care.py::tend_child).

Run inside the backend container:   python tests/test_pressing_intentions.py
(the last section runs the seeded simulation, see tests/determinism.py)
"""

import os
import sys
from unittest import mock

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
import brain.agent_loop  # noqa: F401
from brain import intentions as it
from brain.context_builder import _sec_pressing_intentions
from systems import child_care as cc
from systems.doing import describe_doing

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid, name, age=36, **extra):
    d = {"id": cid, "name": name, "age": age, "traits": [], "memories": [], "relationships": {}, "active_intentions": [], "alive": True,
         "household_id": "hh", "building_id": "b1", "room_id": "b1:kitchen_0", "body": {"hunger": 20}}
    d.update(extra)
    return d


def home(tick=100000):
    mum, dad, kid = person("mum", "Anna Lindqvist"), person("dad", "Erik Lindqvist"), person("kid", "Oskar Lindqvist", 6, age_group="child")
    w = {"tick": tick, "characters": {c["id"]: c for c in (mum, dad, kid)}, "households": {"hh": {"id": "hh", "members": ["mum", "dad", "kid"]}},
         "calendar": {"hour": 12, "minute": 0}}
    return w, mum, dad, kid


# ---- what are they doing ---------------------------------------------------------------------------------------------------------
w, mum, dad, kid = home()
check("nothing in particular, in a room", describe_doing(mum, w) == "doing nothing in particular in the kitchen 0", describe_doing(mum, w))
mum["activity"] = {"type": "cook_recipe", "anchor_name": "kitchen_counter"}
check("an activity, with where", describe_doing(mum, w) == "cooking at the kitchen counter", describe_doing(mum, w))
mum["activity"] = {"type": "socialize", "target_id": "dad"}
check("talking with someone", describe_doing(mum, w) == "talking with Erik Lindqvist")
mum["activity"] = {"type": "sleep"}
check("asleep", describe_doing(mum, w) == "asleep")
mum["activity"] = None
mum["off_grid"], mum["off_grid_reason"] = True, "cafe"
check("away", describe_doing(mum, w) == "away (cafe)")
mum["off_grid"] = False
mum["is_moving"] = True
check("walking", describe_doing(mum, w) == "walking somewhere")
mum["is_moving"] = False

# ---- check-ins -----------------------------------------------------------------------------------------------------------------------
w, mum, dad, kid = home()
it.add_intention(mum, {"type": "feed_child_kid", "category": "health", "priority": 85, "reason": "Oskar is hungry", "child_id": "kid", "created_at": w["tick"]})
i = mum["active_intentions"][0]
check("a new intention has no check-ins yet", not i.get("checkins") and i["stage"] == 0)
mum["activity"] = {"type": "relax"}
w["tick"] = i["deadline_tick"] + 1
it.check_intention_deadlines(mum, w)
check("when it goes unanswered past its deadline it gets more urgent", i["stage"] == 1 and i["priority"] > 85)
check("and notes what the character was doing at that check-in", i["doing_at_checkin"] == "relaxing" and i["checkins"][-1]["doing"] == "relaxing", str(i.get("checkins")))
check("with the stage and the time", i["checkins"][-1]["stage"] == 1 and i["checkins"][-1]["tick"] == w["tick"])
mum["activity"] = {"type": "socialize", "target_id": "dad"}
w["tick"] = i["deadline_tick"] + 1
it.check_intention_deadlines(mum, w)
check("the next check-in notes what they were doing THEN", i["stage"] == 2 and i["doing_at_checkin"] == "talking with Erik Lindqvist" and len(i["checkins"]) == 2)
for _ in range(8):
    w["tick"] = i["deadline_tick"] + 1
    it.check_intention_deadlines(mum, w)
check("only the last few are kept", len(i["checkins"]) == it.CHECKINS_KEPT)
it.add_intention(mum, {"type": "feed_child_kid", "category": "health", "priority": 85, "reason": "Oskar is hungry", "child_id": "kid"})
again = mum["active_intentions"][0]
check("a refresh of the same intention keeps its history", again["stage"] == i["stage"] and again.get("checkins") and again.get("doing_at_checkin"))
it.add_intention(mum, {"type": "expectation:make_dinner", "category": "schedule", "priority": 50})
w["tick"] += 10 ** 7
it.check_intention_deadlines(mum, w)
exp = next(x for x in mum["active_intentions"] if x["type"] == "expectation:make_dinner")
check("expectations are left to their own system", not exp.get("checkins"))

# ---- the question in the prompt --------------------------------------------------------------------------------------------------------
w, mum, dad, kid = home()
it.add_intention(mum, {"type": "feed_child_kid", "category": "health", "priority": 85, "reason": "Oskar is hungry", "child_id": "kid", "created_at": w["tick"] - 1800})
check("a fresh intention raises no question", _sec_pressing_intentions(mum, w) is None)
mum["activity"] = {"type": "relax"}
w["tick"] = mum["active_intentions"][0]["deadline_tick"] + 1
it.check_intention_deadlines(mum, w)
lines = _sec_pressing_intentions(mum, w)
text = " ".join(lines or [])
check("once it is overdue the prompt says what they were doing", "you were relaxing" in text, text)
check("and asks why they are not feeding the child right now", "why am I not feeding Oskar Lindqvist right now?" in text, text)
check("and what could be more important, and what is in the way", "What could be more important than this, and what is actually in the way?" in text)
check("it says how long they have been meaning to", "meaning to feed Oskar Lindqvist for " in text and " minutes" in text)
w["tick"] = mum["active_intentions"][0]["deadline_tick"] + 1
it.check_intention_deadlines(mum, w)
check("at the next stage, that it cannot wait", "cannot wait any longer" in " ".join(_sec_pressing_intentions(mum, w)))
for n in range(4):
    it.add_intention(mum, {"type": f"drink{n}", "category": "survival", "priority": 90 + n, "reason": f"thirst {n}", "stage": 2, "created_at": w["tick"]})
check("no more than two are put to them", len(_sec_pressing_intentions(mum, w)) == 2)
mum["active_intentions"] = [{"type": "exercise", "category": "leisure", "priority": 70, "stage": 1}]
check("ordinary leisure intentions that escalated once do not trigger it", _sec_pressing_intentions(mum, w) is None)

# ---- tending a child -----------------------------------------------------------------------------------------------------------------------
w, mum, dad, kid = home()
kid["body"]["hunger"] = 90
kid["_awaiting_caregiver"] = {"need": "hunger", "tick": w["tick"]}
for p in (mum, dad):
    it.add_intention(p, {"type": "feed_child_kid", "category": "health", "priority": 85, "reason": "hungry", "child_id": "kid"})
cc.tend_child(mum, w, mum["active_intentions"][0])
check("the parent feeds the child", kid["body"]["hunger"] == 30 and not kid.get("_awaiting_caregiver"), str(kid["body"]))
check("and neither parent is left with the intention", not mum["active_intentions"] and not dad["active_intentions"])
check("they remember it", any("I fed Oskar" in m["text"] for m in mum["memories"]))

w, mum, dad, kid = home()
kid["_awaiting_caregiver"] = {"need": "hunger"}
kid["building_id"] = "b2"
it.add_intention(mum, {"type": "feed_child_kid", "category": "health", "priority": 85, "child_id": "kid"})
check("not when the child is in another building (they have to get there)", not cc.tend_child(mum, w, mum["active_intentions"][0]) and mum["active_intentions"])
kid["building_id"], kid["off_grid"] = "b1", True
check("nor when the child is away at school", not cc.tend_child(mum, w, mum["active_intentions"][0]) and mum["active_intentions"])
kid["off_grid"] = False
kid.pop("_awaiting_caregiver")
check("an intention whose need has gone is dropped", not cc.tend_child(mum, w, mum["active_intentions"][0]) and not mum["active_intentions"])

w, mum, dad, kid = home()
kid["_awaiting_reminder"] = {"need": "bladder", "tick": w["tick"]}
it.add_intention(mum, {"type": "remind_child_kid", "category": "health", "priority": 60, "child_id": "kid", "need": "bladder"})
check("a reminder is given", cc.tend_child(mum, w, mum["active_intentions"][0]))
check("and the child gets the intention to go", any(i["type"] == "go_to_toilet" for i in kid["active_intentions"]), str(kid["active_intentions"]))

# ---- food in the house --------------------------------------------------------------------------------------------------------------------------
from systems.household_pantry import stock_pantry, food_units
from systems.strategy import resolve_hunger_strategy
w, mum, dad, kid = home()
hh = w["households"]["hh"]
check("an empty house sends a hungry adult out to buy food", resolve_hunger_strategy(dict(mum, money=500), w) in ("buy_food", "order_takeout"))
added = stock_pantry(w, hh)
check("a household with no food gets a starter supply, per person", added > 0 and food_units(hh) == added and hh["_pantry_stocked"] == w["tick"], str(added))
check("... so a hungry adult can now eat at home", resolve_hunger_strategy(dict(mum, money=500), w) in ("eat_snack", "cook_recipe", "eat_meal", "heat_meal"))
check("only once", stock_pantry(w, hh) == 0)
hh2 = {"id": "h2", "members": ["a"], "storage": {"resources": [{"resource_type": "FOOD_SNACK", "quantity": 2}]}}
check("a house that has food is left alone", stock_pantry(w, hh2) == 0 and food_units(hh2) == 2)
hh3 = {"id": "h3", "members": ["a"], "_pantry_stocked": 5}
check("and one that was stocked before is not topped up (shopping is their business)", stock_pantry(w, hh3) == 0 and food_units(hh3) == 0)

# ---- in the simulation: the model is stubbed to do nothing, and the child still gets fed ------------------------------------------------------------
from tests import determinism

picked = {}


def setup(w):
    kids = [c for c in w["characters"].values() if c.get("age_group") == "child" and not c.get("is_workplace_npc")]
    kid = kids[0]
    kid["body"]["hunger"] = 95
    cc.tick_child_needs(w)
    picked["kid"] = kid["id"]
    picked["parents"] = [p["id"] for p in w["characters"].values() if any(i.get("child_id") == kid["id"] for i in p.get("active_intentions", []))]
    for pid in picked["parents"]:                  # fed, watered, rested, nothing else to do: what is measured is the child care
        parent = w["characters"][pid]
        parent["activity"] = None
        parent["off_grid"] = False
        parent.pop("_body_lazy", None)
        parent["body"].update({"hunger": 0, "hydration": 100, "energy": 100, "fatigue": 0, "bladder": 0, "bowels": 0, "hygiene": 100,
                               "odor": 0, "stomach_discomfort": 0, "mouth_hygiene": 100, "sleep_debt": 0, "hours_awake": 1})
        parent["active_intentions"] = [i for i in parent["active_intentions"] if i.get("child_id") == kid["id"]]


import brain.agent_loop as _al
_al.tick_curiosity = lambda c, w: None
_al.maybe_go_offgrid = lambda c, w: None
_al.maybe_schedule_doctor_visit = lambda c, w: None


w2, errs, _ = determinism.run_sim(120, start="2026-11-04T12:00:00", setup=setup)
kid2 = w2["characters"][picked["kid"]]
print(f"   child {kid2['name']}, parents with the intention: {len(picked['parents'])}; hunger after 120 ticks: {kid2['body'].get('hunger')}; errors {dict(errs)}")
check("the simulation ran without errors", not errs, str(determinism.ERROR_TRACES))
check("a parent got the intention", picked["parents"])
check("the hungry child was fed, with the model doing nothing", not kid2.get("_awaiting_caregiver") and kid2["body"].get("hunger", 100) < 70, str(kid2["body"]))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
