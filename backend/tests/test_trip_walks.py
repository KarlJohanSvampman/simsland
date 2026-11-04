"""
The walk part of a trip -- to the bus stop, to the garage, home -- actually walks (systems/travel.py::_set_off), a stalled
one is re-routed or given up on by its step timeout (systems/step_timeouts.py), and none takes longer than WALK_MAX_TICKS.

Live (2026-11-01): Robert and Stephanie Okafor "walking to the bus stop" for hours without moving: the route was planned
but is_moving was never set, and movement only advances characters that are moving.

Run inside the backend container:   python tests/test_trip_walks.py
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
from systems import travel
from systems import step_timeouts
from systems.step_timeouts import WALK_MAX_TICKS, STALL_TICKS
from core import scheduler
from systems.movement import update_character_movement
from systems.navigation import find_building_at

travel.choose_travel_mode = lambda c, world: "bus"


def setup():
    w = make_world()
    w["tick"] = 40000
    w["props"] = [{"id": "bus_stop_1", "template": "bus_stop_a", "x": 8, "y": 11, "state": {}}]
    r = w["characters"]["robert"]
    r.update(x=60, y=8, building_id="starter_house_2", route=[], is_moving=False, travel_state=None, activity=None,
             legal={}, off_grid=False)
    return w, r


def run(w, c, ticks, move=True):
    for _ in range(ticks):
        w["tick"] += 1
        scheduler.fire_due(w)
        step_timeouts.note_step(c, w)              # what agent_loop.update_agent does each tick
        if move and c.get("is_moving"):
            update_character_movement(c, w)
        travel.update_travel(c, w)
        if c.get("travel_state") not in travel.TRAVEL_WALKING_STATES:
            return


w, r = setup()
travel.begin_travel(r, w, "shopping", 45)
check("setting off for the bus: walking, not standing", r.get("travel_state") == "to_bus_stop" and r.get("is_moving") is True)
run(w, r, WALK_MAX_TICKS)
check("... reaches the bus stop and waits for the bus", r.get("travel_state") == "waiting_for_bus"
      and abs(r["x"] - 8) < 1 and abs(r["y"] - 11) < 1, str((r.get("travel_state"), r["x"], r["y"])))

w, r = setup()
r.update(travel_state="to_bus_stop", travel_mode="bus", _pending_offgrid={"reason": "driving_lesson", "duration": 65},
         route=[{"type": "indoor", "tiles": [[60, 7], [60, 6]], "building_id": "starter_house_2"},
                {"type": "outdoor", "tiles": [[59, 5], [59, 6], [59, 7], [59, 8], [59, 9], [59, 10], [58, 10], [57, 10]]}],
         route_segment_index=0, is_moving=False)
run(w, r, STALL_TICKS + 2)
check("Robert's live state (an old route, not moving): after 3 minutes without progress, re-routed and walking",
      r.get("is_moving") is True and r.get("travel_state") == "to_bus_stop")
check("... and that is reported in his memory log", any("stuck" in (m.get("tags") or []) for m in r.get("memories", [])))
run(w, r, WALK_MAX_TICKS)
check("... and gets to the bus stop", r.get("travel_state") == "waiting_for_bus", str(r.get("travel_state")))

w, r = setup()
w["props"] = [{"id": "bus_stop_1", "template": "bus_stop_a", "x": 8, "y": 11, "state": {}}]
r.update(travel_state="to_bus_stop", travel_mode="bus", _pending_offgrid={"reason": "shopping", "duration": 45},
         route=[{"type": "outdoor", "tiles": [[59, 5]]}], is_moving=False)
w["outdoor_navigation"] = {}                       # nowhere to walk: no route can be found
for _t in w.get("world_tile_lookup", {}).values():
    _t["walkable"] = False
run(w, r, STALL_TICKS + 2)
check("no route at all: the trip happens without the walk", r.get("off_grid") is True
      and r.get("off_grid_reason") == "shopping" and not r.get("travel_state"), str((r.get("off_grid"), r.get("travel_state"))))

w, r = setup()
r.update(travel_state="to_bus_stop", travel_mode="bus", _pending_offgrid={"reason": "shopping", "duration": 45},
         route=[{"type": "outdoor", "tiles": [[59, 5]]}], is_moving=True)
run(w, r, 2 * STALL_TICKS + 4, move=False)       # never actually moves (stuck in place)
check("stuck in place: one fresh route after 3 minutes, still stuck 3 minutes later -> given up: straight off-grid",
      r.get("off_grid") is True and not r.get("travel_state"))

w, r = setup()
r.update(x=8, y=11, building_id=None, travel_mode="bus")
travel._begin_walking_home(r, w)
check("back from the bus: walking home", r.get("travel_state") == "walking_home" and r.get("is_moving") is True,
      str((r.get("travel_state"), r.get("is_moving"))))
run(w, r, WALK_MAX_TICKS)
check("... and ends up inside the house", not r.get("travel_state")
      and (find_building_at(w, r["x"], r["y"])[0] or {}).get("id") == "starter_house_2", str((r["x"], r["y"])))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
