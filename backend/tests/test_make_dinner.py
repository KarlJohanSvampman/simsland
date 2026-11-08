"""
Make Dinner (brain/actionplans): the expectation acted on by plans, not left to the model's choice.

Live (2026-11-08, 24h runs): nothing ever called systems/expectation_planner.py, so dinner was only made if the model
happened to choose cooking; both parents missed Sunday's dinner window. Now: waits until half an hour before the window
(act_when), then: someone already cooked -> met; cook (shopping first if the cupboards are bare); heat ready meals;
takeout. Met for every grown-up of the household who had it to do.

Run inside the backend container:   python tests/test_make_dinner.py
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
from systems.schema_defaults import ensure_world_defaults
from brain.actionplans import store, checker, runner
from brain.actionplans import resolvers as R
from core.definitions import load_definitions

data = store.load()
errors = [p for p in checker.check(data, load_definitions("default")) if p["level"] == "error"]
check("the behaviour definitions pass the path checker", not errors, str(errors[:3]))
check("Make Dinner is live and takes over expectation:make_dinner",
      runner.live_intention_for({}, "expectation:make_dinner")["id"] == "make_dinner")

DINNER = {"type": "expectation:make_dinner", "category": "schedule", "priority": 50, "reason": "You still need to make dinner."}


def world(tick_to_window):
    w = make_world()
    w["tick"] = 60000
    w["calendar"] = {"year": 2026, "month": 11, "day": 2, "hour": 17, "minute": 30, "second": 0, "minute_of_day": 1050, "weekday": "Monday"}
    ensure_world_defaults(w)
    k, rob = w["characters"]["kathleen"], w["characters"]["robert"]
    for c in w["characters"].values():
        c.setdefault("body", {}).update(hunger=20)
        c["activity"] = None
        c["traits"] = ["impulsive"]
    k.update(age=10, age_group="child")
    rob.update(age=42, age_group="adult", money=0)
    rob["expectations"] = {"make_dinner": {"template_id": "make_dinner", "status": "pending", "streak": 0, "frustration": 0,
                                           "missed_count": 0, "window_start_tick": w["tick"] + tick_to_window,
                                           "window_end_tick": w["tick"] + tick_to_window + 3600}}
    rob["active_intentions"] = [dict(DINNER)]
    hh = w["households"]["oka"]
    hh["leftovers"], hh["ready_meals"], hh["deliveries"] = [], [], []
    hh.setdefault("storage", {})["resources"] = []
    return w, rob, hh


def steps(c):
    att = (c.get("plan_attempts") or {}).get("make_dinner") or ((c.get("plan_log") or [{}])[-1])
    return [(t.get("plan"), t.get("node"), t.get("what"), t.get("out")) for t in att.get("trace") or []]


# lunchtime: nothing to do yet, and the intention stays
w, rob, hh = world(5 * 3600)
res = runner.autopilot(rob, w, rob["active_intentions"][0])
check("five hours before the dinner window: waits -- no attempt, nothing cleared", res == "busy"
      and not rob.get("plan_attempts", {}).get("make_dinner") and rob["active_intentions"] and not rob.get("plan_log"))

# twenty minutes before: cook
w, rob, hh = world(20 * 60)
real_ingr = R.RESOLVERS["has_ingredients"]
R.RESOLVERS["has_ingredients"] = lambda c, w_: True
res = runner.autopilot(rob, w, rob["active_intentions"][0])
check("twenty minutes before the window, ingredients in: they start cooking", res == "started" and rob["activity"]["type"] == "cook_recipe",
      f"{res} {steps(rob)}")
rob["activity"] = None
runner.on_activity_end({"character_id": "robert", "activity_type": "cook_recipe"}, w, "done")
check("... cooked: Make Dinner is met", rob["expectations"]["make_dinner"]["status"] == "satisfied"
      and rob["plan_log"][-1]["status"] == "satisfied", f"{rob['expectations']['make_dinner'].get('status')} {steps(rob)[-3:]}")
R.RESOLVERS["has_ingredients"] = real_ingr

# someone else already cooked: met for them too
w, rob, hh = world(0)
import systems.cookware as cw
real_ready = cw.ready_vessel
cw.ready_vessel = lambda h, tick: {"kind": "pot"} if h.get("id") == "oka" else None
res = runner.autopilot(rob, w, rob["active_intentions"][0])
check("dinner already on the table: met without cooking again", rob["expectations"]["make_dinner"]["status"] == "satisfied"
      and ("dinner_on_the_table", "made", "action", "done") in steps(rob), str(steps(rob)))
cw.ready_vessel = real_ready

# bare cupboards, shops open: shopping first
w, rob, hh = world(0)
real_open = R.RESOLVERS["grocery_open"]
R.RESOLVERS["grocery_open"] = lambda c, w_: True
runner.autopilot(rob, w, rob["active_intentions"][0])
check("nothing in the cupboards: off to the shops first", rob.get("off_grid") and ("buy_groceries", "shop", "action", "done") in steps(rob),
      str(steps(rob)[-4:]))
R.RESOLVERS["grocery_open"] = real_open

# satisfied already: the intention is just cleared
w, rob, hh = world(0)
rob["expectations"]["make_dinner"]["status"] = "satisfied"
check("already met this evening: nothing to do", runner.autopilot(rob, w, rob["active_intentions"][0]) == "busy")

# ---- the school run: nothing expected on a day without school ---------------------------------------------------------
from systems.expectations import _has_school_run_today
import systems.offgrid as og
w, rob, hh = world(0)
k = w["characters"]["kathleen"]
check("a child not enrolled anywhere: no school run expected today", _has_school_run_today(rob, w) is False)
k["current_school"] = "school_1"
real_block = og._school_block
og._school_block = lambda c, w_: {"activity": "school", "start": "08:30", "end": "15:00"}
check("enrolled, with school today: the school run is expected", _has_school_run_today(rob, w) is True)
og._school_block = lambda c, w_: None
check("enrolled, but no school today (the weekend): not expected", _has_school_run_today(rob, w) is False)
og._school_block = real_block

# ---- Have Dinner Together ----------------------------------------------------------------------------------------------
def together_world():
    w, rob, hh = world(0)
    k = w["characters"]["kathleen"]
    k.update(building_id="starter_house_2", x=60, y=6)
    rob.update(building_id="starter_house_2", x=60, y=8)
    for c in (rob, k):
        c["room_id"] = "starter_house_2:dining_room_1"
    rob["expectations"]["family_dinner_together"] = {"template_id": "family_dinner_together", "status": "pending", "streak": 0,
                                                     "frustration": 0, "missed_count": 0, "requires_others": True,
                                                     "window_start_tick": w["tick"], "window_end_tick": w["tick"] + 3600}
    return w, rob, k


TOGETHER = {"type": "expectation:family_dinner_together", "category": "social", "priority": 55, "reason": "dinner together"}


def tsteps(c):
    att = (c.get("plan_attempts") or {}).get("dinner_together") or ((c.get("plan_log") or [{}])[-1])
    return [(t.get("plan"), t.get("node"), t.get("what"), t.get("out")) for t in att.get("trace") or []]


w, rob, k = together_world()
cw.ready_vessel = lambda h, tick: {"kind": "pot"} if h.get("id") == "oka" else None
res = runner.autopilot(rob, w, dict(TOGETHER))
check("dinner together: everyone home, food on the table -- called to the table, and they sit down to eat",
      ("dinner_together", "call", "action", "done") in tsteps(rob) and res == "started" and rob["activity"]["type"] == "eat_meal"
      and (k.get("activity") or {}).get("type") == "eat_meal", f"{res} {tsteps(rob)} kathleen={k.get('activity')}")
k["activity"] = None
rob["activity"] = None
runner.on_activity_end({"character_id": "robert", "activity_type": "eat_meal"}, w, "done")
k["room_id"] = "starter_house_2:kitchen_0"                # finished first, went for a glass of water
check("... the whole household was there (one finished first and went for water): met", rob["expectations"]["family_dinner_together"]["status"] == "satisfied"
      and rob["plan_log"][-1]["status"] == "satisfied", str(tsteps(rob)[-3:]))

w, rob, k = together_world()
k["conversation"] = "conv_1"                               # on the phone, can't come
runner.autopilot(rob, w, dict(TOGETHER))
k["room_id"] = "starter_house_2:bedroom_5"                # ... and stayed upstairs
rob["activity"] = None
runner.on_activity_end({"character_id": "robert", "activity_type": "eat_meal"}, w, "done")
check("... Kathleen, busy on the phone, stayed in her room: not met, and it says who wasn't there",
      rob["expectations"]["family_dinner_together"]["status"] != "satisfied" and "Kathleen" in str(rob["plan_log"][-1].get("why"))
      and rob["expectations"]["family_dinner_together"].get("last_missed_blame") == ["kathleen"], str(rob["plan_log"][-1]))

w, rob, k = together_world()
for e in ("family_dinner_together",):
    rob["expectations"][e].update(window_start_tick=w["tick"] + 40 * 60, window_end_tick=w["tick"] + 100 * 60)
rob["expectations"]["make_dinner"]["status"] = "satisfied"
cw.ready_vessel = real_ready
check("forty minutes early, dinner not cooked: not yet", R.RESOLVERS["family_dinner_time"](rob, w) is False)
cw.ready_vessel = lambda h, tick: {"kind": "pot"} if h.get("id") == "oka" else None
check("forty minutes early, but dinner was just made and is on the table: sit down to it now", R.RESOLVERS["family_dinner_time"](rob, w) is True)

w, rob, k = together_world()
k.update(off_grid=True)
res = runner.autopilot(rob, w, dict(TOGETHER))
check("someone is out: they wait for everyone to come home", res == "busy"
      and ((rob["plan_attempts"].get("dinner_together") or {}).get("wait") or {}).get("node") == "wait_home", str(tsteps(rob)))
cw.ready_vessel = real_ready

# ---- Check the Kids at Bedtime -----------------------------------------------------------------------------------------
w, rob, k = together_world()
rob["dependents"] = ["kathleen"]
rob["expectations"]["child_bedtime_check"] = {"template_id": "child_bedtime_check", "status": "pending", "streak": 0, "frustration": 0,
                                              "missed_count": 0, "window_start_tick": w["tick"], "window_end_tick": w["tick"] + 3600}
k["body"]["fatigue"] = 70
runner.autopilot(rob, w, {"type": "expectation:child_bedtime_check", "category": "household", "priority": 60, "reason": "bedtime"})
check("bedtime: they look in on the kids, send the one still up to bed, and it is met",
      rob["expectations"]["child_bedtime_check"]["status"] == "satisfied"
      and any(i.get("type") == "go_to_sleep" for i in k.get("active_intentions") or []), str(rob.get("plan_log", [])[-1:]))

from core.definitions import load_definitions as _ld
check("a household dining table seats four", sum(1 for a in _ld("default")["prop_templates"]["dining_table_a"]["anchors"]
                                                if a.get("interaction") == "eat") >= 4)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
