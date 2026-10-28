"""
systems/cookware.py -- pots, pans and the oven (docs/food_system.md).

Every vessel has a built-in inventory and one life:

    empty -> loaded -> cooking -> ready (charges = portions) -> dirty -> (washed) -> empty

  * load:    ingredients are pulled from the household's stock into the vessel (`pull_ingredients`)
  * begin:   the cook starts it (`begin`); it then cooks by itself for a realistic time -- nobody has to stand there
  * ready:   `update(world)` finishes it; it holds `charges` portions and the dish, served for 1-2 hours
  * a portion: `take_portion` hands over ONE plated dish (what is eaten, with its own calories / fat / health / taste) and
               takes one charge off the vessel
  * after the serving window the food is closed out (`close_out`): the leftovers go in a container in the fridge, or the trash,
    and the vessel is dirty until it is washed

The household's food is a list of stacks, `household["storage"]["resources"]`, each naming its ingredient (`template_id`).
"""

import random
import uuid

from data.ingredients import INGREDIENTS
from data.item_templates import get_template
from systems import food_scoring as fs

VESSEL_KINDS = ("pot", "pan", "oven")
CAPACITY = {"pot": 12, "pan": 8, "oven": 16}
SERVE_WINDOW = (3600, 7200)             # ticks (= sim seconds): the food stays served for 1-2 hours

# the household pool's resource type for each ingredient group, and the stack a legacy row without a name stands for
RESOURCE_OF_GROUP = {"protein": "FOOD_PROTEIN", "carb": "FOOD_CARB", "vegetable": "FOOD_VEGETABLE", "fruit": "FOOD_FRUIT",
                     "dairy": "FOOD_DAIRY", "bread": "FOOD_BREAD", "none": "FOOD_SNACK", "spice": "FOOD_SPICE"}
LEGACY_TEMPLATE = {"FOOD_PROTEIN": "chicken", "FOOD_CARB": "rice", "FOOD_VEGETABLE": "carrot", "FOOD_FRUIT": "apple",
                   "FOOD_DAIRY": "cheese", "FOOD_BREAD": "bread_loaf", "FOOD_SNACK": "bag_of_chips", "FOOD_SPICE": "salt"}


# ---- the household's stacks -----------------------------------------------------------------------------------------------------------------
def _rows(household):
    return household.setdefault("storage", {}).setdefault("resources", [])


def row_template(row):
    return row.get("template_id") or LEGACY_TEMPLATE.get(row.get("resource_type"))


def row_group(row):
    t = INGREDIENTS.get(row_template(row)) or {}
    if t.get("spice"):
        return "spice"
    g = t.get("food_group")
    return "vitamin" if g in ("fruit", "vegetable") else g


def stock(household, group=None):
    """[(row, template_id)] of food stacks, optionally of one recipe group."""
    out = []
    for row in _rows(household):
        if str(row.get("resource_type", "")).startswith("FOOD_") and (row.get("quantity") or 0) > 0:
            if group is None or row_group(row) == group:
                out.append(row)
    return out


def add_stock(household, template_id, quantity):
    """Put `quantity` of a named ingredient into the household's stock (merging into its stack)."""
    t = INGREDIENTS[template_id]
    rtype = RESOURCE_OF_GROUP[t["food_group"]]
    for row in _rows(household):
        if row.get("resource_type") == rtype and row_template(row) == template_id:
            row["quantity"] = (row.get("quantity") or 0) + quantity
            return row
    row = {"resource_type": rtype, "template_id": template_id, "quantity": quantity, "freshness": 1.0}
    _rows(household).append(row)
    return row


def _have(household, group):
    return sum(r.get("quantity") or 0 for r in stock(household, group))


def can_make(household, rec, people):
    return all(_have(household, g) >= n for g, n in fs.units_needed(rec, people).items())


def feasible_recipes(household, people):
    return [rid for rid, rec in fs.DISH_RECIPES.items() if can_make(household, rec, people)]


def pull_ingredients(household, rec, people, rank=None):
    """Take what the recipe needs out of the stock. `rank(template_id)` orders the choices (higher first) -- who likes what.
    Returns the taken items, or None (nothing is removed) when something is short."""
    need = fs.units_needed(rec, people)
    if not can_make(household, rec, people):
        return None
    taken = []
    for group, n in need.items():
        rows = sorted(stock(household, group), key=lambda r: -(rank(row_template(r)) if rank else 0))
        for row in rows:
            if n <= 0:
                break
            take = min(n, row["quantity"])
            row["quantity"] -= take
            n -= take
            taken.append({"template_id": row_template(row), "quantity": take})
    _rows(household)[:] = [r for r in _rows(household) if (r.get("quantity") or 0) > 0 or not str(r.get("resource_type", "")).startswith("FOOD_")]
    return taken


# ---- the vessels -----------------------------------------------------------------------------------------------------------------------------
def ensure_vessels(household):
    vessels = household.setdefault("cookware", [])
    have = {v["kind"] for v in vessels}
    for kind in VESSEL_KINDS:
        if kind not in have:
            vessels.append({"id": f"{kind}_{uuid.uuid4().hex[:6]}", "kind": kind, "state": "empty", "items": [], "capacity": CAPACITY[kind]})
    return vessels


def vessel_for(household, kind):
    return next((v for v in ensure_vessels(household) if v["kind"] == kind and v["state"] == "empty"), None)


def load(vessel, items):
    if vessel["state"] != "empty":
        return False
    vessel["items"] = list(items)
    vessel["state"] = "loaded"
    return True


def begin(c, world, vessel, recipe_id, people):
    """The cook starts cooking what is in the vessel; from here it needs nobody."""
    rec = fs.DISH_RECIPES[recipe_id]
    people = max(1, people)
    dish = fs.dish_from_items(vessel["items"], people, name=rec["name"])
    dish["recipe_id"] = recipe_id
    tick = world.get("tick", 0)
    vessel.update({"state": "cooking", "recipe_id": recipe_id, "people": people, "maker_id": c.get("id"), "dish": dish,
                   "started_tick": tick, "done_tick": tick + fs.cook_minutes(rec, people) * 60, "charges": 0})
    return vessel


def name_legacy_stock(household, rng=random):
    """Stacks from before ingredients had names ("FOOD_CARB x18") become a spread of named ingredients of that kind, once."""
    group_of_type = {rtype: g for g, rtype in RESOURCE_OF_GROUP.items()}
    rows = _rows(household)
    legacy = [r for r in rows if str(r.get("resource_type", "")).startswith("FOOD_") and not r.get("template_id")]
    for row in legacy:
        group = group_of_type.get(row["resource_type"])
        rows.remove(row)
        choices = [tid for tid, t in INGREDIENTS.items() if t["food_group"] == group]
        for _ in range(int(row.get("quantity") or 0)):
            add_stock(household, rng.choice(choices), 1)
    household["_stock_named"] = True


def update(world):
    """Finish what is done, and close out food whose serving window has passed. Run about once a minute."""
    tick = world.get("tick", 0)
    for household in world.get("households", {}).values():
        if not household.get("_stock_named"):
            name_legacy_stock(household)
        for v in household.get("cookware", []):
            if v["state"] == "cooking" and tick >= v["done_tick"]:
                v["state"] = "ready"
                v["charges"] = v["people"]
                v["ready_tick"] = tick
                v["serve_until_tick"] = tick + random.randint(*SERVE_WINDOW)
                announce(world, household, v)
            elif v["state"] == "ready" and tick >= v.get("serve_until_tick", 0):
                v["expired"] = True
                end_of_dinner(world, household, v)


def announce(world, household, vessel):
    """The food is ready: the cook says so to everyone home, and everyone home (the cook too) is drawn to the table."""
    from brain.intentions import add_intention
    from systems.incidental_speech import fire_incidental
    characters = world.get("characters", {})
    maker = characters.get(vessel.get("maker_id"))
    vessel["announce_pending"] = False
    if maker:
        here = maker.get("building_id")
        home = [characters[m] for m in household.get("members", []) if m in characters and characters[m].get("building_id") == here]
        if len(home) > 1:
            fire_incidental(maker, "inform", f"{vessel['dish']['name']} is ready -- come and eat!", world)
        for who in home:
            add_intention(who, {"type": "eat_food", "category": "survival", "priority": 55, "reason": "dinner is served"})


def end_of_dinner(world, household, vessel):
    """The serving window is over: what is left is stored for later if it was good, else binned, and the cook sees to the dishes --
    unless the household has agreed that someone else washes up."""
    from systems.chores import add_dirty_dishes, kitchen_zone_key
    from brain.intentions import add_intention
    dish = vessel.get("dish") or {}
    close_out(household, vessel, store=dish.get("taste", 0) >= 0.4)
    add_dirty_dishes(household, 1)
    characters = world.get("characters", {})
    from systems import dinner_rota
    washer = characters.get(dinner_rota.washer_for(world, household, vessel.get("maker_id")))
    zone = kitchen_zone_key(world, household)
    if washer and zone:
        add_intention(washer, {"type": "clean_zone", "category": "chores", "priority": 50, "reason": "the dishes from dinner", "zone_key": zone})


def ready_vessel(household, tick):
    """A vessel with portions left that is still being served."""
    for v in household.get("cookware", []):
        if v["state"] == "ready" and v.get("charges", 0) > 0 and tick < v.get("serve_until_tick", 0):
            return v
    return None


def take_portion(vessel, world, weakness=None):
    """One plate: a plated-dish item with its own numbers, and one charge fewer. None when there is nothing to take."""
    if vessel["state"] != "ready" or vessel.get("charges", 0) <= 0:
        return None
    plate = plate_item(vessel["dish"], weakness)
    vessel["charges"] -= 1
    if vessel["charges"] <= 0:
        vessel["state"] = "dirty"
    return plate


def plate_item(dish, weakness=None):
    """The item one person eats: a plate of this dish, with the numbers of the mix they actually took."""
    plate = fs.plate_from_dish(dish, weakness)
    return {
        "id": f"plate_{uuid.uuid4().hex[:8]}", "template_id": "plated_dish", "name": f"{dish['name']} (plate)",
        "category": "food", "food_group": "dish", "edible": True, "consumable": True, "uses": 1, "size": 1, "stackable": False,
        "calories": plate["calories"], "fat_pct": plate["fat_pct"], "health": plate["health"], "taste": plate["taste"],
        "addictive": plate["addictive"], "ingredients": list(dish.get("ingredients") or []), "dish_name": dish["name"], "recipe_id": dish.get("recipe_id"),
        "nutrition": round(plate["calories"] / 2000, 3), "hunger_restore": round(plate["calories"] / 8),
    }


def take_leftover(household, weakness=None):
    """One plate from the leftovers in the fridge, or None."""
    for left in household.get("leftovers", []):
        if left.get("portions", 0) > 0:
            left["portions"] -= 1
            plate = plate_item(left["dish"], weakness)
            if left["portions"] <= 0:
                household["leftovers"].remove(left)
            return plate
    return None


def close_out(household, vessel, store=True):
    """The serving window is over: what is left goes into a container in the fridge (store) or the trash; the vessel is dirty.
    Returns the leftovers item, or None."""
    leftovers = None
    if store and vessel.get("charges", 0) > 0 and vessel.get("dish"):
        d = vessel["dish"]
        leftovers = {"id": f"leftovers_{uuid.uuid4().hex[:8]}", "template_id": "leftovers", "name": f"Leftover {d['name']}",
                     "category": "food", "food_group": "dish", "edible": True, "portions": vessel["charges"],
                     "dish": dict(d), "stored_tick": None}
        household.setdefault("leftovers", []).append(leftovers)
    vessel.update({"state": "dirty", "charges": 0, "expired": False, "announce_pending": False})
    return leftovers


def wash(household):
    """Every dirty vessel is clean again."""
    n = 0
    for v in household.get("cookware", []):
        if v["state"] == "dirty":
            v.update({"state": "empty", "items": [], "dish": None, "recipe_id": None, "charges": 0})
            n += 1
    return n


# ---- the cook's side ------------------------------------------------------------------------------------------------------------------------
def people_at_home(c, world, household):
    """Who dinner is for: the cook and the household's members who are home with them."""
    here = c.get("building_id")
    n = 1
    for mid in household.get("members", []):
        other = world.get("characters", {}).get(mid)
        if other and other.get("id") != c.get("id") and other.get("building_id") == here:
            n += 1
    return n


def start_dinner(c, world, household, rank=None, recipe_id=None):
    """Decide a recipe and how many it is for, take the ingredients out of the stock into a free pot, pan or oven, and begin.
    The cook's own tastes pick the recipe and which ingredients go in (systems/food_habits.py).
    Returns the vessel, or None when there is nothing they can make."""
    from systems import food_habits
    ensure_vessels(household)
    rank = rank or food_habits.rank_fn(c)
    people = people_at_home(c, world, household)
    while people >= 1:
        options = [r for r in ([recipe_id] if recipe_id else feasible_recipes(household, people))
                   if can_make(household, fs.DISH_RECIPES[r], people) and vessel_for(household, fs.DISH_RECIPES[r]["method"])]
        if options:
            rid = recipe_id or food_habits.choose_recipe(c, household, people, options)
            rec = fs.DISH_RECIPES[rid]
            vessel = vessel_for(household, rec["method"])
            load(vessel, pull_ingredients(household, rec, people, rank))
            from systems import dinner_rota
            dinner_rota.note_cook(household, c.get("id"))
            return begin(c, world, vessel, rid, people)
        people -= 1
    return None
