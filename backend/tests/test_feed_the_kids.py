"""
Feed the Kids (brain/actionplans): the grown-up's side of a hungry child's "ask a grown-up for food".

Live (2026-11-08, 24h runs): every child's ask timed out -- the request gave the parent a feed_child intention but never
marked the child as waiting, and the parent's tend_child dropped it as "already seen to". Now the ask marks the child, and
the parent's plans get food ready: call them if food is served, heat a ready meal, cook, order takeout; the old instant
feed only as the last resort. The child's own plan waits for any ready food and eats it.

Run inside the backend container:   python tests/test_feed_the_kids.py
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
check("Feed the Kids is live and takes over every child's feed_child_<id>",
      runner.live_intention_for({}, "feed_child_kathleen")["id"] == "feed_the_kids"
      and runner.live_intention_for({}, "feed_child_susan")["id"] == "feed_the_kids")

EAT = {"type": "eat_food", "category": "survival", "priority": 80, "reason": "very_hungry"}


def world():
    w = make_world()
    w["tick"] = 40000
    w["calendar"] = {"year": 2026, "month": 11, "day": 2, "hour": 14, "minute": 0, "second": 0,
                     "minute_of_day": 840, "weekday": "Monday"}
    ensure_world_defaults(w)
    for c in w["characters"].values():
        c.setdefault("body", {}).update(hunger=10)
        c["activity"] = None
        c["traits"] = ["impulsive"]
    k, rob = w["characters"]["kathleen"], w["characters"]["robert"]
    k.update(age=10, age_group="child", money=0)
    rob.update(age=42, age_group="adult", money=0)
    k["body"]["hunger"] = 85
    hh = w["households"]["oka"]
    hh["leftovers"], hh["ready_meals"], hh["deliveries"] = [], [], []
    hh.setdefault("storage", {})["resources"] = []
    return w, k, rob, hh


def steps(c, iid):
    att = (c.get("plan_attempts") or {}).get(iid) or ((c.get("plan_log") or [{}])[-1])
    return [(t.get("plan"), t.get("node"), t.get("what"), t.get("out")) for t in att.get("trace") or []]


def feed_intention(rob):
    return next((i for i in rob.get("active_intentions") or [] if str(i.get("type")).startswith("feed_child_")), None)


# ---- the ask now reaches the grown-up ------------------------------------------------------------------------------
w, k, rob, hh = world()
runner.autopilot(k, w, EAT)
fi = feed_intention(rob)
check("the child asks: marked as waiting, and the grown-up has the duty", k.get("_awaiting_caregiver") and fi, str(k.get("_awaiting_caregiver")))

# nothing ready, nothing to cook, no phone: the last resort feeds them
real_phone = R.RESOLVERS["phone_usable"]
R.RESOLVERS["phone_usable"] = lambda c, w_: False
res = runner.autopilot(rob, w, fi)
tr = steps(rob, "feed_the_kids")
check("nothing ready, no ingredients, no takeout: the grown-up rustles something up",
      ("kids_something_quick", "feed", "action", "done") in tr and k["body"]["hunger"] < 85 and not k.get("_awaiting_caregiver"),
      f"{res} {tr[-5:]} hunger={k['body']['hunger']}")
check("... the duty is done", rob["plan_log"][-1]["status"] == "satisfied" and not feed_intention(rob), str(rob["plan_log"][-1]))

# food is served: call them to eat
w, k, rob, hh = world()
runner.autopilot(k, w, EAT)
import systems.cookware as cw
real_ready = cw.ready_vessel
cw.ready_vessel = lambda h, tick: {"kind": "pot"} if h.get("id") == "oka" else None
res = runner.autopilot(rob, w, feed_intention(rob))
check("food already served: call the child to come and eat", ("kids_food_is_ready", "call", "action", "done") in steps(rob, "feed_the_kids")
      and not k.get("_awaiting_caregiver") and any(i.get("type") == "eat_food" for i in k.get("active_intentions") or []),
      str(steps(rob, "feed_the_kids")))
w["tick"] += 60
runner._on_wait_timer(w, {"owner": "planwait:kathleen", "key": "reduce_hunger"})
check("... and the child, who was waiting for food, goes and eats it", (k.get("activity") or {}).get("type") == "eat_meal",
      str(steps(k, "reduce_hunger")[-4:]))
cw.ready_vessel = real_ready

# a ready meal in the freezer: heat it, then call
w, k, rob, hh = world()
runner.autopilot(k, w, EAT)
real_rm = R.RESOLVERS["has_ready_meal"]
R.RESOLVERS["has_ready_meal"] = lambda c, w_: True
res = runner.autopilot(rob, w, feed_intention(rob))
check("a ready meal to heat: the grown-up heats it", res == "started" and rob["activity"]["type"] == "heat_meal", f"{res} {steps(rob, 'feed_the_kids')}")
R.RESOLVERS["has_ready_meal"] = real_rm
rob["activity"] = None
runner.on_activity_end({"character_id": "robert", "activity_type": "heat_meal"}, w, "done")
check("... and when it is hot, calls the child", ("kids_heat_a_meal", "call", "action", "done") in steps(rob, "feed_the_kids"),
      str(steps(rob, "feed_the_kids")[-4:]))

# ingredients: cook for the family
w, k, rob, hh = world()
runner.autopilot(k, w, EAT)
real_ingr = R.RESOLVERS["has_ingredients"]
R.RESOLVERS["has_ingredients"] = lambda c, w_: True
res = runner.autopilot(rob, w, feed_intention(rob))
check("ingredients in: the grown-up cooks", res == "started" and rob["activity"]["type"] == "cook_recipe", f"{res} {steps(rob, 'feed_the_kids')}")
R.RESOLVERS["has_ingredients"] = real_ingr
R.RESOLVERS["phone_usable"] = real_phone

# the child found something on their own meanwhile: the grown-up's duty just goes
w, k, rob, hh = world()
runner.autopilot(k, w, EAT)
fi = feed_intention(rob)
k.pop("_awaiting_caregiver", None)
res = runner.autopilot(rob, w, fi)
check("nobody waiting any more: nothing to do, and the duty goes", res == "busy" and not feed_intention(rob))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
