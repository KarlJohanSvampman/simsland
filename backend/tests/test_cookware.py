"""
Pots, pans and the oven: ingredients pulled from the household's stacks, cooked on a clock, served as plates off a charge count,
closed out after the serving window (systems/cookware.py, food_scoring.plate_from_dish).

Run inside the backend container:   python tests/test_cookware.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from systems import cookware, food_scoring as fs

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def household(**stocks):
    h = {"id": "h", "members": ["a", "b"], "storage": {"resources": []}}
    for tid, n in stocks.items():
        cookware.add_stock(h, tid, n)
    return h


def world(h, tick=1000):
    chars = {m: {"id": m, "name": m.upper(), "building_id": "b", "active_intentions": []} for m in h["members"]}
    return {"tick": tick, "households": {"h": h}, "characters": chars, "props": [], "calendar": {"hour": 18, "minute": 0}}


STOCKED = dict(ground_beef=4, pasta=4, tomato=4, salt=4, chicken=4, rice=4, broccoli=4, herbs=2)

# ---- stock ---------------------------------------------------------------------------------------------------------------------------------
h = household(**STOCKED)
check("stock is named ingredients, merged into stacks", cookware.add_stock(h, "pasta", 2)["quantity"] == 6
      and len([r for r in h["storage"]["resources"] if r["template_id"] == "pasta"]) == 1)
check("the household's rows keep the resource types the older code reads",
      {r["resource_type"] for r in h["storage"]["resources"]} >= {"FOOD_PROTEIN", "FOOD_CARB", "FOOD_VEGETABLE", "FOOD_SPICE"})
legacy = {"id": "h2", "storage": {"resources": [{"resource_type": "FOOD_CARB", "quantity": 3, "freshness": 1.0}]}}
check("a legacy row without a name still counts (as rice)", cookware.row_group(legacy["storage"]["resources"][0]) == "carb")

old = {"id": "h3", "members": ["a"], "storage": {"resources": [{"resource_type": "FOOD_CARB", "quantity": 12}, {"resource_type": "FOOD_SPICE", "quantity": 4}]}}
cookware.name_legacy_stock(old)
check("old unnamed stacks become named ingredients, the same amount, and a spread of them", sum(r["quantity"] for r in old["storage"]["resources"]) == 16
      and all(r.get("template_id") for r in old["storage"]["resources"]) and len([r for r in old["storage"]["resources"] if r["resource_type"] == "FOOD_CARB"]) > 1, str(old))

# ---- what can be made ----------------------------------------------------------------------------------------------------------------------
check("recipes the stock covers are offered", "pasta_bolognese" in cookware.feasible_recipes(h, 2))
check("... more people need more", "pasta_bolognese" not in cookware.feasible_recipes(h, 10))
check("a recipe without its dairy is not offered", "mac_and_cheese" not in cookware.feasible_recipes(h, 2))
check("nothing in stock, nothing to make", cookware.feasible_recipes(household(), 2) == [])

# ---- loading takes from the stock, nothing when short ---------------------------------------------------------------------------------
rec = fs.DISH_RECIPES["pasta_bolognese"]
before = sum(r["quantity"] for r in h["storage"]["resources"])
items = cookware.pull_ingredients(h, rec, 2)
after = sum(r["quantity"] for r in h["storage"]["resources"])
check("the units taken are the ratio times the people", sum(i["quantity"] for i in items) == before - after == 2 + 2 + 2 + 1, str(items))
short = cookware.pull_ingredients(household(chicken=1), rec, 2)
check("when something is short nothing is taken", short is None)
liked = cookware.pull_ingredients(household(chicken=2, ground_beef=2, pasta=2, tomato=2, salt=1), rec, 2, rank=lambda t: 1 if t == "chicken" else 0)
check("the one they like is chosen first", [i["template_id"] for i in liked if i["template_id"] in ("chicken", "ground_beef")] == ["chicken"], str(liked))

# ---- the vessel's life ---------------------------------------------------------------------------------------------------------------------
h = household(**STOCKED)
w = world(h)
cook = {"id": "a", "name": "Anna"}
v = cookware.vessel_for(h, "pot")
check("every household gets a pot, a pan and an oven", sorted(x["kind"] for x in h["cookware"]) == ["oven", "pan", "pot"])
check("ingredients go into the vessel", cookware.load(v, cookware.pull_ingredients(h, rec, 2)) and v["state"] == "loaded" and len(v["items"]) >= 4)
check("a loaded vessel takes no more", not cookware.load(v, []) and cookware.vessel_for(h, "pot") is None)
cookware.begin(cook, w, v, "pasta_bolognese", 2)
check("cooking takes a realistic time", v["state"] == "cooking" and v["done_tick"] - w["tick"] == fs.cook_minutes(rec, 2) * 60 and v["done_tick"] - w["tick"] >= 20 * 60)
w["tick"] = v["done_tick"] - 1
cookware.update(w)
check("... and is not done a second early", v["state"] == "cooking")
w["tick"] = v["done_tick"]
cookware.update(w)
check("when done it holds a charge for each person and is served for one to two hours", v["state"] == "ready" and v["charges"] == 2
      and 3600 <= v["serve_until_tick"] - w["tick"] <= 7200, str(v))
check("the cook calls everyone home to the table, and goes too", v["maker_id"] == "a" and not v["announce_pending"]
      and all(any(i["type"] == "eat_food" for i in ch["active_intentions"]) for ch in w["characters"].values()), str(w["characters"]))
check("... out loud", "come and eat" in (w["characters"]["a"].get("current_speech") or {}).get("utterance", ""), str(w["characters"]["a"].get("current_speech")))
check("a served vessel is found", cookware.ready_vessel(h, w["tick"]) is v)

p1 = cookware.take_portion(v, w)
check("a plate is one portion with its own numbers", p1["calories"] > 0 and 0 < p1["health"] <= 1 and p1["category"] == "food"
      and p1["dish_name"] == "Pasta Bolognese" and p1["id"].startswith("plate_"), str(p1))
check("... and takes a charge off the vessel", v["charges"] == 1 and v["state"] == "ready")
p2 = cookware.take_portion(v, w)
check("the last plate leaves the vessel dirty", v["charges"] == 0 and v["state"] == "dirty" and cookware.ready_vessel(h, w["tick"]) is None)
check("nothing more to take", cookware.take_portion(v, w) is None)
check("washing makes it usable again", cookware.wash(h) == 1 and v["state"] == "empty" and v["items"] == [])

# ---- the serving window ends ---------------------------------------------------------------------------------------------------------------
h = household(**STOCKED)
w = world(h)
v = cookware.vessel_for(h, "oven")
cookware.load(v, cookware.pull_ingredients(h, fs.DISH_RECIPES["roast_dinner"], 2))
cookware.begin(cook, w, v, "roast_dinner", 2)
w["tick"] = v["done_tick"]
cookware.update(w)
cookware.take_portion(v, w)
w["tick"] = v["serve_until_tick"]
cookware.update(w)
check("when the window passes the cook's dinner is closed out: dirty vessel, a dish to wash", v["state"] == "dirty" and h.get("dirty_dishes", 0) >= 1)
check("a late plate is not served", cookware.ready_vessel(h, w["tick"]) is None)
check("what was left of a good dish is stored as leftovers for the fridge", len(h["leftovers"]) == 1 and h["leftovers"][0]["portions"] == 1, str(h.get("leftovers")))
check("... and someone can eat them later", cookware.take_leftover(h)["template_id"] == "plated_dish" and h["leftovers"] == [])
v2 = cookware.vessel_for(h, "pot")
cookware.load(v2, cookware.pull_ingredients(h, rec, 2))
cookware.begin(cook, w, v2, "pasta_bolognese", 2)
w["tick"] = v2["done_tick"]
cookware.update(w)
check("or are thrown away", cookware.close_out(h, v2, store=False) is None and h["leftovers"] == [] and v2["state"] == "dirty")

# ---- weaknesses decide the plate ----------------------------------------------------------------------------------------------------------
dish = fs.dish_from_items([{"template_id": "ground_beef", "quantity": 2}, {"template_id": "pasta", "quantity": 2},
                           {"template_id": "tomato", "quantity": 2}], people=2, name="x")
plain = fs.plate_from_dish(dish)
meaty = fs.plate_from_dish(dish, {"meat": 1.0})
carby = fs.plate_from_dish(dish, {"meat": -1.0})
greedy = fs.plate_from_dish(dish, {"calories": 1.0})
check("with no weakness the plate is the portion", plain["calories"] == dish["calories_per_portion"], f"{plain['calories']} vs {dish['calories_per_portion']}")
check("a weakness for meat takes more meat and fewer carbs, fattier", meaty["groups"]["protein"] > plain["groups"]["protein"]
      and meaty["groups"]["carb"] < plain["groups"]["carb"] and meaty["fat_pct"] > plain["fat_pct"])
check("... and the other way round", carby["groups"]["carb"] > plain["groups"]["carb"] and carby["fat_pct"] < plain["fat_pct"])
check("a weakness for calories is a bigger helping", greedy["calories"] > plain["calories"])

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
