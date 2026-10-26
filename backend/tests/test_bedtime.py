"""
Bedtime on a night before a work or school day (systems/bedtime.py) and the spawn-time settling (systems/spawn_setup.py).

Run inside the backend container:   python tests/test_bedtime.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from db import load_definitions
from systems import bedtime as bt
from systems.body_intentions import generate_body_intentions
from systems.character_gen import generate_character
from systems.spawn_setup import settle_new_character, hours_since_waking

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def world(day, hour, minute=0):
    return {"tick": 1000, "calendar": {"weekday": day, "hour": hour, "minute": minute}, "characters": {}, "households": {}}


def worker(start="08:00", days=("monday", "tuesday", "wednesday", "thursday", "friday"), asleep_block=True, **extra):
    week = {d: [{"start": "23:00", "end": "07:00", "activity": "sleep"}] + ([{"start": start, "end": "16:00", "activity": "work"}] if d in days else [])
            for d in bt.WEEKDAYS}
    c = {"id": "w", "name": "Worker", "age": 35, "traits": [], "schedule": {"week": week}, "body": {"fatigue": 30, "hours_awake": 17},
         "active_intentions": [], "job": {"id": "clerk"}}
    if asleep_block:
        c["active_schedule_block"] = {"start": "23:00", "end": "07:00", "activity": "sleep"}
    c.update(extra)
    return c


# ---- the rule ------------------------------------------------------------------------------------------------------------------
check("Sunday 23:30: Monday is a work day, go to bed", bt.wants_bed(worker(), world("sunday", 23, 30)))
check("Monday 00:47 (already Monday): go to bed", bt.wants_bed(worker(), world("monday", 0, 47)))
check("Thursday night, Friday is a work day", bt.wants_bed(worker(), world("thursday", 23, 10)))
check("Friday night: Saturday is free, no bedtime from this rule", not bt.wants_bed(worker(), world("friday", 23, 30)))
check("Saturday 01:00 (Saturday morning is free)", not bt.wants_bed(worker(), world("saturday", 1, 0)))
check("Saturday night: Sunday is free", not bt.wants_bed(worker(), world("saturday", 23, 30)))
check("not in the middle of the day", not bt.wants_bed(worker(asleep_block=False, active_schedule_block={"activity": "work"}), world("monday", 11)))
check("a shift that starts in the evening is not a daytime job", not bt.wants_bed(worker(start="20:00"), world("monday", 23, 30)))
check("a worker whose schedule has no job tomorrow stays up", not bt.wants_bed(worker(days=("wednesday",)), world("monday", 23, 30)))
check("already asleep: nothing to add", not bt.wants_bed(worker(activity={"type": "sleep"}), world("monday", 23, 30)))
check("away from the grid", not bt.wants_bed(worker(off_grid=True), world("monday", 23, 30)))
retired = worker(job={"id": "retired"}, schedule={"week": {d: [{"start": "23:00", "end": "07:00", "activity": "sleep"}] for d in bt.WEEKDAYS}})
check("someone with no job and no school has no daytime obligation", not bt.wants_bed(retired, world("monday", 23, 30)))
kid = worker(age=9, current_school="riverside_primary", job={}, schedule={"week": {d: [{"start": "23:00", "end": "07:00", "activity": "sleep"}] for d in bt.WEEKDAYS}})
check("a school child goes to bed before a school day", bt.wants_bed(kid, world("sunday", 22 + 1, 15)))
check("... but not before a Saturday", not bt.wants_bed(kid, world("friday", 23, 15)))
noschedule = {"id": "n", "age": 30, "job": {"id": "clerk"}, "active_intentions": []}
check("with no schedule yet, the clock decides it is night and a weekday counts", bt.wants_bed(noschedule, world("tuesday", 23, 30)))
check("... and by day it does not", not bt.wants_bed(noschedule, world("tuesday", 14, 0)))

# ---- the intention ------------------------------------------------------------------------------------------------------------------
c = worker()
generate_body_intentions(c, world("sunday", 23, 30))
sleep = next((i for i in c["active_intentions"] if i["type"] == "sleep"), None)
check("the body intentions add a sleep intention for bedtime", sleep and sleep["reason"] == "bedtime" and sleep["priority"] >= 70, str(sleep))
c = worker()
generate_body_intentions(c, world("friday", 23, 30))
check("none on a Friday night", not any(i["type"] == "sleep" for i in c["active_intentions"]))
c = worker(body={"fatigue": 95, "hours_awake": 40})
generate_body_intentions(c, world("friday", 23, 30))
sleep = next((i for i in c["active_intentions"] if i["type"] == "sleep"), None)
check("real exhaustion still sends them, whatever the day", sleep and sleep["reason"] == "exhausted", str(sleep))
c = worker(body={"fatigue": 95, "hours_awake": 40})
generate_body_intentions(c, world("sunday", 23, 30))
sleep = next(i for i in c["active_intentions"] if i["type"] == "sleep")
check("and bedtime does not downgrade it", sleep["reason"] == "exhausted" and sleep["priority"] >= 90, str(sleep))

# ---- settling ----------------------------------------------------------------------------------------------------------------------------
defs = load_definitions("default")


def fresh(age=35, **overrides):
    return generate_character(defs, dict({"age": age}, **overrides))


w = world("monday", 0, 47)
w["definitions"] = defs
adult = fresh(job={"id": "x"})                                # (an override job is kept for an adult)
w["characters"][adult["id"]] = adult
adult["job"] = {"id": "clerk", "title": "Clerk"}
adult["schedule"] = None
done = settle_new_character(w, adult)
check("a schedule is made", done["schedule_days"] == 7 and len(adult["schedule"]["week"]) == 7)
check("the current block is known: it is their sleep time", done["block"] == "sleep" and adult["active_schedule_block"]["activity"] == "sleep", str(done))
check("the body clock fits the time of day: awake about 17-18 hours at 00:47", 16.5 <= done["hours_awake"] <= 18.5, str(done["hours_awake"]))
check("with the fatigue that goes with it", adult["body"]["fatigue"] >= 30, str(adult["body"]["fatigue"]))
bedtime_due = bt.has_daytime_obligation(adult, "monday")
check("and, with a working day ahead, bed first", done["bedtime"] == bedtime_due, f"{done} {bedtime_due}")
before = adult["body"]["fatigue"]
settle_new_character(w, adult)
check("running it again does not lower fatigue", adult["body"]["fatigue"] >= before)

w2 = world("monday", 10, 0)
w2["definitions"] = defs
morning = fresh()
w2["characters"][morning["id"]] = morning
done2 = settle_new_character(w2, morning)
check("spawned mid-morning: awake about 3 hours, not tired, no bedtime", 2.5 <= done2["hours_awake"] <= 3.5 and not done2["bedtime"], str(done2))

w3 = world("sunday", 23, 40)
w3["definitions"] = defs
child = fresh(age=9)
w3["characters"][child["id"]] = child
done3 = settle_new_character(w3, child)
check("a school child spawned on a Sunday night is sent to bed", done3["bedtime"], str(done3))
check("hours since waking before the wake hour counts from yesterday", abs(hours_since_waking(adult, world("monday", 0, 30)) - 17.5) < 1.1)

# ---- no outings at bedtime ---------------------------------------------------------------------------------------------------------------
from unittest import mock
import systems.offgrid as og
sent = []
c = worker(employed=True)
with mock.patch.object(og, "send_offgrid", lambda *a, **k: sent.append(a)), mock.patch.object(og, "send_offgrid_chain", lambda *a, **k: sent.append(a)):
    og.maybe_go_offgrid(c, world("sunday", 23, 30))
check("nobody is sent off on an errand or outing at bedtime before a work day", not sent and not c.get("off_grid"), str(sent))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
