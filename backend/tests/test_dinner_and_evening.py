"""
- Waiting for family dinner: with the household's family dinner due within 90 minutes, Reduce Hunger doesn't start
  a meal of their own -- unless they're badly hungry (brain/actionplans/resolvers.py::not_waiting_for_dinner).
- The day running out: a daily expectation still unmet from 20:30 to 22:30 is pressing (systems/todo.py::tier) --
  before, "relax with someone" was always behind something pressing and missed every evening.

Run inside the backend container:   python tests/test_dinner_and_evening.py
"""
import json
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


from brain.actionplans.resolvers import not_waiting_for_dinner, DINNER_WAIT_SECONDS
from house_world import make_world

w = make_world()
w["tick"] = 100000
dad, kid = w["characters"]["robert"], w["characters"]["kathleen"]
kid["household_id"] = dad.get("household_id")
dad["expectations"] = {"family_dinner_together": {"status": "pending", "window_start_tick": w["tick"] + 3600,
                                                 "window_end_tick": w["tick"] + 7200}}
dad.setdefault("body", {})["hunger"] = 62
kid.setdefault("body", {})["hunger"] = 65
kid["expectations"] = {}
check("dinner in an hour, peckish: waits for it", not not_waiting_for_dinner(dad, w))
check("... so does the rest of the household (dinner is theirs too)", not not_waiting_for_dinner(kid, w))
dad["body"]["hunger"] = 85
check("badly hungry: eats now anyway", not_waiting_for_dinner(dad, w))
dad["body"]["hunger"] = 62
dad["expectations"]["family_dinner_together"]["window_start_tick"] = w["tick"] + DINNER_WAIT_SECONDS + 600
check("dinner further off than an hour and a half: eats now", not_waiting_for_dinner(dad, w))
dad["expectations"]["family_dinner_together"].update(window_start_tick=w["tick"] - 600, status="satisfied")
check("dinner already had: eats", not_waiting_for_dinner(dad, w))

b = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "simulations", "default", "behaviour.json")))
rh = next(i for i in b["intentions"] if i["id"] == "reduce_hunger")
check("Reduce Hunger acts only when not waiting for dinner (behaviour.json)", rh.get("act_when") == "not_waiting_for_dinner"
      and any(r["id"] == "not_waiting_for_dinner" for r in b["requirements"]))

from systems import todo
from brain import intentions as ints
day0 = 200000                                  # a day's window: day0 .. day0 + 24 h (midnight to midnight)
i = {"type": "expectation:relax_with_someone", "category": "social", "priority": 25,
     "window_start_tick": day0, "window_end_tick": day0 + 86400}
def at(h, m=0):
    ints._CURRENT_TICK = day0 + h * 3600 + m * 60
    return todo.tier(i)
check("relax with someone at 18:00: when there's time", at(18) == "when_free")
check("... at 20:30, still not done: pressing", at(20, 30) == "pressing")
check("... at 22:00: pressing", at(22) == "pressing")
check("... at 23:00 (the day is over for that): not pressing", at(23) == "when_free")
week = dict(i, window_end_tick=day0 + 7 * 86400)
ints._CURRENT_TICK = day0 + 20 * 3600 + 3600
check("a weekly one isn't made pressing every evening", todo.tier(week) == "when_free")
short = dict(i, window_start_tick=day0 + 18 * 3600, window_end_tick=day0 + 19 * 3600)
ints._CURRENT_TICK = day0 + 18 * 3600 + 600
check("dinner's hour still pressing while open (unchanged)", todo.tier(short) == "pressing")

# ---- a meal isn't broken off: not to ask around, not to come and sit down with someone ----
import systems.whereabouts as wa
eater = {"id": "e", "activity": {"type": "eat_meal"}, "perception": {"visible_people": []}}
wa._pending_target = lambda c, world: "someone"
check("eating: doesn't stop to ask where someone is", wa.check_ask_whereabouts(eater, {"tick": 1, "characters": {}}) is False)
from brain.actionplans.resolvers import unwind_companion, NOT_FREE_TO_UNWIND
check("eating isn't free to unwind", "eat_meal" in NOT_FREE_TO_UNWIND)
w2 = make_world()
a, b = w2["characters"]["robert"], w2["characters"]["kathleen"]
b.update(age=40, household_id=a.get("household_id"), building_id=a.get("building_id"), activity={"type": "eat_meal"})
for o in w2["characters"].values():
    if o is not a and o is not b:
        o["building_id"] = "elsewhere"
check("... so nobody eating is picked to unwind with", unwind_companion(a, w2) is None)
import brain.actionplans.actions as acts
check("... and an invite doesn't pull them away from the table",
      acts.invite_to_unwind(a, w2, {"vars": {"unwind_with": "kathleen"}}) is False and b["activity"]["type"] == "eat_meal")

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
