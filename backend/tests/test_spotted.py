"""
Knowing what's around, not only what's in view (systems/spotted.py).

Since walls block sight, a hungry character in the bedroom no longer saw the fridge. Now: their own home is familiar,
elsewhere they remember what they happened to notice, and what they need brings the right things to mind -- which
can then be named as targets even out of sight (they walk there first).

Run inside the backend container:   python tests/test_spotted.py
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


import random
from house_world import make_world
from brain.perception import perceive
from brain.context_builder import build_available_actions
from brain.action_resolver import resolve_target
from systems import spotted
from systems.room_assignment import refresh_character_room

w = make_world()
w["tick"] = 60000
w["households"]["lind"]["name"] = "The Lindqvist Household"
# Okafors: starter_house_2 (x=50): kitchen local rows 3-5, bedroom local x 13-16, rows 8-11.
w["props"] = [
    {"id": "oka_fridge", "template": "fridge_a", "x": 61, "y": 4, "state": {}, "building_id": "starter_house_2"},
    {"id": "oka_bed", "template": "bed_double_a", "x": 64, "y": 10, "state": {}, "building_id": "starter_house_2"},
    {"id": "lind_fridge", "template": "fridge_a", "x": 36, "y": 4, "state": {}, "building_id": "starter_house_1"},
]
r = w["characters"]["robert"]
r.update(x=64, y=9, building_id="starter_house_2", age=41, traits=[], relationships={}, activity=None, route=[],
         is_moving=False, cognition={}, memories=[],
         active_intentions=[{"type": "eat_food", "reason": "I'm hungry", "category": "survival", "priority": 80}])
for c in w["characters"].values():
    refresh_character_room(c, w)

perceive(r, w)
in_view = {p["id"] for p in r["perception"]["visible_props"]}
check("in the bedroom Robert doesn't see the fridge (it's in the kitchen)", "oka_fridge" not in in_view, str(in_view))
lines = spotted.context_lines(r, w)
check("... but being hungry brings it to mind, and where it is",
      any("fridge" in ln and "your kitchen" in ln for ln in lines), str(lines))
check("... not the neighbours' fridge he's never noticed", not any("Lindqvist" in ln for ln in lines), str(lines))

aa = build_available_actions(r, w)
res = resolve_target(r, w, "interact", "the fridge", aa)
check("'the fridge' resolves to his own, out of sight", res["id"] == "oka_fridge" and res.get("remembered"), str(res))
from systems.action_router import _route_interact
_route_interact(r, w, {"type": "interact", "target": "oka_fridge"}, w["definitions"])
check("... and using it means walking to the kitchen first",
      (r.get("activity") or {}).get("phase") == "walking" and r.get("is_moving"), str(r.get("activity")))

# ---- somewhere else: only what they happen to notice -----------------------------------------------------------------
r.update(x=35, y=5, building_id="starter_house_1", activity=None, is_moving=False, route=[])
refresh_character_room(r, w)
_orig = random.random
random.random = lambda: 0.99
perceive(r, w)
check("in the Lindqvists' kitchen, a glance doesn't always register the fridge", "lind_fridge" not in r.get("spotted", {}))
random.random = lambda: 0.0
perceive(r, w)
check("... another look, and it does", "lind_fridge" in r.get("spotted", {}))
random.random = _orig
check("... now it's something he knows about, with where",
      spotted.known_props(r, w)["lind_fridge"]["room_id"] == "starter_house_1:kitchen_0")

# ---- people: where they were last seen ------------------------------------------------------------------------------
k = w["characters"]["kathleen"]
k.update(x=36, y=5, building_id="starter_house_1")
refresh_character_room(k, w)
perceive(r, w)
r.update(x=64, y=9, building_id="starter_house_2")
refresh_character_room(r, w)
perceive(r, w)
r["active_intentions"] = [{"type": "visit_person", "reason": "talk to Kathleen", "target_id": "kathleen",
                           "category": "social", "priority": 80}]
lines = spotted.context_lines(r, w)
check("a plan about Kathleen brings to mind where he last saw her",
      any("last saw Kathleen Okafor" in ln and "Lindqvists' kitchen" in ln for ln in lines), str(lines))

# ---- examining something always registers it -------------------------------------------------------------------------
s = w["characters"]["susan"]
s.update(spotted={})
spotted.notice(s, w, w["props"][2])
check("something examined is remembered", "lind_fridge" in s["spotted"])

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
