"""
The at-home "work" action is gone (it stood a character still for up to 8 hours with no effect -- live 2026-11-01: Carol
Lindqvist, 14, no job, 5+ sim-hours in). Going to work is the scheduled off-grid shift: systems/offgrid.py::go_to_work.

Run inside the backend container:   python tests/test_no_work_action.py
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


from house_world import make_world                    # the live 3-household world, rebuilt offline
from systems import lateness
from systems.offgrid import go_to_work, maybe_go_offgrid
from systems.action_router import _route_work
from systems.activity_watchdog import check_activity_watchdog

lateness.holds_start = lambda *a, **k: False          # nobody runs late in this test (it's a random roll)


def at(world, weekday, hh, mm):
    world["calendar"] = {"year": 2026, "month": 11, "day": 2, "hour": hh, "minute": mm, "second": 0,
                         "minute_of_day": hh * 60 + mm, "weekday": weekday}
    return world


def robert(world):
    c = world["characters"]["robert"]
    c.update(employed=True, age=41, age_group="adult", job={"title": "Stripper"}, legal={},
             schedule={"week": {"monday": [{"activity": "work", "start": "09:00", "end": "12:00"}]}})
    return c


world = at(make_world(), "Monday", 8, 30)
r = robert(world)
check("before the shift: not going yet", go_to_work(r, world) is False and not r.get("off_grid"))
at(world, "Monday", 9, 0)
maybe_go_offgrid(r, world)
check("at the start of the work block they go off-grid for work", r.get("off_grid") is True and r.get("off_grid_reason") == "work",
      str((r.get("off_grid"), r.get("off_grid_reason"), r.get("travel_state"))))

world = at(make_world(), "Monday", 10, 15)
r = robert(world)
_route_work(r, world)
check("a model that still says \"work\" during the shift sends them off", r.get("off_grid") is True and r.get("off_grid_reason") == "work")

world = at(make_world(), "Monday", 13, 0)
r = robert(world)
_route_work(r, world)
check("... after the shift: nothing starts, no 8-hour stand", not r.get("off_grid") and not (r.get("activity") or {}).get("type"))

world = at(make_world(), "Sunday", 13, 0)
carol = world["characters"]["kathleen"]
carol.update(employed=False, age=14, age_group="teen")
_route_work(carol, world)
check("no job: nothing starts", not carol.get("off_grid") and not (carol.get("activity") or {}).get("type"))
log = [m for m in carol.get("memories", []) if "debug_event" in (m.get("tags") or [])]
check("... and the memory log says why", log and "no job to go to" in log[-1]["text"], log and log[-1]["text"])

carol["activity"] = {"type": "work", "interaction": "work", "phase": "using", "phase_started_tick": world["tick"] - 19767,
                     "duration": 28800}
check("someone stuck in the old at-home \"work\" is released", check_activity_watchdog(carol, world) and not carol.get("activity"))

from brain.context_builder import build_available_actions
carol["perception"] = {}
check("\"work\" isn't on the menu any more", "work" not in build_available_actions(carol, world).get("action_types", []))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
