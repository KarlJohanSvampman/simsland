"""
Eating is a real meal at a real place: a food item, taken to a dining table, and written on the activity (systems/eating.py,
systems/action_router.py::_route_eat, systems/activities.py's eat completion).

Run inside the backend container:   python tests/test_eating.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from systems import eating
from systems.action_router import _route_eat

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def table(x=5, y=5, building="b"):
    return {"id": "table", "template": "dining_table_a", "building_id": building, "x": x, "y": y,
            "anchors": [{"name": "anchor_eat", "interaction": "eat", "x": x, "y": y}]}


def world(*props):
    return {"tick": 100, "calendar": {"hour": 13, "minute": 5}, "props": list(props), "characters": {}, "households": {}, "placed_items": {}}


def char(**extra):
    c = {"id": "k", "name": "Karim", "age": 41, "x": 5, "y": 5, "building_id": "b", "posture": "standing", "activity": None,
         "inventory": [{"id": "item_apple", "template_id": "apple", "name": "apple", "category": "food"},
                       {"id": "item_key", "template_id": "house_key", "name": "house key"}]}
    c.update(extra)
    return c


# ---- what and where ----------------------------------------------------------------------------------------------------------------------------
w, c = world(table()), char()
meal = eating.resolve_meal(c, w, "char_someone_else")
check("a person as the target still resolves to real food they carry", meal and meal["item"]["id"] == "item_apple", str(meal))
check("... and to the dining table in their building", meal and meal["place"] and meal["place"]["id"] == "table")
check("the item they named is the one chosen", eating.resolve_meal(c, w, "item_apple")["item"]["id"] == "item_apple")
check("a key is not food", eating.resolve_meal(char(inventory=[{"id": "item_key", "template_id": "house_key"}]), w, "item_key") is None)
check("nothing edible anywhere: no meal (the hunger routine takes over)", eating.resolve_meal(char(inventory=[]), w, None) is None)
check("a table in another building is not where they eat", eating.eating_place(c, world(table(building="elsewhere"))) is None)
check("an occupied table is passed over", eating.eating_place(c, world({**table(), "anchors": [{"name": "anchor_eat", "interaction": "eat", "occupied_by": "x"}]})) is None)

# ---- the activity says what it is ---------------------------------------------------------------------------------------------------------
w, c = world(table()), char()
_route_eat(c, w, {"type": "eat", "target": "char_someone_else"})
act = c["activity"]
check("the eat activity is at the table, not where they happened to stand", act and act["type"] == "eat" and act["target_id"] == "table", str(act))
check("... and carries what is being eaten", act["state"].get("food_name") == "apple" and act["state"].get("food_id") == "item_apple", str(act["state"]))
check("... with the choice on its timeline", any(t["step"] == "chose food" and t.get("food") == "apple" for t in act.get("timeline", [])), str(act.get("timeline")))

# the end of the activity consumes exactly that item
from systems import activities
consumed = []
real = activities._take_item_anywhere
activities._take_item_anywhere = lambda c, w, item_id: (consumed.append(item_id), None)[1]
try:
    try:
        activities.complete_activity(c, w, act)
    except Exception:
        pass            # the rest of completion needs a full character; only which item it reached for matters here
finally:
    activities._take_item_anywhere = real
check("completion reaches for the chosen item, not the table", consumed[:1] == ["item_apple"], str(consumed))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
