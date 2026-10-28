"""
Tastes, stress habits, the dinner planner and the dinner rota (systems/food_habits.py, dinner.py, dinner_rota.py).

Run inside the backend container:   python tests/test_food_habits.py
"""

import os
import random
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from systems import cookware, dinner, dinner_rota, food_habits as fh, food_scoring as fs
from systems.proposals import respond

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid, stress=0, **extra):
    c = {"id": cid, "name": f"{cid.upper()} Test", "age": 35, "age_group": "adult", "household_id": "h", "building_id": "home",
         "stress": stress, "active_intentions": [], "inventory": []}
    c.update(extra)
    return c


def setup(stocked=True, weekday="Tuesday", hour=17, members=("a", "b")):
    h = {"id": "h", "members": list(members), "building_ids": ["home"], "storage": {"resources": []}, "_stock_named": True}
    if stocked:
        for tid, n in dict(ground_beef=6, pasta=6, tomato=6, salt=4, chicken=6, rice=6, broccoli=6, herbs=2, cheese=3).items():
            cookware.add_stock(h, tid, n)
    w = {"tick": 100000, "calendar": {"year": 2026, "month": 3, "day": 10, "weekday": weekday, "hour": hour, "minute": 0},
         "households": {"h": h}, "characters": {m: person(m) for m in members}, "props": [], "proposals": {}}
    return w, h


# ---- tastes ------------------------------------------------------------------------------------------------------------------------------
a, b = person("a"), person("b")
check("a starting lean is personal and the same every time", fh.liking(a, "pasta") == fh.liking(person("a"), "pasta") and fh.liking(a, "pasta") != fh.liking(b, "pasta")
      or fh.liking(a, "rice") != fh.liking(b, "rice"))
check("... and small", all(abs(fh.liking(a, t)) <= fh.BASE_LEAN for t in ("pasta", "rice", "chicken", "tomato")))

dish = fs.dish_from_items([{"template_id": "ground_beef", "quantity": 2}, {"template_id": "pasta", "quantity": 2}, {"template_id": "tomato", "quantity": 2}], 2, "x")
plate = cookware.plate_item(dish)
check("a plate remembers its ingredients", {i["template_id"] for i in plate["ingredients"]} == {"ground_beef", "pasta", "tomato"})

fan = person("fan")
fan["food_taste"] = {"ground_beef": 0.9, "pasta": 0.9, "tomato": 0.9}
foe = person("foe")
foe["food_taste"] = {"ground_beef": -0.9, "pasta": -0.9, "tomato": -0.9}
check("the same plate is better for someone who likes what is in it", fh.personal_taste(fan, plate) > plate["taste"] > fh.personal_taste(foe, plate))

before = fh.liking(fan, "pasta")
for _ in range(10):
    fh.on_meal(fan, {}, plate)
check("liking a meal grows liking for its ingredients, capped", before < fan["food_taste"]["pasta"] <= 1.0)
bland = dict(plate, taste=0.05, health=0.95, addictive=0.0)
neutral = person("n")
neutral["food_taste"] = {"ground_beef": 0.0, "pasta": 0.0, "tomato": 0.0}
for _ in range(15):
    fh.on_meal(neutral, {}, bland)
check("a meal that tastes bad turns them off its ingredients", neutral["food_taste"]["pasta"] < 0.0, str(neutral["food_taste"]))

junk = {"template_id": "bag_of_chips", "calories": 150, "fat_pct": 0.55, "food_group": "none", "category": "food"}
c = person("c")
for _ in range(6):
    fh.on_meal(c, {}, junk)
check("junk raises a craving", fh.craving(c) > 0.2, str(fh.habits(c)))
for _ in range(10):
    fh.on_meal(c, {}, dict(plate, health=0.8, taste=0.4, addictive=0.04))
check("good meals let it fade", fh.craving(c) < 0.1, str(fh.habits(c)))

stressed = person("s", stress=80)
for _ in range(5):
    fh.on_meal(stressed, {}, junk)
check("eating junk while stressed builds a comfort habit", fh.habits(stressed)["comfort"] > 0.25, str(fh.habits(stressed)))
calm = person("k", stress=10)
calm["food_habits"] = {"craving": 0, "comfort": 0.5, "stress_days": []}
for _ in range(10):
    fh.on_meal(calm, {}, dict(plate, health=0.8, taste=0.5, addictive=0.04))
check("eating well while calm undoes it", fh.habits(calm)["comfort"] < 0.3)

# ---- stress: now and the week ---------------------------------------------------------------------------------------------------------------
w, h = setup()
tired = person("t", stress=10)
tired["food_habits"] = {"craving": 0, "comfort": 0, "stress_days": [90, 90, 90, 90, 90, 90, 90]}
check("the week's strain weighs in even when today is calm", fh.pressure(tired) > fh.pressure(person("z", stress=10)))
for d in range(10):
    fh.note_day(tired)
check("the week is the last seven days only", len(fh.habits(tired)["stress_days"]) == fh.WEEK)

rng = random.Random(1)
calm_cooks = sum(fh.dinner_mode(person("x", stress=5), w, h, rng) == "cook" for _ in range(200))
worn_cooks = sum(fh.dinner_mode(person("y", stress=95), w, h, rng) == "cook" for _ in range(200))
check("a calm person cooks nearly always; a worn-out one mostly doesn't", calm_cooks > 180 and worn_cooks < 60, f"{calm_cooks} {worn_cooks}")
check("with nothing to cook there is no choice", fh.dinner_mode(person("x"), *setup(stocked=False), rng) == "easy" if False else fh.dinner_mode(person("x"), setup(False)[0], setup(False)[1], rng) == "easy")

# ---- choosing a recipe and ingredients by taste --------------------------------------------------------------------------------------------
w, h = setup()
lover = person("l")
lover["food_taste"] = {"chicken": 1.0, "ground_beef": -1.0, "rice": 0.8, "pasta": -0.8, "tomato": -0.5, "broccoli": 0.8, "cheese": 0, "herbs": 0}
options = cookware.feasible_recipes(h, 2)
hooked, steady = person("hk"), person("st")
hooked["food_habits"] = {"craving": 1.0, "comfort": 0.0, "stress_days": []}


def mean_addictive(who):
    got = [fh.choose_recipe(who, h, 2, options, random.Random(i)) for i in range(300)]
    return sum(fs.dish_from_items(cookware.pull_ingredients(dict(h, storage={"resources": [dict(r) for r in h["storage"]["resources"]]}), fs.DISH_RECIPES[r], 2), 2, "x")["addictive"] for r in got) / len(got)


check("a craving pulls them towards the more addictive dishes", mean_addictive(hooked) > mean_addictive(steady))
vessel = cookware.start_dinner(lover, w, h, recipe_id="roast_dinner")
used = {i["template_id"] for i in vessel["items"]}
check("and take the ingredients they prefer out of the stock", "chicken" in used or "ground_beef" not in used, str(used))

# ---- the planner: who cooks, and will they ----------------------------------------------------------------------------------------------------
w, h = setup(hour=16)
dinner.plan(w)
check("before dinner time nothing is planned", not h.get("dinner_day") and not any(c["active_intentions"] for c in w["characters"].values()))
w["calendar"]["hour"] = 17
random.seed(3)
dinner.plan(w)
cooks = [c for c in w["characters"].values() if any(i["type"] == "cook_dinner" for i in c["active_intentions"])]
check("at dinner time one calm person gets the job", len(cooks) == 1 and h["dinner_mode"]["mode"] == "cook", str(h.get("dinner_mode")))
dinner.plan(w)
check("... only once an evening", len([c for c in w["characters"].values() if c["active_intentions"]]) == 1)

w, h = setup()
for c in w["characters"].values():
    c["stress"] = 95
    c["food_habits"] = {"craving": 0.8, "comfort": 0.9, "stress_days": [95] * 7}
modes = []
for i in range(60):
    w2, h2 = setup()
    for c in w2["characters"].values():
        c.update(stress=95, food_habits={"craving": 0.8, "comfort": 0.9, "stress_days": [95] * 7})
    dinner.plan(w2, random.Random(i))
    modes.append(h2["dinner_mode"]["mode"])
check("a strained, comfort-eating household mostly takes the easy way out", modes.count("easy") > 40, str(modes.count("easy")))

w, h = setup(stocked=False)
dinner.plan(w)
check("with nothing in the cupboard nobody is sent to the stove", not any(c["active_intentions"] for c in w["characters"].values()))

w, h = setup()
w["characters"]["a"]["building_id"] = "work"
w["characters"]["b"]["age_group"] = "child"
w["characters"]["b"]["age"] = 8
dinner.plan(w)
check("a child never gets the job, and neither does anyone who's out", not h.get("dinner_day") and not any(c["active_intentions"] for c in w["characters"].values()))

# ---- the rota ---------------------------------------------------------------------------------------------------------------------------
w, h = setup(weekday="Tuesday", hour=17)
h["dinner_rota"] = {"cooks": {"monday": "a", "tuesday": "b", "wednesday": "a", "thursday": "b", "friday": "a"}, "dishes": "other"}
dinner.plan(w, random.Random(5))
check("the rota's cook is the one sent to the stove (when they are calm)", h["dinner_mode"]["cook"] == "b")

w, h = setup(weekday="Tuesday", hour=17)
h["dinner_rota"] = {"cooks": {"tuesday": "b"}, "dishes": "other"}
w["characters"]["b"]["building_id"] = "work"
dinner.plan(w)
check("... and if they aren't home yet the household waits", not h.get("dinner_day"))
w["calendar"]["hour"] = 19
w["calendar"]["minute"] = 0
dinner.plan(w)
check("... until half past six, then someone else steps in", h.get("dinner_mode", {}).get("cook") == "a")

check("with 'dishes: other' the one who didn't cook washes up", dinner_rota.washer_for(w, h, "a") == "b" and dinner_rota.washer_for(w, h, "b") == "a")
h["dinner_rota"]["dishes"] = "cook"
check("with 'dishes: cook' the cook washes up", dinner_rota.washer_for(w, h, "a") == "a")
check("with no rota the dishes are the cook's, or the household's named dish duty", dinner_rota.washer_for(w, {"dish_duty": "z"}, "a") == "z"
      and dinner_rota.washer_for(w, {}, "a") == "a")

wk = dinner_rota.assignments(["a", "b"], random.Random(2))
check("a week is shared out: both cook, nobody every night", set(wk.values()) == {"a", "b"} and list(wk) == list(dinner_rota.WEEKDAYS)
      and all(list(wk.values()).count(x) in (2, 3) for x in ("a", "b")), str(wk))

w, h = setup()
for _ in range(3):
    dinner_rota.note_cook(h, "a")
dinner_rota.note_cook(h, "b")
check("someone who made three of the last four is lopsided", dinner_rota.lopsided_cook(h) == "a")
prop = dinner_rota.maybe_propose(w, h, random.Random(1))
check("so they propose a rota to the other adult", prop and prop["kind"] == "dinner_rota" and prop["proposer_id"] == "a" and prop["recipients"] == ["b"]
      and "rota" in prop["params"]["text"].lower(), str(prop))
check("... only once", dinner_rota.maybe_propose(w, h, random.Random(1)) is None)
respond(w["characters"]["b"], w, prop["id"], "accept")
r = h.get("dinner_rota")
check("when they accept, the household has the rota", r and set(r["cooks"].values()) == {"a", "b"} and r["dishes"] in ("cook", "other"), str(r))

w, h = setup()
for _ in range(3):
    dinner_rota.note_cook(h, "a")
dinner_rota.note_cook(h, "a")
prop = dinner_rota.maybe_propose(w, h, random.Random(1))
respond(w["characters"]["b"], w, prop["id"], "decline")
check("if they decline there is no rota", not h.get("dinner_rota"))

w, h = setup()
for x in ("a", "b", "a", "b"):
    dinner_rota.note_cook(h, x)
check("a household that already shares it has nothing to propose", dinner_rota.maybe_propose(w, h) is None)

# the washer is the rota's when dinner ends
w, h = setup()
h["dinner_rota"] = {"cooks": {}, "dishes": "other"}
v = cookware.vessel_for(h, "pot")
cookware.load(v, cookware.pull_ingredients(h, fs.DISH_RECIPES["pasta_bolognese"], 2))
cookware.begin(w["characters"]["a"], w, v, "pasta_bolognese", 2)
w["tick"] = v["done_tick"]
cookware.update(w)
w["tick"] = v["serve_until_tick"]
w["characters"]["a"]["active_intentions"] = []
w["characters"]["b"]["active_intentions"] = []
cookware.update(w)

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
