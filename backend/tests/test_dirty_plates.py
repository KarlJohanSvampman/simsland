"""
Dirty plates are real items, and the Household tab's kitchen view (systems/chores.py, body.on_consume_complete, api/household.py).

Run inside the backend container:   python tests/test_dirty_plates.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from systems import cookware, chores, ready_meals, food_scoring as fs
from systems.body import ensure_body, on_consume_complete
from systems.task_process import _dishes_on_complete
from api.household import _kitchen_of

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


c = {"id": "a", "name": "Anna A", "age": 35, "sex": "female", "weight_kg": 70, "household_id": "h", "building_id": "home",
     "body_features": {"height_cm": 170}, "inventory": [], "physical_traits": [], "physical_health": []}
ensure_body(c)
h = {"id": "h", "members": ["a"], "building_ids": ["home"], "storage": {"resources": []}, "_stock_named": True}
w = {"tick": 5000, "calendar": {"hour": 18, "minute": 0, "weekday": "Monday"}, "households": {"h": h}, "characters": {"a": c}, "props": []}

dish = fs.dish_from_items([{"template_id": "chicken", "quantity": 2}, {"template_id": "rice", "quantity": 2}, {"template_id": "broccoli", "quantity": 2}], 2, "Chicken Stirfry")
on_consume_complete(c, w, cookware.plate_item(dish))
check("a plate eaten leaves a dirty plate item behind, recording the dish, who and where", len(h["dirty_items"]) == 1 and h["dirty_items"][0]["from"] == "Chicken Stirfry"
      and h["dirty_items"][0]["left_by"] == "a" and h["dirty_items"][0]["building_id"] == "home", str(h.get("dirty_items")))
check("... and the household's dirty count goes up with it", h["dirty_dishes"] == 1)

cookware.add_stock(h, "apple", 1)
apple = {"template_id": "apple", "category": "food", "calories": 95, "fat_pct": 0.03, "name": "Apple"}
on_consume_complete(c, w, apple)
check("a piece of fruit adds to the count but there is no plate to carry", h["dirty_dishes"] == 2 and len(h["dirty_items"]) == 1)

ready_meals.add(h, "takeout_burger", 5000, 1, "warm")
box = ready_meals.take(h, c)
on_consume_complete(c, w, box)
check("a takeout comes in a box for the bin: nothing to wash", h["dirty_dishes"] == 2 and len(h["dirty_items"]) == 1)

ready_meals.add(h, "frozen_lasagna", 5000, 1, "warm")
on_consume_complete(c, w, ready_meals.take(h, c))
check("a microwaved meal leaves a plate", len(h["dirty_items"]) == 2 and h["dirty_items"][1]["from"] == "Frozen lasagna")

k = _kitchen_of(h, w["characters"], w["tick"])
check("the kitchen view lists the dirty plates", len(k["dirty_plates"]) == 2 and k["dirty_dishes"] == 3)

v = cookware.vessel_for(h, "pot")
for tid, n in dict(ground_beef=4, pasta=4, tomato=4, salt=2).items():
    cookware.add_stock(h, tid, n)
cookware.load(v, cookware.pull_ingredients(h, fs.DISH_RECIPES["pasta_bolognese"], 2))
cookware.begin(c, w, v, "pasta_bolognese", 2)
k = _kitchen_of(h, w["characters"], w["tick"])
pot = next(x for x in k["cookware"] if x["kind"] == "pot")
check("the kitchen view shows what is cooking, for whom and how long is left", pot["state"] == "cooking" and pot["dish"] == "Pasta Bolognese" and pot["people"] == 2
      and pot["minutes_left"] >= 20 and pot["maker"] == "Anna A", str(pot))
w["tick"] = v["done_tick"]
cookware.update(w)
k = _kitchen_of(h, w["characters"], w["tick"])
pot = next(x for x in k["cookware"] if x["kind"] == "pot")
check("... and when it is ready, the portions left and how long it is served", pot["state"] == "ready" and pot["charges"] == 2 and 60 <= pot["served_minutes_left"] <= 120, str(pot))

_dishes_on_complete(h, {}, w)
check("washing up clears the plates, the count and the pots", h["dirty_items"] == [] and h["dirty_dishes"] == 0)

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
