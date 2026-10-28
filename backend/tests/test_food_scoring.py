"""
Ingredients, recipes as ratios, and the health / taste / addictive scale (data/ingredients.py, data/dishes.py, systems/food_scoring.py).

Run inside the backend container:   python tests/test_food_scoring.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from data.dishes import DISH_RECIPES
from data.ingredients import INGREDIENTS, EAT_AS_IS
from data.item_templates import get_template
from systems import food_scoring as fs

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def it(tid, n=1):
    return {"template_id": tid, "quantity": n}


# ---- the ingredients ------------------------------------------------------------------------------------------------------------------------
groups = {"carb", "protein", "vegetable", "dairy", "fruit", "bread", "none", "spice"}
check("every ingredient has a known group, calories, fat share and a price",
      all(t["food_group"] in groups and t["calories"] >= 0 and 0 <= t["fat_pct"] <= 1 and t["base_price"] > 0 for t in INGREDIENTS.values()))
check("every group is represented", groups <= {t["food_group"] for t in INGREDIENTS.values()})
check("only fruit, bread and ready-made items are eaten as they are",
      all(t["ready_to_eat"] == (t["food_group"] in EAT_AS_IS) for t in INGREDIENTS.values()))
check("the ingredients are real item templates (apple is the new one)", get_template("apple")["food_group"] == "fruit" and get_template("chicken")["calories"] == 165)
check("bread holds ingredients", get_template("bread_loaf")["holds_ingredients"] and get_template("bread_loaf")["capacity"] > 0)
check("spices only add taste", all(t["spice_taste"] > 0 and t["calories"] <= 5 for t in INGREDIENTS.values() if t.get("spice")))
check("groups resolve for recipes (vegetables and fruit are both vitamins)", fs.group_of(it("carrot")) == "vitamin" and fs.group_of(it("apple")) == "vitamin"
      and fs.group_of(it("salt")) == "spice" and fs.group_of(it("cheese")) == "dairy")

# ---- recipes are ratios --------------------------------------------------------------------------------------------------------------------
rec = DISH_RECIPES["pasta_bolognese"]
check("a recipe scales with the number of people", fs.units_needed(rec, 1) == {"protein": 1, "carb": 1, "vitamin": 1, "spice": 1}
      and fs.units_needed(rec, 4) == {"protein": 4, "carb": 4, "vitamin": 4, "spice": 2}, str(fs.units_needed(rec, 4)))
check("... and so does the cooking time, by cookware", fs.cook_minutes(rec, 4) > fs.cook_minutes(rec, 1)
      and fs.cook_minutes(DISH_RECIPES["roast_dinner"], 2) > fs.cook_minutes(DISH_RECIPES["omelette"], 2))
check("every recipe names a cookware and only asks for known groups", all(r["method"] in ("pot", "pan", "oven")
      and set(r["per_person"]) <= {"protein", "carb", "vitamin", "dairy", "spice"} for r in DISH_RECIPES.values()))

# ---- the scale -------------------------------------------------------------------------------------------------------------------------
chips = fs.dish_from_items([it("bag_of_chips")])
apple = fs.dish_from_items([it("apple")])
supper = fs.dish_from_items([it("chicken", 2), it("rice", 2), it("broccoli", 2), it("herbs")], people=2)
fry = fs.dish_from_items([it("sausage", 2), it("butter"), it("pasta", 2)], people=2)
check("chips are far less nutritional than an apple", chips["health"] < apple["health"] - 0.3, f"{chips['health']} vs {apple['health']}")
check("a balanced dinner is more nutritional than a fry-up", supper["health"] > fry["health"], f"{supper['health']} vs {fry['health']}")
check("the less nutritional it is, the better it tastes", chips["taste"] > apple["taste"] > 0 and fry["taste"] > supper["taste"] - 0.2)
check("... and the more addictive", chips["addictive"] > supper["addictive"] and chips["addictive"] > apple["addictive"])
check("a medium dish is good or great, honestly", fs.reaction(fs.taste_of(0.5)) in ("good", "great"), fs.reaction(fs.taste_of(0.5)))
check("the most nutritional end is worse tasting", fs.taste_of(1.0) < fs.taste_of(0.5) and fs.reaction(fs.taste_of(1.0)) in ("bland", "not good", "fine"))
check("taste only ever falls as health rises", all(fs.taste_of(h / 10) >= fs.taste_of((h + 1) / 10) for h in range(10)))
check("spice raises taste, and is capped", fs.taste_of(0.8, 0.05) > fs.taste_of(0.8) and fs.taste_of(0.8, 5) - fs.taste_of(0.8) <= fs.SPICE_BONUS_CAP + 1e-9)
check("spice adds no nutrition", fs.dish_from_items([it("chicken"), it("salt", 3)])["calories"] - fs.dish_from_items([it("chicken")])["calories"] <= 10)

# ---- the numbers that drive weight -----------------------------------------------------------------------------------------------------
check("calories are summed and shared out over the portions", supper["calories"] == 165 * 2 + 200 * 2 + 35 * 2 + 3
      and supper["calories_per_portion"] == round(supper["calories"] / 2), str(supper))
check("fat share is the calorie-weighted average", abs(supper["fat_pct"] - supper["fat_cal"] / supper["calories"]) < 0.002 and 0 < supper["fat_pct"] < 1)
check("a fry-up carries a higher fat share than the supper", fry["fat_pct"] > supper["fat_pct"] + 0.2, f"{fry['fat_pct']} vs {supper['fat_pct']}")

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
