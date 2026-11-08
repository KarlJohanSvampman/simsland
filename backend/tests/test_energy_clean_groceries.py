"""
Restore Energy, Get Clean, and Buy groceries (brain/actionplans) on the real house world.

A nap asked for by day is a nap (it counts as done, however tired they still are), not a night's sleep. Sleep at night;
woken for the bathroom and back to bed is still the same night. Bedtime keeps the need open however rested they are. A
shower gets them clean. Cooking with nothing in the cupboards sends a grown-up out on the grocery trip, and cooking
carries on when they are back with the shopping.

Run inside the backend container:   python tests/test_energy_clean_groceries.py
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
intents = store.by_id(data, "intentions")
check("Restore Energy and Get Clean are live; Buy groceries is usable",
      intents["restore_energy"]["status"] == intents["get_clean"]["status"] == "live"
      and store.by_id(data, "plans")["buy_groceries"].get("status") != "planned")


def world(hour=14):
    w = make_world()
    w["tick"] = 40000
    w["calendar"] = {"year": 2026, "month": 11, "day": 2, "hour": hour, "minute": 0, "second": 0,
                     "minute_of_day": hour * 60, "weekday": "Monday"}
    ensure_world_defaults(w)
    for c in w["characters"].values():
        c.setdefault("body", {}).update(fatigue=10, hygiene=90, hunger=10)
        c["activity"] = None
        c["traits"] = ["impulsive"]
        c["age"], c["age_group"] = 35, "adult"
    return w


def steps(c, iid):
    att = (c.get("plan_attempts") or {}).get(iid) or ((c.get("plan_log") or [{}])[-1])
    return [(t.get("plan"), t.get("node"), t.get("what"), t.get("out")) for t in att.get("trace") or []]


real_wants_bed = R.RESOLVERS["wants_bed"]
R.RESOLVERS["wants_bed"] = lambda c, w: False

# ---- a nap by day ---------------------------------------------------------------------------------------------------
w = world()
j = w["characters"]["joseph"]
j["body"]["fatigue"] = 80
res = runner.autopilot(j, w, {"type": "take_nap", "category": "health", "priority": 65, "reason": "tired"})
check("a nap asked for by day: a nap, not a night's sleep", res == "started" and j["activity"]["type"] == "nap",
      f"{res} {j.get('activity')} {steps(j, 'restore_energy')}")
j["body"]["fatigue"] = 45
j["activity"] = None
runner.on_activity_end({"character_id": "joseph", "activity_type": "nap"}, w, "done")
check("... still a bit tired after it, but the nap is done: satisfied", j["plan_log"][-1]["status"] == "satisfied", str(j["plan_log"][-1]))
w = world()
j = w["characters"]["joseph"]
j["body"]["fatigue"] = 90
runner.autopilot(j, w, {"type": "take_nap", "category": "health", "priority": 65, "reason": "tired"})
j["body"]["fatigue"] = 80
j["activity"] = None
runner.on_activity_end({"character_id": "joseph", "activity_type": "nap"}, w, "done")
check("a nap that leaves them still exhausted: a proper sleep after it, not nap after nap",
      (j.get("activity") or {}).get("type") == "sleep" and ("nap_by_day", "enough", "decision", "still exhausted") in steps(j, "restore_energy"),
      str(steps(j, "restore_energy")))

# ---- a night's sleep, a bathroom break, back to bed ------------------------------------------------------------------
w = world(hour=23)
j = w["characters"]["joseph"]
j["body"]["fatigue"] = 85
res = runner.autopilot(j, w, {"type": "sleep", "category": "health", "priority": 88, "reason": "tired"})
check("sleep at night: the nap plan says 'a night's sleep', then bed", res == "started" and j["activity"]["type"] == "sleep"
      and ("nap_by_day", "asked", "decision", "a night's sleep") in steps(j, "restore_energy"), str(steps(j, "restore_energy")))
j["activity"] = None
runner.on_activity_end({"character_id": "joseph", "activity_type": "sleep", "reason": "bladder_urgent"}, w, "failed")
att = j["plan_attempts"]["restore_energy"]
check("woken by the bladder: not a failure yet -- they wait to be back in bed", (att.get("wait") or {}).get("node") == "back",
      str(steps(j, "restore_energy")))
j["activity"] = {"type": "sleep"}                     # back to bed (systems/activities.py's _resume_sleep_after_bathroom)
w["tick"] += 120
runner._on_wait_timer(w, {"owner": "planwait:joseph", "key": "restore_energy"})
check("... asleep again: still waiting while they sleep", j["plan_attempts"].get("restore_energy"))
j["activity"] = None
j["body"]["fatigue"] = 5
w["tick"] += 8 * 3600
runner._on_wait_timer(w, {"owner": "planwait:joseph", "key": "restore_energy"})
check("... and the morning after: one night, satisfied", j["plan_log"][-1]["status"] == "satisfied"
      and not j.get("plan_attempts", {}).get("restore_energy"), str(j["plan_log"][-1]))

# ---- bedtime keeps it open however rested ---------------------------------------------------------------------------
w = world(hour=22)
j = w["characters"]["joseph"]
j["body"]["fatigue"] = 10
R.RESOLVERS["wants_bed"] = lambda c, w_: True
res = runner.autopilot(j, w, {"type": "sleep", "category": "health", "priority": 88, "reason": "bedtime"})
check("bedtime before a work day, not tired: off to bed all the same", res == "started" and j["activity"]["type"] == "sleep",
      f"{res} {steps(j, 'restore_energy')}")
R.RESOLVERS["wants_bed"] = lambda c, w_: False
w = world()
j = w["characters"]["joseph"]
j["active_intentions"] = [{"type": "sleep", "category": "health", "priority": 88, "reason": "tired"}]
res = runner.autopilot(j, w, j["active_intentions"][0])
check("not bedtime and not tired: a leftover sleep intention just goes", res == "busy" and not j["active_intentions"])

# ---- a shower -------------------------------------------------------------------------------------------------------
w = world()
j = w["characters"]["joseph"]
j["body"]["hygiene"] = 25
res = runner.autopilot(j, w, {"type": "take_shower", "category": "health", "priority": 65, "reason": "hygiene_low"})
check("feeling dirty: a shower starts (the shower prop's 'shower' anchor)", res == "started" and j["activity"]["type"] == "take_shower",
      f"{res} {j.get('activity')} {steps(j, 'get_clean')}")
from systems.activities import complete_activity
complete_activity(j, w, j["activity"])
j["activity"] = None
runner.on_activity_end({"character_id": "joseph", "activity_type": "take_shower"}, w, "done")
check("... clean afterwards: satisfied", j["body"]["hygiene"] > 90 and j["plan_log"][-1]["status"] == "satisfied", str(j["plan_log"][-1]))

# ---- nothing in the cupboards: the grocery trip, then cooking -------------------------------------------------------
w = world()
j = w["characters"]["joseph"]
j.update(money=100)
j["body"]["hunger"] = 85
hh = w["households"]["lind"]
hh["leftovers"], hh["ready_meals"], hh["deliveries"] = [], [], []
hh.setdefault("storage", {})["resources"] = []
real = {k: R.RESOLVERS[k] for k in ("grocery_open", "phone_usable")}
R.RESOLVERS["grocery_open"] = lambda c, w_: True
R.RESOLVERS["phone_usable"] = lambda c, w_: False          # no takeout: cooking is the way
res = runner.autopilot(j, w, {"type": "eat_food", "category": "survival", "priority": 80, "reason": "very_hungry"})
tr = steps(j, "reduce_hunger")
att = j["plan_attempts"].get("reduce_hunger") or {}
check("no ingredients: cooking sidetracks into the grocery trip, and they go out",
      ("buy_groceries", "shop", "action", "done") in tr and j.get("off_grid") and hh.get("shopping_plan")
      and (att.get("wait") or {}).get("node") == "back", f"{tr[-6:]} off_grid={j.get('off_grid')}")
real_ingr = R.RESOLVERS["has_ingredients"]
R.RESOLVERS["has_ingredients"] = lambda c, w_: True          # home with the shopping (systems/offgrid.py's return restocks)
j["off_grid"] = False
w["tick"] += 3000
runner._on_wait_timer(w, {"owner": "planwait:joseph", "key": "reduce_hunger"})
tr = steps(j, "reduce_hunger")
check("... back with the shopping: cooking picks up where it left off",
      ("buy_groceries", "back", "wait", "ready") in tr and (j.get("activity") or {}).get("type") == "cook_recipe", str(tr[-6:]))
R.RESOLVERS["has_ingredients"] = real_ingr
R.RESOLVERS.update(real)

w = world(hour=3)
j = w["characters"]["joseph"]
j["body"]["hunger"] = 85
hh = w["households"]["lind"]
hh["leftovers"], hh["ready_meals"], hh["deliveries"] = [], [], []
hh.setdefault("storage", {})["resources"] = []
runner.autopilot(j, w, {"type": "eat_food", "category": "survival", "priority": 80, "reason": "very_hungry"})
w2 = world()
j2 = w2["characters"]["joseph"]
j2["_offgrid_last_trip"] = {"reason": "shopping", "day": __import__("systems.offgrid", fromlist=["_today"])._today(w2)}
att2 = {"vars": {}}
from brain.actionplans.actions import ACTIONS
check("a second grocery trip the same day is refused, saying so",
      ACTIONS["go_grocery_shopping"](j2, w2, att2) is False and att2["vars"].get("why") == "already went shopping today", str(att2))
check("at three in the morning the shops are shut: no trip", not j.get("off_grid")
      and ("buy_groceries", "store", "gate", "no") in steps(j, "reduce_hunger"), str(steps(j, "reduce_hunger")[-5:]))

# ---- a step's end reported after something else has already started: no clash, it resumes when free --------------
w = world()
j = w["characters"]["joseph"]
j["body"]["hygiene"] = 25
runner.autopilot(j, w, {"type": "take_shower", "category": "health", "priority": 65, "reason": "hygiene_low"})
j["activity"] = {"type": "use_toilet", "phase": "using"}       # the bladder took over before the event came in
runner.on_activity_end({"character_id": "joseph", "activity_type": "take_shower"}, w, "failed")
att = j["plan_attempts"].get("get_clean") or {}
check("an interrupted step heard about while on the toilet: nothing new starts on top", j["activity"]["type"] == "use_toilet"
      and att.get("resume"), str(att))
j["activity"] = None
runner.autopilot(j, w, {"type": "take_shower", "category": "health", "priority": 65, "reason": "hygiene_low"})
check("... and once free the plan carries on from that outcome: no shower, so a wash at the sink",
      (j.get("activity") or {}).get("type") == "wash_up" and ("shower", None, "fallback", None) in steps(j, "get_clean"),
      str(steps(j, "get_clean")))
j["activity"] = None
j["body"]["hygiene"] = 50
runner.on_activity_end({"character_id": "joseph", "activity_type": "wash_up"}, w, "done")
check("... the wash counts: satisfied", j["plan_log"][-1]["status"] == "satisfied", str(j["plan_log"][-1:]))

# ---- thirst: a glass of water, a second one if the first wasn't enough ----------------------------------------------
w = world()
j = w["characters"]["joseph"]
j["body"]["hydration"] = 40
res = runner.autopilot(j, w, {"type": "drink", "category": "survival", "priority": 60, "reason": "thirsty"})
check("thirsty: a glass of water at the sink", res == "started" and j["activity"]["type"] == "drink_water",
      f"{res} {steps(j, 'reduce_thirst')}")
j["activity"] = None
j["body"]["hydration"] = 55                      # no clean glass: cupped hands, only +15
runner.on_activity_end({"character_id": "joseph", "activity_type": "drink_water"}, w, "done")
check("... still thirsty after it: a second drink", (j.get("activity") or {}).get("type") == "drink_water"
      and ("glass_of_water", "enough", "decision", "still thirsty") in steps(j, "reduce_thirst"), str(steps(j, "reduce_thirst")))
j["activity"] = None
j["body"]["hydration"] = 70
runner.on_activity_end({"character_id": "joseph", "activity_type": "drink_water"}, w, "done")
check("... and that will do: satisfied", j["plan_log"][-1]["status"] == "satisfied", str(j["plan_log"][-1:]))
w = world()
j = w["characters"]["joseph"]
j.update(x=50, y=80)
j["body"]["hydration"] = 40
runner.autopilot(j, w, {"type": "drink", "category": "survival", "priority": 60, "reason": "thirsty"})
check("out in the open, home far away... a sink at home still counts as reachable: they go home for it",
      (j.get("activity") or {}).get("type") == "drink_water", str(steps(j, "reduce_thirst")))

R.RESOLVERS["wants_bed"] = real_wants_bed
print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
