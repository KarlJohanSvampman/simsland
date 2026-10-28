"""
The food flow end to end: a stocked pantry -> a dinner on the stove -> served -> a plate -> hunger, calories, fat and weight.
(household_pantry.py, cookware.py, eating.py, strategy.py, body.py::on_consume_complete, nutrition.py)

Run inside the backend container:   python tests/test_food_flow.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from systems import cookware, eating, nutrition
from systems.body import ensure_body, on_consume_complete
from systems.household_pantry import stock_pantry, restock
from systems.strategy import resolve_hunger_strategy

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid="a", **extra):
    c = {"id": cid, "name": cid.upper(), "age": 35, "sex": "female", "weight_kg": 70, "household_id": "h", "building_id": "b",
         "body_features": {"height_cm": 170}, "inventory": [], "physical_traits": [], "physical_health": []}
    c.update(extra)
    ensure_body(c)
    return c


def setup(members=("a", "b")):
    h = {"id": "h", "members": list(members), "storage": {"resources": []}}
    w = {"tick": 5000, "calendar": {"hour": 18, "minute": 0, "day": 3}, "households": {"h": h}, "props": [], "placed_items": {},
         "characters": {m: person(m) for m in members}}
    return w, h


# ---- a pantry is named ingredients -----------------------------------------------------------------------------------------------------------
w, h = setup()
added = stock_pantry(w, h)
check("a new household is stocked with named ingredients", added > 0 and all(r.get("template_id") for r in h["storage"]["resources"]))
check("... enough to cook for everyone at home", len(cookware.feasible_recipes(h, 2)) > 0, str(cookware.feasible_recipes(h, 2)))
before = sum(r["quantity"] for r in h["storage"]["resources"])
restock(w, h, {"money": 500})
check("a grocery trip adds named ingredients too", sum(r["quantity"] for r in h["storage"]["resources"]) > before and all(r.get("template_id") for r in h["storage"]["resources"]))

# ---- hungry: cook, then eat what is served -----------------------------------------------------------------------------------------------
w, h = setup()
stock_pantry(w, h)
a = w["characters"]["a"]
check("with ingredients and no food ready, a hungry person's routine is to eat what they can at once", resolve_hunger_strategy(a, w) in ("eat_snack", "cook_recipe"))
stocked = sum(r["quantity"] for r in h["storage"]["resources"])
vessel = cookware.start_dinner(a, w, h)
check("cooking started for the two at home", vessel and vessel["people"] == 2 and vessel["state"] == "cooking", str(vessel and vessel["state"]))
check("the ingredients left the stock", sum(r["quantity"] for r in h["storage"]["resources"]) < stocked)
check("while it cooks there is nothing served", cookware.ready_vessel(h, w["tick"]) is None)
w["tick"] = vessel["done_tick"] + 1
cookware.update(w)
check("when it is done, hungry people go and eat it", resolve_hunger_strategy(a, w) == "eat_meal")

a["body"]["hunger"] = 80
meal = eating.resolve_meal(a, w, None)
check("eating takes a plate off the vessel", meal and meal["item"]["template_id"] == "plated_dish" and vessel["charges"] == 1, str(meal))
plate = meal["item"]
check("the plate is in their hands", plate in a["inventory"])
on_consume_complete(a, w, plate)
b = a["body"]
check("it fills them by its calories (about a point per 8 kcal)", abs((80 - b["hunger"]) - min(100, plate["calories"] / 8)) < 0.5, f"{b['hunger']} {plate['calories']}")
check("the calories and the fat of it are on the day's tally", b["calories_today"] == plate["calories"] and abs(b["fat_cal_today"] - plate["calories"] * plate["fat_pct"]) < 1)
check("the nutrition tally is a share of THEIR day", abs(b["nutrients_today"] - plate["calories"] / nutrition.daily_kcal_need(a)) < 0.01)
check("they have an honest word for it", eating.meal_reaction(plate) in ("great", "good", "fine", "bland", "not good"))
b2 = person("b")
w["characters"]["b"] = b2
meal2 = eating.resolve_meal(b2, w, None)
check("the second person takes the last plate and the vessel is then dirty", meal2 and vessel["charges"] == 0 and vessel["state"] == "dirty")
check("with nothing served and the vessel dirty, nothing more comes off it", eating.served_plate(a, w) is None)

# ---- ready-to-eat from the stock ---------------------------------------------------------------------------------------------------------
w, h = setup()
cookware.add_stock(h, "apple", 2)
check("a hungry person with only fruit takes a snack", resolve_hunger_strategy(person(), w) == "eat_snack")
apple = eating.stock_item(person(), w)
check("... a real item with calories, taken out of the stock", apple and apple["calories"] == 95 and h["storage"]["resources"][0]["quantity"] == 1)
cookware.add_stock(h, "bread_loaf", 1)
check("bread is eaten as it is too", eating.stock_item(person(), w, groups=("bread",))["food_group"] == "bread")
check("a raw chicken is not a snack", eating.stock_item(person(), setup()[0]) is None)

# ---- weight from calories and fat -----------------------------------------------------------------------------------------------------------
c = person()
need = nutrition.daily_kcal_need(c)
check("a daily need is a realistic number of kcal", 1500 < need < 2800, str(need))
check("a man needs more than a woman of the same build", nutrition.daily_kcal_need(person(sex="male")) > need)
check("eating exactly what you burn changes nothing", abs(nutrition.weight_change_kg(c, need)) < 1e-9)
gain = nutrition.weight_change_kg(c, need + 1000)
lose = nutrition.weight_change_kg(c, need - 1000)
check("a surplus puts weight on and a deficit takes it off, about 7700 kcal to the kilo", abs(gain - 1000 / 7700) < 0.01 and lose < 0)
check("the same surplus from fat weighs a little more", nutrition.weight_change_kg(c, need + 1000, fat_cal=(need + 1000) * 0.6) > gain)
check("a day never moves weight more than the cap", nutrition.weight_change_kg(c, need * 4) <= nutrition.MAX_DAILY_KG and nutrition.weight_change_kg(c, 0) >= -nutrition.MAX_DAILY_KG)

c = person()
c["body"]["nutrients_today"] = 1.5
c["body"]["calories_today"] = 1.5 * need
c["body"]["fat_cal_today"] = 0.5 * 1.5 * need
start = c["weight_kg"]
nutrition.settle_nutrition_day(c, {"tick": 0, "definitions": {}, "calendar": {}})
check("settling the day applies it, and starts the next tally from zero", c["weight_kg"] > start and c["body"]["calories_today"] == 0 and c["body"]["fat_cal_today"] == 0
      and c["body"]["nutrients_today"] == 0, f"{start} -> {c['weight_kg']}")

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
