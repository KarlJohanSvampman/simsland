"""
Route plans are recorded (systems/path_debug.py), and a real failure to find a way puts the character into a short,
noticeable "lost" psychotic episode.

Run inside the backend container:   python tests/test_path_debug.py
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
from core import scheduler
from systems import path_debug
from systems.navigation import plan_character_route

w = make_world()
w["tick"] = 90000
r = w["characters"]["robert"]
r.update(x=60, y=8, building_id="starter_house_2", memories=[], route=[])

check("a route to the kitchen is planned", plan_character_route(w, r, 58, 4))
p = r["path_plans"][-1]
check("... and recorded: from, to, ok, how many tiles", p["ok"] and p["reason"] == "ok" and p["tiles"] > 0
      and p["from"] == [60, 8] and p["to"] == [58, 4], str(p))

check("to where he already stands: no route, but not a failure", not plan_character_route(w, r, 60, 8)
      and r["path_plans"][-1]["reason"] == "already_there" and not (r.get("psychosis_state") or {}).get("active"))

w["outdoor_navigation"] = {}                     # nowhere to walk outdoors
with path_debug.probing():
    plan_character_route(w, r, 85, 6)
check("a probe that finds no way (picking a spot to roam to) raises no alarm",
      not (r.get("psychosis_state") or {}).get("active"))

check("to the Moreaus' with no way there: no route", not plan_character_route(w, r, 85, 6))
check("... recorded as why", r["path_plans"][-1]["reason"] == "no_outdoor_path", str(r["path_plans"][-1]))
st = r.get("psychosis_state") or {}
check("... and he's thrown into a short 'lost' psychotic episode", st.get("active") and st.get("trigger") == "no_path",
      str(st))
check("... saying so out loud", "can't find the way" in (r.get("current_speech") or {}).get("utterance", ""))
check("... and remembering it", any("couldn't find any way" in m["text"] for m in r["memories"]))

r["current_speech"] = None
plan_character_route(w, r, 85, 6)
check("failing again right away doesn't start another episode", not r.get("current_speech"))

w["tick"] += path_debug.EPISODE_TICKS + 1
scheduler.fire_due(w)
check("ten minutes on, the episode is over", not (r.get("psychosis_state") or {}).get("active"))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
