"""
Make Things Right and Check On Someone (brain/actionplans): find the person, then the model says it.

Live (2026-11-09, 24h runs): every apologize_to and suggest_hygiene went red and was never done -- they waited for the
model to choose to go and find someone, and it rarely did. Now: the person is right here -> wake the model with what
they came to say, and wait until they have spoken to them; somewhere else -> walk over first; away -> blocked, says so.
Only the intention about that person is cleared.

Run inside the backend container:   python tests/test_make_things_right.py
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
check("apologies and checking on someone are live",
      runner.live_intention_for({}, "apologize_to")["id"] == "make_things_right"
      and runner.live_intention_for({}, "suggest_hygiene")["id"] == "check_on_someone"
      and runner.live_intention_for({}, "go_to_sleep")["id"] == "restore_energy")


def world():
    w = make_world()
    w["tick"] = 40000
    w["calendar"] = {"year": 2026, "month": 11, "day": 2, "hour": 14, "minute": 0, "second": 0, "minute_of_day": 840, "weekday": "Monday"}
    ensure_world_defaults(w)
    w["conversations"] = {}
    for c in w["characters"].values():
        c["activity"] = None
        c["traits"] = ["impulsive"]
    return w


def steps(c, iid="make_things_right"):
    att = (c.get("plan_attempts") or {}).get(iid) or ((c.get("plan_log") or [{}])[-1])
    return [(t.get("plan"), t.get("node"), t.get("what"), t.get("out")) for t in att.get("trace") or []]


SORRY = {"type": "apologize_to", "category": "social", "priority": 42, "target_id": "kathleen", "reason": "still upset"}

# right here: the model is woken with it, then it is met once they've spoken
w = world()
rob, k = w["characters"]["robert"], w["characters"]["kathleen"]
rob["room_id"] = k["room_id"] = "starter_house_2:kitchen_0"
rob["active_intentions"] = [dict(SORRY), {"type": "apologize_to", "category": "social", "priority": 42, "target_id": "susan", "reason": "x"}]
res = runner.autopilot(rob, w, rob["active_intentions"][0])
cog = rob.get("cognition") or {}
check("Kathleen is right here: the model is woken to say it", cog.get("wake_reason") == "social_purpose"
      and "apologise to Kathleen" in (cog.get("wake_payload") or {}).get("line", ""), str(cog))
check("... and the plan waits for them to have said something to her", res == "busy"
      and ((rob["plan_attempts"].get("make_things_right") or {}).get("wait") or {}).get("node") == "said", str(steps(rob)))
w["conversations"]["c1"] = {"participants": ["robert", "kathleen"], "history": [{"speaker": "robert", "tick": w["tick"] + 5, "text": "I'm sorry."}]}
w["tick"] += 60
runner._on_wait_timer(w, {"owner": "planwait:robert", "key": "make_things_right"})
check("... once he has: met", rob["plan_log"][-1]["status"] == "satisfied", str(steps(rob)[-3:]))
check("... and only the apology to Kathleen is cleared (the one to Susan stays)",
      [i.get("target_id") for i in rob["active_intentions"] if i.get("type") == "apologize_to"] == ["susan"], str(rob["active_intentions"]))

# somewhere else: walk over first
w = world()
rob, s = w["characters"]["robert"], w["characters"]["susan"]
rob["room_id"], s["room_id"] = "starter_house_2:kitchen_0", "starter_house_3:kitchen_0"
res = runner.autopilot(rob, w, dict(SORRY, target_id="susan"))
check("Susan is in her own house: he walks over", rob.get("move_target", {}).get("target_id") == "susan"
      and ("make_amends", "go", "action", "done") in steps(rob), f"{rob.get('move_target')} {steps(rob)}")

# away: blocked, and says so
w = world()
rob, s = w["characters"]["robert"], w["characters"]["susan"]
s["off_grid"] = True
runner.autopilot(rob, w, dict(SORRY, target_id="susan"))
check("Susan is away: blocked, 'they're away'", rob["plan_log"][-1]["status"] == "blocked" and "away" in rob["plan_log"][-1]["why"],
      str(rob["plan_log"][-1]))

# check on someone: the same, with its own words
w = world()
rob, k = w["characters"]["robert"], w["characters"]["kathleen"]
rob["room_id"] = k["room_id"] = "starter_house_2:kitchen_0"
runner.autopilot(rob, w, {"type": "suggest_hygiene", "category": "social", "priority": 35, "target_id": "kathleen", "reason": "smells"})
line = ((rob.get("cognition") or {}).get("wake_payload") or {}).get("line", "")
check("smelly Kathleen: woken to tactfully suggest a shower", "shower" in line and "Kathleen" in line, line)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
