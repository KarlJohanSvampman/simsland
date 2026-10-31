"""
Running late and running over (systems/lateness.py): a share of work shifts and appointments start late or run over by 10-60 minutes,
the reason is in the summary, and getting home late, being ill or worn out make a household order in instead of cooking dinner.

Run inside the backend container:   python tests/test_lateness.py
"""

import os
import random
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from systems import cookware, dinner, food_habits as fh, lateness, offgrid
from systems.body import ensure_body
from systems.offgrid_summary import build_summary

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid="a", **extra):
    c = {"id": cid, "name": f"{cid.upper()} Test", "age": 35, "age_group": "adult", "sex": "female", "weight_kg": 70, "household_id": "h", "building_id": "home",
         "money": 100, "stress": 0, "active_intentions": [], "inventory": [], "body_features": {"height_cm": 170}, "physical_traits": [], "physical_health": []}
    c.update(extra)
    ensure_body(c)
    return c


def world_at(hour=9, minute=0, tick=100000, weekday="Tuesday"):
    return {"tick": tick, "calendar": {"year": 2026, "month": 3, "day": 10, "weekday": weekday, "hour": hour, "minute": minute, "minute_of_day": hour * 60 + minute},
            "characters": {}, "households": {}, "props": []}


# ---- the roll -----------------------------------------------------------------------------------------------------------------------------
rng = random.Random(7)
rolls = [lateness.roll("work", lateness.START_REASONS, rng) for _ in range(4000)]
late = [r for r in rolls if r]
check("about a quarter of the time they are late", 0.20 < len(late) / len(rolls) < 0.30, str(len(late) / len(rolls)))
check("... by 10 to 60 minutes, for a reason", all(10 <= m <= 60 and reason for m, reason in late) and min(m for m, _ in late) <= 12 and max(m for m, _ in late) >= 58)
check("late and over share the chance and the range", lateness.LATE_CHANCE == 0.25 and (lateness.MIN_MINUTES, lateness.MAX_MINUTES) == (10, 60))

# ---- a late start ------------------------------------------------------------------------------------------------------------------------
always = lateness.LATE_CHANCE
lateness.LATE_CHANCE = 1.0
c = person()
w = world_at()
check("a late start holds them at first", lateness.holds_start(c, w, "work", random.Random(1)))
rec = c["_late_starts"]["work"]
check("... it is pending after the usual start time", lateness.start_pending(c, w, "work"))
w["tick"] = rec["until_tick"] - 1
check("... still holding a moment before", lateness.holds_start(c, w, "work"))
w["tick"] = rec["until_tick"]
check("... and released when the time is up", not lateness.holds_start(c, w, "work"))
lateness.departed(c, w, "work")
check("the trip keeps what the lateness was", c["_trip_late"]["start"]["minutes"] == rec["minutes"] and c["_trip_late"]["kind"] == "work")
check("it is not rolled again that day", not lateness.holds_start(c, w, "work") and not lateness.start_pending(c, w, "work"))
w["calendar"]["day"] = 11
check("the next day it is rolled afresh", lateness.holds_start(c, w, "work", random.Random(2)))

# two appointments the same day are told apart
c = person()
w = world_at()
lateness.holds_start(c, w, "appt", random.Random(1), key="appt:1")
lateness.departed(c, w, "appt", key="appt:1")
check("a second appointment is rolled on its own", lateness.holds_start(c, w, "appt", random.Random(1), key="appt:2") or c["_late_starts"]["appt:2"]["minutes"] == 0)

# ---- running over ------------------------------------------------------------------------------------------------------------------------
c = person()
w = world_at(hour=17)
c["off_grid"], c["off_grid_reason"], c["return_tick"] = True, "work", w["tick"]
lateness.departed(c, w, "work")
check("a shift that ends is held up", lateness.holds_end(c, w, "work", random.Random(3)))
over = c["_trip_late"]["over"]
check("... the return tick moves out by the minutes", c["return_tick"] == w["tick"] + over["minutes"] * 60)
w["tick"] = over["until_tick"]
check("... and lets go when the time is up", not lateness.holds_end(c, w, "work"))
late_rec = lateness.finish(c, w)
check("the story gets the delay and the reason", late_rec["over"]["minutes"] == over["minutes"] and over["reason"] in lateness.note(late_rec))
check("... and dinner is told how late they got home", lateness.late_home_today(c, w) == over["minutes"] and "_trip_late" not in c)
w["calendar"]["day"] = 11
check("... for that day only", lateness.late_home_today(c, w) == 0)

lateness.LATE_CHANCE = 0.0
c = person()
w = world_at()
lateness.departed(c, w, "work")
check("with no delay the trip is not held and tells nothing", not lateness.holds_end(c, w, "work") and lateness.finish(c, w) is None)
lateness.LATE_CHANCE = always

# the work departure and the end of the shift through offgrid.py
lateness.LATE_CHANCE = 1.0
c = person(employed=True, job={"title": "Clerk"}, schedule={"week": {"tuesday": [{"start": "09:00", "end": "17:00", "activity": "work"}]}})
w = world_at(hour=9, minute=0)
w["characters"]["a"] = c
offgrid.maybe_go_offgrid(c, w)
check("a character due at work at nine, running late, is still at home", not c.get("off_grid") and lateness.start_pending(c, w, "work"))
w["tick"] = c["_late_starts"]["work"]["until_tick"]
w["calendar"].update(minute_of_day=9 * 60 + 40, minute=40)
check("... the work block is still open after the usual ten minutes", offgrid._work_block_open(c, w))
lateness.LATE_CHANCE = always

# ---- the summary ---------------------------------------------------------------------------------------------------------------------------
w = world_at(hour=17, minute=45)
late_rec = {"start": {"minutes": 25, "reason": "the bus was late"}, "over": {"minutes": 40, "reason": "a meeting ran over"}}
s = build_summary(person(job={"title": "Clerk"}), w, "work", "Worked.", w["tick"] - 8 * 3600, w["tick"], beats=[], lateness=late_rec)
keys = list(s["key_events"])
check("the key events open with the late arrival and close with the hold-up", keys[0] == "Arrived late" and keys[-1] == "Held up at the end", str(keys))
check("... each with its reason", "bus was late" in s["key_events"]["Arrived late"]["note"] and "meeting ran over" in s["key_events"]["Held up at the end"]["note"])
check("... and every event lies within the trip", all(s["start_tick"] <= e["start_tick"] <= e["stop_tick"] <= s["end_tick"] for e in s["key_events"].values()))
s2 = build_summary(person(job={"title": "Clerk"}), w, "work", "Worked.", w["tick"] - 8 * 3600, w["tick"], beats=[])
check("a normal day has neither", "Arrived late" not in s2["key_events"] and "Held up at the end" not in s2["key_events"])

# ---- dinner -------------------------------------------------------------------------------------------------------------------------------
def household_for_dinner():
    h = {"id": "h", "members": ["a"], "building_ids": ["home"], "storage": {"resources": []}, "_stock_named": True}
    for tid, n in dict(ground_beef=6, pasta=6, tomato=6, salt=4, chicken=6, rice=6, broccoli=6, herbs=2, cheese=3).items():
        cookware.add_stock(h, tid, n)
    return h


def cook_share(setup, trials=300):
    n = 0
    for i in range(trials):
        w = world_at(hour=17, minute=30)
        c = person()
        setup(c, w)
        n += fh.dinner_mode(c, w, household_for_dinner(), random.Random(i)) == "cook"
    return n / trials


calm = cook_share(lambda c, w: None)
late_home = cook_share(lambda c, w: c.update(late_home={"day": (2026, 3, 10), "minutes": 55, "reason": "x"}))
ill = cook_share(lambda c, w: c["body"].update(sickness=45))
tired = cook_share(lambda c, w: c["body"].update(energy=5))
a_bit_late = cook_share(lambda c, w: c.update(late_home={"day": (2026, 3, 10), "minutes": 10, "reason": "x"}))
check("a calm, rested, healthy person cooks", calm > 0.95, str(calm))
check("getting home an hour late makes takeout likelier", late_home < calm - 0.5, f"{late_home} vs {calm}")
check("... ten minutes late hardly changes it", a_bit_late > late_home and a_bit_late > 0.85, str(a_bit_late))
check("being ill does", ill < calm - 0.5, str(ill))
check("so does running on empty", tired < calm - 0.5, str(tired))

c = person(money=100)
w = world_at(hour=17, minute=30)
h = household_for_dinner()
check("calm, with food in the house and nothing ready, they would not order in", fh.easy_choice(c, w, h) in ("takeout", "processed", "snack"))
c["late_home"] = {"day": (2026, 3, 10), "minutes": 60, "reason": "x"}
c["body"]["sickness"] = 40
from systems import ready_meals
ready_meals.add(h, "frozen_pizza", w["tick"], 2)
check("late and ill with a freezer meal at home, they still order in", fh.easy_choice(c, w, h) == "takeout")
c["money"] = 5
check("... unless they cannot afford it", fh.easy_choice(c, w, h) == "processed")

pts, why = fh.strain(c, w)
check("the reasons are named", pts > 0 and any("late" in x for x in why) and any("ill" in x for x in why), str(why))

# the planner picks the better-off adult and records why
h = household_for_dinner()
h["members"] = ["a", "b"]
a = person("a", late_home={"day": (2026, 3, 10), "minutes": 60, "reason": "x"})
b = person("b")
w = world_at(hour=17, minute=30, weekday="Tuesday")
w["households"]["h"] = h
w["characters"] = {"a": a, "b": b}
dinner.plan(w, random.Random(1))
check("with one of them late home, the other cooks", h["dinner_mode"]["cook"] == "b", str(h["dinner_mode"]))
h2 = household_for_dinner()
w2 = world_at(hour=17, minute=30, weekday="Tuesday")
solo = person("a", late_home={"day": (2026, 3, 10), "minutes": 60, "reason": "got held up"})
h2["members"] = ["a"]
w2["households"]["h"] = h2
w2["characters"] = {"a": solo}
dinner.plan(w2, random.Random(1))
check("the household record says why", "why" in h2["dinner_mode"] and any("late" in x for x in h2["dinner_mode"]["why"]), str(h2["dinner_mode"]))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
