"""
Intentions and ActionPlans (brain/actionplans): Reduce Hunger end to end on the real house world.

The definitions (simulations/default/behaviour.json) pass the path checker; then each way of satisfying hunger is walked:
food served -> eat; only ingredients -> cook; a child with nothing ready -> asks a grown-up; nothing at all -> blocked with
the reason; takeout late at night -> the delivery-hours decision says closed. Every transition is in the attempt's trace.

Run inside the backend container:   python tests/test_action_plans.py
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
from core.definitions import load_definitions
from core import event_bus

data = store.load()
errors = [p for p in checker.check(data, load_definitions("default")) if p["level"] == "error"]
check("the behaviour definitions pass the path checker", not errors, str(errors[:3]))
intents = store.by_id(data, "intentions")
check("one intention per drive, and every drive has one",
      all(intents[d["intention"]]["drive"] == d["id"] for d in data["drives"]) and len(data["drives"]) == len(intents))
check("Reduce Hunger is live and replaces eat_food", intents["reduce_hunger"]["status"] == "live"
      and runner.live_intention_for({}, "eat_food")["id"] == "reduce_hunger")

EAT = {"type": "eat_food", "category": "survival", "priority": 80, "reason": "very_hungry"}


def world(hour=12, minute=0):
    w = make_world()
    w["tick"] = 20000
    w["calendar"] = {"year": 2026, "month": 11, "day": 2, "hour": hour, "minute": minute, "second": 0,
                     "minute_of_day": hour * 60 + minute, "weekday": "Monday"}
    ensure_world_defaults(w)
    for c in w["characters"].values():
        c.setdefault("body", {})["hunger"] = 85
        c["activity"] = None
        c["traits"] = ["impulsive"]                 # no scouting in these cases: straight to the plans
    for hh in w["households"].values():
        hh["leftovers"] = []
        hh.setdefault("storage", {})["resources"] = []
        hh["ready_meals"] = []
        hh["deliveries"] = []
    return w


def flush(w):
    event_bus.flush(w)


def last_trace(c, iid="reduce_hunger"):
    att = (c.get("plan_attempts") or {}).get(iid) or ((c.get("plan_log") or [{}])[-1])
    return att.get("trace") or []


def what(c):
    return [(t.get("plan"), t.get("node"), t.get("what"), t.get("out")) for t in last_trace(c)]


# ---- food is served: eat it ---------------------------------------------------------------------------------------
w = world()
r = w["characters"]["robert"]
import systems.cookware as cw
real_ready = cw.ready_vessel
cw.ready_vessel = lambda hh, tick: {"kind": "pot"} if hh.get("id") == "oka" else None
res = runner.autopilot(r, w, EAT)
check("food served: the light meal plan starts eating", res == "started" and r["activity"]["type"] == "eat_meal",
      f"{res} {r.get('activity')} {what(r)}")
r["body"]["hunger"] = 10
r["activity"] = None
runner.on_activity_end({"character_id": "robert", "activity_type": "eat_meal"}, w, "done")
check("... it finishes and the need is met: satisfied", r["plan_log"][-1]["status"] == "satisfied"
      and not r.get("plan_attempts", {}).get("reduce_hunger"), str(r["plan_log"][-1]))
check("... and the trace shows the gate that found the food", ("light_meal", "served", "gate", "yes") in
      [(t.get("plan"), t.get("node"), t.get("what"), t.get("out")) for t in r["plan_log"][-1]["trace"]])
cw.ready_vessel = real_ready

# ---- only ingredients: light meal falls back, cooking starts -------------------------------------------------------
w = world()
r = w["characters"]["robert"]
r["age"], r["age_group"] = 42, "adult"
from brain.actionplans import resolvers as R
real_ingr = R.RESOLVERS["has_ingredients"]
R.RESOLVERS["has_ingredients"] = lambda c, w_: True
res = runner.autopilot(r, w, EAT)
tr = what(r)
check("nothing ready but ingredients: light meal falls back, then cooking starts",
      ("light_meal", None, "fallback", None) in [(a, b, c_, d) for a, b, c_, d in tr] and res == "started"
      and r["activity"]["type"] == "cook_recipe", f"{res} {r.get('activity', {}) and r['activity'].get('type')} {tr}")
check("... it believes what it found (no snack, has ingredients)", runner.believed(r, w, "has_snack") is False
      and runner.believed(r, w, "has_ingredients") is True)
r["activity"] = None
runner.on_activity_end({"character_id": "robert", "activity_type": "cook_recipe"}, w, "done")
check("... after cooking it waits for the food to be ready", (r["plan_attempts"]["reduce_hunger"].get("wait") or {}).get("node") == "wait")
R.RESOLVERS["has_ingredients"] = real_ingr

# ---- a child with nothing ready: asks a grown-up, then waits -----------------------------------------------------
w = world()
k, rob = w["characters"]["kathleen"], w["characters"]["robert"]
k.update(age=10, age_group="child", building_id="starter_house_2")
rob.update(age=42, age_group="adult", building_id="starter_house_2")
k["money"] = 0
res = runner.autopilot(k, w, EAT)
tr = what(k)
check("a child can't cook, has no money for takeout: asks a grown-up",
      any(t[0] == "ask_for_food" and t[2] == "action" and t[3] == "done" for t in tr), str(tr))
check("... the grown-up now has to feed them", any(str(i.get("type", "")).startswith("feed_child_") and i.get("child_id") == "kathleen"
                                                   for i in rob.get("active_intentions") or []))
check("... and the child waits for the food", (k["plan_attempts"]["reduce_hunger"].get("wait") or {}).get("node") == "wait")

# ---- nothing at all: blocked, with the reason, and not retried at once -------------------------------------------
w = world()
j = w["characters"]["joseph"]
j.update(age=35, age_group="adult", money=0)
real_open = R.RESOLVERS["grocery_open"]
R.RESOLVERS["grocery_open"] = lambda c, w_: False          # the shops are shut (open, they would go -- groceries come on credit)
res = runner.autopilot(j, w, EAT)
log = (j.get("plan_log") or [{}])[-1]
check("no food, no money, the shops shut, nobody to ask: blocked, and says why", log.get("status") == "blocked" and log.get("why"), str(log))
check("... remembered", any("blocked" in (m.get("tags") or []) for m in j.get("memories") or []))
check("... and not retried straight away", runner.autopilot(j, w, EAT) == "busy" and not j.get("plan_attempts", {}).get("reduce_hunger"))
R.RESOLVERS["grocery_open"] = real_open

# ---- takeout late at night: the delivery-hours decision ------------------------------------------------------------
w = world(hour=23, minute=30)
j = w["characters"]["joseph"]
j.update(age=35, age_group="adult", money=200)
runner.autopilot(j, w, EAT)
tr = [(t.get("plan"), t.get("node"), t.get("what"), t.get("out")) for t in (j.get("plan_log") or [{}])[-1].get("trace", [])]
check("23:30: the takeout plan's time-of-day decision says closed", ("order_takeout", "hours", "decision", "closed") in tr, str(tr))
w = world(hour=19)
j = w["characters"]["joseph"]
j.update(age=35, age_group="adult", money=200)
real_phone = R.RESOLVERS["phone_usable"]
R.RESOLVERS["phone_usable"] = lambda c, w_: True          # this test world gives nobody a phone
runner.autopilot(j, w, EAT)
R.RESOLVERS["phone_usable"] = real_phone
att = (j.get("plan_attempts") or {}).get("reduce_hunger") or {}
check("19:00 with money: takeout is ordered and they wait for the delivery",
      ("order_takeout", "order", "action", "done") in [(t.get("plan"), t.get("node"), t.get("what"), t.get("out")) for t in att.get("trace", [])]
      and (att.get("wait") or {}).get("node") == "wait" and w["households"]["lind"].get("deliveries"), str(att.get("trace", [])[-4:]))

# ---- a leftover eat_food while the need is already met: no attempt, and it is cleared --------------------------------
w = world()
j = w["characters"]["joseph"]
j["body"]["hunger"] = 5
j["active_intentions"] = [{"type": "eat_food", "reason": "it is hot", "category": "survival", "priority": 55}]
before = len(j.get("plan_log") or [])
res = runner.autopilot(j, w, j["active_intentions"][0])
check("a leftover eat_food with hunger already met starts nothing, logs nothing, and goes",
      res == "busy" and len(j.get("plan_log") or []) == before and not j["active_intentions"], str((res, j.get("plan_log"))))

# ---- an intention that is not live leaves the old path alone -----------------------------------------------------------
check("an intention type no live intention replaces is not handled here",
      runner.autopilot(j, w, {"type": "visit_person", "reason": "miss her"}) is None)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
