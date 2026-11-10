"""
Prepare for an Event, Spend Time Alone, Unwind with Someone (brain/actionplans).

Live (2026-11-09, 24h runs): all three were open all day and never done -- nothing could satisfy them. Now:
  - an event reminder is taken note of (remembered, with what it needs) once per reminder band, and not raised again until
    the event moves into the next one (systems/calendar_events.py)
  - alone in a room they take some time to themselves; otherwise they go to their own room first, and wait for it to be free
  - in the evening they ask their partner (or another grown-up at home) to sit down with them, and both do

Run inside the backend container:   python tests/test_events_alone_unwind.py
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

data = store.load()
errors = [p for p in checker.check(data, load_definitions("default")) if p["level"] == "error"]
check("the behaviour definitions pass the path checker", not errors, str(errors[:3]))


def world(hour=14):
    w = make_world()
    w["tick"] = 40000
    w["calendar"] = {"year": 2026, "month": 11, "day": 2, "hour": hour, "minute": 0, "second": 0, "minute_of_day": hour * 60,
                     "weekday": "Monday"}
    ensure_world_defaults(w)
    for c in w["characters"].values():
        c["activity"] = None
        c["traits"] = ["impulsive"]
        c["age"], c["age_group"] = 35, "adult"
        c.setdefault("body", {})
    return w


def steps(c, iid):
    att = (c.get("plan_attempts") or {}).get(iid) or ((c.get("plan_log") or [{}])[-1])
    return [(t.get("plan"), t.get("node"), t.get("what"), t.get("out")) for t in att.get("trace") or []]


# ---- Prepare for an Event ------------------------------------------------------------------------------------------
w = world()
j = w["characters"]["joseph"]
ev = {"type": "prepare_for_event", "priority": 40, "source": "calendar", "event_id": "bday_susan", "event_name": "Susan's birthday",
      "occasion": "birthday", "days_until": 12, "band_days": 14, "prep_requirements": ["buy_gift", "send_card"]}
j["active_intentions"] = [dict(ev), {"type": "buy_gift", "event_id": "bday_susan", "priority": 45}]
runner.autopilot(j, w, j["active_intentions"][0])
mem = " ".join(m.get("content") or m.get("text") or "" for m in j.get("memories") or [])
check("an event two weeks off: taken note of, with what it needs, and met",
      j["plan_log"][-1]["status"] == "satisfied" and "Susan's birthday is in 12 days" in mem and "buy gift" in mem,
      f"{j['plan_log'][-1]} {mem[:200]}")
check("... the concrete task (the gift) stays", [i["type"] for i in j["active_intentions"]] == ["buy_gift"], str(j["active_intentions"]))
from systems import calendar_events as ce
e2 = {"id": "bday_susan", "name": "Susan's birthday", "type": "birthday", "days_until": 11, "prep_requirements": ["buy_gift"],
      "for_char_id": "susan"}
j["active_intentions"] = []
ce._inject_intentions_for_event(j, e2)
check("... the next day, same band: not raised again", not any(i["type"] == "prepare_for_event" for i in j["active_intentions"]))
ce._inject_intentions_for_event(j, dict(e2, days_until=6))
check("... a week off (the next band): raised again", any(i["type"] == "prepare_for_event" and i.get("band_days") == 7
                                                          for i in j["active_intentions"]), str(j["active_intentions"]))

# ---- Spend Time Alone ----------------------------------------------------------------------------------------------
ALONE = {"type": "expectation:spend_time_alone", "category": "leisure", "priority": 25, "reason": "time to yourself"}


def with_expectation(c, eid):
    c["expectations"] = {eid: {"template_id": eid, "status": "pending", "streak": 0, "frustration": 0, "missed_count": 0}}


w = world()
j = w["characters"]["joseph"]
with_expectation(j, "spend_time_alone")
res = runner.autopilot(j, w, dict(ALONE))
check("alone in the room: some time to themselves, right there", res == "started" and j["activity"]["type"] == "time_to_myself",
      f"{res} {steps(j, 'spend_time_alone')}")
from systems.activities import complete_activity
j["stress"] = 40
complete_activity(j, w, j["activity"])
j["activity"] = None
runner.on_activity_end({"character_id": "joseph", "activity_type": "time_to_myself"}, w, "done")
check("... a bit less stressed, and the weekly expectation is met",
      j["stress"] < 40 and j["expectations"]["spend_time_alone"]["status"] == "satisfied", str(j["expectations"]))

w = world()
rob, k = w["characters"]["robert"], w["characters"]["kathleen"]
k["x"], k["y"] = rob["x"], rob["y"]                    # Kathleen right beside him
with_expectation(rob, "spend_time_alone")
runner.autopilot(rob, w, dict(ALONE))
check("someone in the room: off to his own room first", ("time_to_myself", "go", "action", "done") in steps(rob, "spend_time_alone")
      and str((rob.get("move_target") or {}).get("target_id", "")).startswith("room:"), f"{rob.get('move_target')} {steps(rob, 'spend_time_alone')}")

# ---- Unwind with Someone -------------------------------------------------------------------------------------------
UNWIND = {"type": "expectation:relax_with_someone", "category": "leisure", "priority": 30, "reason": "unwind"}
w = world(hour=14)
rob, k = w["characters"]["robert"], w["characters"]["kathleen"]
with_expectation(rob, "relax_with_someone")
check("in the afternoon: not yet", runner.autopilot(rob, w, dict(UNWIND)) == "busy" and not rob.get("plan_log"))

w = world(hour=20)
rob, k = w["characters"]["robert"], w["characters"]["kathleen"]
rob["relationships"] = {"kathleen": {"labels": ["spouse"]}}
k["building_id"] = rob["building_id"]
with_expectation(rob, "relax_with_someone")
res = runner.autopilot(rob, w, dict(UNWIND))
check("the evening: he asks his wife to sit with him, and they both sit down",
      (k.get("activity") or {}).get("type") == "sit_and_relax" and res == "started" and rob["activity"]["type"] == "sit_and_relax",
      f"{res} k={k.get('activity')} {steps(rob, 'unwind_with_someone')}")
rob["activity"] = None
runner.on_activity_end({"character_id": "robert", "activity_type": "sit_and_relax"}, w, "done")
check("... and afterwards it is met", rob["expectations"]["relax_with_someone"]["status"] == "satisfied", str(steps(rob, "unwind_with_someone")[-3:]))

w = world(hour=20)
rob, k = w["characters"]["robert"], w["characters"]["kathleen"]
k["off_grid"] = True
with_expectation(rob, "relax_with_someone")
runner.autopilot(rob, w, dict(UNWIND))
check("nobody home to unwind with, and no friend to visit: blocked, says so", rob["plan_log"][-1]["status"] == "blocked"
      and "nobody" in rob["plan_log"][-1]["why"], str(rob["plan_log"][-1]))

# nobody at home, but a friend next door is home and free: go round
w = world(hour=20)
rob, k, j = w["characters"]["robert"], w["characters"]["kathleen"], w["characters"]["joseph"]
k["off_grid"] = True
rob["relationships"] = {"joseph": {"labels": ["friend"], "affection": 40}}
with_expectation(rob, "relax_with_someone")
runner.autopilot(rob, w, dict(UNWIND))
check("nobody at home, his friend Joseph is home next door: he goes round",
      (rob.get("move_target") or {}).get("target_id") == "joseph" and ("visit_a_friend", "go", "action", "done") in steps(rob, "unwind_with_someone"),
      f"{rob.get('move_target')} {steps(rob, 'unwind_with_someone')}")

# an event reminder now has a category: pressing once it has waited (systems/todo.py)
j = world()["characters"]["joseph"]
j["active_intentions"] = []
ce._inject_intentions_for_event(j, dict(e2, days_until=20))
pi = next(i for i in j["active_intentions"] if i["type"] == "prepare_for_event")
from systems.todo import tier
check("an event reminder is 'household': when there is time at first, pressing once it has waited",
      pi.get("category") == "household" and tier(pi) == "when_free" and tier(dict(pi, stage=1)) == "pressing", str(pi))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
