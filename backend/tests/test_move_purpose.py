"""
Walking to a thing is for doing something with it (systems/move_purpose.py).

Live (2026-11-03): Steven Moreau, hungry, chose "move | To the kitchen counter to grab something to eat" over and
over while standing by the counter; nothing ever happened, and he was never told he was there.

Run inside the backend container:   python tests/test_move_purpose.py
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
from systems.action_router import _route_move
from systems.move_purpose import check_arrival
from systems.movement import update_character_movement
from systems.room_assignment import refresh_character_room

HUNGRY = [{"type": "eat_food", "reason": "hungry", "category": "survival", "priority": 80}]


def setup(x, y, intentions=()):
    w = make_world()
    w["tick"] = 70000
    # the Okafors' kitchen (starter_house_2, x=50): local rows 3-5
    w["props"] = [{"id": "counter", "template": "kitchen_counter", "x": 57, "y": 4, "state": {}, "rotation": 0},
                  {"id": "sink", "template": "kitchen_sink", "x": 60, "y": 4, "state": {}, "rotation": 0}]
    r = w["characters"]["robert"]
    r.update(x=x, y=y, building_id="starter_house_2", age=41, activity=None, route=[], is_moving=False, cognition={},
             memories=[], active_intentions=list(intentions), posture="standing")
    refresh_character_room(r, w)
    return w, r


def walk(w, c, ticks=600):
    for _ in range(ticks):
        w["tick"] += 1
        if c.get("is_moving"):
            update_character_movement(c, w)
        check_arrival(c, w)
        if c.get("activity") or (c.get("cognition") or {}).get("staged_knowledge"):
            return


def told(c):
    return " ".join((c.get("cognition") or {}).get("staged_knowledge") or [])


# ---- the live case: right by the counter, hungry --------------------------------------------------------------------
w, r = setup(57, 5, HUNGRY)
_route_move(r, w, {"type": "move", "target": "counter",
                   "target_description": "To the kitchen counter to grab something to eat."})
act = r.get("activity") or {}
check("hungry, already at the counter, 'move to the counter to grab something to eat': he starts preparing food",
      act.get("target_id") == "counter" and act.get("interaction") == "prepare_food", str(act))

# ---- from across the house: walks there, then does it ------------------------------------------------------------------
w, r = setup(64, 9, HUNGRY)
_route_move(r, w, {"type": "move", "target": "counter", "target_description": "the kitchen counter"})
check("from the bedroom: he sets off for the counter", r.get("is_moving") and r.get("_move_purpose"))
walk(w, r)
act = r.get("activity") or {}
check("... and on getting there, starts preparing food (what his hunger calls for)",
      act.get("interaction") == "prepare_food", str(act) + " / " + told(r))

# ---- the purpose he gives decides, when it names a use -----------------------------------------------------------------
w, r = setup(60, 5)
_route_move(r, w, {"type": "move", "target": "sink", "target_description": "the kitchen sink", "detail": "to get a drink"})
check("'to the sink to get a drink': he drinks", (r.get("activity") or {}).get("interaction") == "drink",
      str(r.get("activity")))

# ---- no purpose, nothing pressing: he's told he's there and what it's for --------------------------------------------
w, r = setup(60, 5)
_route_move(r, w, {"type": "move", "target": "sink", "target_description": "the kitchen sink"})
check("no reason given and nothing pressing: nothing starts", not r.get("activity"))
check("... he's told he's at the sink and what it's for", "You're at the kitchen sink" in told(r)
      and "wash dishes" in told(r), told(r))
check("... and isn't left 'heading to' it", not r.get("move_target"))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
