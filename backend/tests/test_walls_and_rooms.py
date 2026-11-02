"""
Walls stop sight, and a character's room follows them (brain/perception.py::walls_between,
systems/room_assignment.py::refresh_character_room).

Live (2026-11-02): Robert Okafor stood in his kitchen and kept talking to Carol Lindqvist, who was eating in the dining
room on the other side of the wall: she was on his "People here" list, and his prompt said he was in the dining room
(his room_id was still the one he spawned in).

Run inside the backend container:   python tests/test_walls_and_rooms.py
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
from brain.perception import line_of_sight, walls_between, perceive_people
from systems.room_assignment import refresh_character_room

w = make_world()
robert, kathleen = w["characters"]["robert"], w["characters"]["kathleen"]

# starter_house_2 sits at x=50: the kitchen is local rows 3-5, the dining room rows 6-11, doors at local (10,5)/(11,5).
robert.update(x=59, y=4, building_id="starter_house_2", room_id="starter_house_2:dining_room_1")
kathleen.update(x=60, y=9, building_id="starter_house_2")

refresh_character_room(robert, w)
check("Robert's room follows him: the kitchen, not the room he spawned in",
      robert["room_id"] == "starter_house_2:kitchen_0", robert["room_id"])
refresh_character_room(kathleen, w)
check("... and Kathleen's: the dining room", kathleen["room_id"] == "starter_house_2:dining_room_1", kathleen["room_id"])

check("the live case: kitchen to dining room through the wall -- no line of sight", not line_of_sight(robert, kathleen, w))
check("... so she isn't among the people he sees",
      all(p["id"] != "kathleen" for p in perceive_people(robert, w)))

kathleen.update(x=61, y=5)
check("someone else in the same kitchen is seen", line_of_sight(robert, kathleen, w))
robert.update(x=60, y=5)
kathleen.update(x=60, y=7)
check("through the open doorway between kitchen and dining room: seen", line_of_sight(robert, kathleen, w))
w["buildings"][2]["doors"] = [{"x": 60, "y": 5, "is_open": False}]
check("... with that door closed: not", not line_of_sight(robert, kathleen, w))
w["buildings"][2]["doors"] = []

check("from the street into the kitchen through the outer wall: not seen",
      walls_between({"x": 59, "y": 14}, {"x": 59, "y": 4}, w))
check("street to street past the houses: nothing in the way", not walls_between({"x": 45, "y": 14}, {"x": 70, "y": 14}, w))

robert.update(x=59, y=14, building_id=None)
refresh_character_room(robert, w)
check("outdoors: no room", robert["room_id"] is None)

# ---- "move to the kitchen" while in the kitchen ---------------------------------------------------------------------
from systems.action_router import _route_move
robert.update(x=59, y=4, building_id="starter_house_2", move_target=None, is_moving=False, route=[], cognition={})
_route_move(robert, w, {"type": "move", "target": "room:starter_house_2:kitchen_0"})
check("moving to the room you're already in goes nowhere: no 'heading to the kitchen'",
      not robert.get("move_target") and not robert.get("is_moving"), str(robert.get("move_target")))
check("... and he's told so (and how to reach someone in another room)",
      any("already in the kitchen" in t for t in robert["cognition"].get("staged_knowledge", [])))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
