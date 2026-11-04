"""
"sleep" means going to bed (systems/action_router.py::_route_sleep): live (2026-11-04), Robert Okafor lay down and
slept on the restroom floor -- the sleep action started right where he stood.

Run inside the backend container:   python tests/test_sleep_in_bed.py
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
from systems.action_router import _route_sleep
from systems.room_assignment import refresh_character_room
from systems.schema_defaults import ensure_prop_template_fields

w = make_world()
w["tick"] = 5000
w["props"] = [{"id": "bed", "template": "bed_double_a", "x": 64, "y": 10, "state": {}, "rotation": 0,
               "building_id": "starter_house_2"}]
ensure_prop_template_fields(w, w["definitions"])
r = w["characters"]["robert"]
r.update(x=63, y=6, building_id="starter_house_2", activity=None, route=[], is_moving=False, posture="standing", age=41)
refresh_character_room(r, w)

_route_sleep(r, w, {"type": "sleep"})
a = r.get("activity") or {}
check("in the restroom, choosing to sleep: he walks to the bed", a.get("type") == "sleep" and a.get("phase") == "walking"
      and a.get("target_id") == "bed" and r.get("is_moving"), str(a))
check("... and doesn't lie down on the spot", r.get("posture") != "lying")
check("... sleeping as long as tonight calls for", a.get("duration", 0) > 3600)

w["props"] = []
r.update(activity=None, posture="standing", is_moving=False, route=[])
_route_sleep(r, w, {"type": "sleep"})
check("no bed anywhere: he still sleeps (where he is)", (r.get("activity") or {}).get("type") == "sleep")

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
