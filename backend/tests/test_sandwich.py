"""
Bread takes fillings from the stock and becomes a sandwich (systems/eating.py::sandwich_item, stock_item).

Run inside the backend container:   python tests/test_sandwich.py
"""

import os
import random
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from systems import cookware, eating

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def setup(**stock):
    h = {"id": "h", "members": ["a"], "storage": {"resources": []}, "_stock_named": True}
    for tid, n in stock.items():
        cookware.add_stock(h, tid, n)
    c = {"id": "a", "household_id": "h", "building_id": "b", "inventory": []}
    return {"households": {"h": h}, "characters": {"a": c}, "tick": 1}, h, c


w, h, c = setup(bread_loaf=2, cheese=2, tomato=2, chicken=2)
s = eating.sandwich_item(c, w)
used = {i["template_id"] for i in s["ingredients"]}
check("a sandwich is bread with a filling of each kind that there is", s["name"] == "Sandwich" and "bread_loaf" in used and len(used) == 4, str(used))
check("... one item with calories, health and taste like any dish", s["calories"] > 300 and 0 < s["health"] <= 1 and s["taste"] > 0 and s["category"] == "food")
left = {cookware.row_template(r): r["quantity"] for r in h["storage"]["resources"]}
check("the bread and the fillings come out of the stock", left.get("bread_loaf") == 1 and left.get("cheese") == 1 and left.get("tomato") == 1 and left.get("chicken") == 1, str(left))

w, h, c = setup(bread_loaf=1)
check("bread with nothing to put in it stays bread", eating.sandwich_item(c, w) is None)
random.seed(1)
check("... and is eaten as bread", eating.stock_item(c, w, groups=("bread",))["food_group"] == "bread")

w, h, c = setup(cheese=2, tomato=2)
check("fillings with no bread make nothing", eating.sandwich_item(c, w) is None)

w, h, c = setup(bread_loaf=1, ground_beef=1)
fan = {"id": "f", "household_id": "h", "building_id": "b", "food_taste": {"cheese": 1.0, "chicken": -1.0, "ground_beef": -1.0, "egg": 0.0}}
s = eating.sandwich_item(c, w)
check("a single filling is fine", {i["template_id"] for i in s["ingredients"]} == {"bread_loaf", "ground_beef"})

w, h, c = setup(bread_loaf=3, chicken=2, egg=2)
c["food_taste"] = {"chicken": -0.9, "egg": 0.9}
s = eating.sandwich_item(c, w)
check("they choose the filling they like", "egg" in {i["template_id"] for i in s["ingredients"]} and "chicken" not in {i["template_id"] for i in s["ingredients"]}, str(s["ingredients"]))

sandwiches = 0
for i in range(100):
    w, h, c = setup(bread_loaf=2, cheese=2, tomato=2)
    random.seed(i)
    item = eating.stock_item(c, w, groups=("bread",))
    sandwiches += item.get("name") == "Sandwich"
check("with bread and fillings in the house they usually make one", 40 < sandwiches < 85, str(sandwiches))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
