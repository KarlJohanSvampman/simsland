"""
systems/eating.py -- what is being eaten, and where.

The model's `eat` action can name anything as its target (a food item, a prop, even a person). The router used to start eating on the
spot, wherever the character stood -- a bathroom -- with no food chosen, so with a person (or nothing) as the target nothing was
eaten at all and nobody could say what the meal was. Now every `eat` resolves to
  * a real food item: the one named, else the first edible thing they carry, else the first edible thing in the household's storage;
  * a real eating place: the nearest free "eat" anchor (a dining table) in the building they are in;
and the food is written on the activity (`act["state"]["food_id"]`, `["food_name"]`) so it can be shown and consumed at the end.

    resolve_meal(c, world, target_id) -> {"item", "place"} | None     (None: nothing to eat -- the caller uses the hunger strategy)
"""


def _props(world):
    props = world.get("props", [])
    return list(props.values()) if isinstance(props, dict) else props


def is_food(item):
    return bool(item) and (item.get("category") == "food" or item.get("edible"))


def food_name(item):
    return str(item.get("name") or item.get("template_id") or "food").replace("_", " ")


def _pools(c, world):
    yield c.get("inventory", [])
    yield c.get("held_stack", [])
    from systems.activities import _household_storage_containers
    for container in _household_storage_containers(c, world):
        yield container.get("items", [])


def find_item(c, world, item_id):
    """The item with this id, wherever it is (not removed)."""
    if not item_id:
        return None
    for pool in _pools(c, world):
        for item in pool:
            if item.get("id") == item_id:
                return item
    return (world.get("placed_items") or {}).get(item_id)


def pick_food(c, world):
    """What they carry first, then what the household keeps."""
    for pool in _pools(c, world):
        for item in pool:
            if is_food(item):
                return item
    return None


def eating_place(c, world):
    """The nearest prop in their building with a free eat anchor (a dining table), else None."""
    from systems.occupancy import find_free_anchor
    from systems.props import prop_distance
    building = c.get("building_id")
    places = [p for p in _props(world) if (not building or p.get("building_id") == building) and find_free_anchor(p, "eat")]
    return min(places, key=lambda p: prop_distance(c, p)) if places else None


def weakness_of(c):
    """How much this person is drawn to meat, fat and a big helping, each -1..1 (negative: puts them off). Fixed per person."""
    if "food_weakness" not in c:
        import random
        rng = random.Random(f"weakness:{c.get('id')}")
        c["food_weakness"] = {k: round(max(-1.0, min(1.0, rng.gauss(0.2, 0.5))), 2) for k in ("meat", "fat", "calories")}
    return c["food_weakness"]


def _household(c, world):
    return (world.get("households") or {}).get(c.get("household_id"))


def served_plate(c, world):
    """One plate of what the household has cooked and is still serving (a portion comes off the vessel), or None."""
    household = _household(c, world)
    if not household:
        return None
    from systems import cookware
    vessel = cookware.ready_vessel(household, world.get("tick", 0))
    if vessel:
        return cookware.take_portion(vessel, world, weakness_of(c))
    plate = cookware.take_leftover(household, weakness_of(c))
    if plate:
        return plate
    from systems import ready_meals
    return ready_meals.take(household, c)


SANDWICH_FILLINGS = (("protein", 1), ("dairy", 1), ("vitamin", 1))      # what goes between the bread: one of each, if there is any
SANDWICH_ODDS = 0.6                                                      # a person with bread and fillings in the house usually builds one


def sandwich_item(c, world, rng=None):
    """A slice of bread takes fillings from the stock and turns into a sandwich: one item, eaten as it is, scored like any dish
    (health, taste, calories, what is in it). Returns the item, or None when there is no bread or nothing to put in it."""
    import random
    import uuid
    from systems import cookware, food_scoring as fs, food_habits
    rng = rng or random
    household = _household(c, world)
    if not household:
        return None
    breads = cookware.stock(household, "bread")
    if not breads:
        return None
    parts = []
    from data.ingredients import INGREDIENTS
    for group, n in SANDWICH_FILLINGS:
        # fruit shares the vegetables' recipe group but doesn't go in a sandwich
        rows = sorted((r for r in cookware.stock(household, group) if group != "vitamin" or INGREDIENTS[cookware.row_template(r)]["food_group"] == "vegetable"),
                      key=lambda r: -food_habits.liking(c, cookware.row_template(r)))
        if rows:
            parts.append((rows[0], n))
    if not parts:
        return None
    bread = max(breads, key=lambda r: r.get("quantity", 0))
    taken = []
    for row, n in [(bread, 1)] + parts:
        take = min(n, row["quantity"])
        row["quantity"] -= take
        taken.append({"template_id": cookware.row_template(row), "quantity": take})
    household["storage"]["resources"][:] = [r for r in household["storage"]["resources"] if (r.get("quantity") or 0) > 0 or not str(r.get("resource_type", "")).startswith("FOOD_")]
    dish = fs.dish_from_items(taken, 1, "Sandwich")
    item = cookware.plate_item(dish)
    item.update(id=f"sandwich_{uuid.uuid4().hex[:8]}", template_id="sandwich", name="Sandwich", dish_name="Sandwich", food_group="dish")
    return item


def stock_item(c, world, groups=("fruit", "bread", "none")):
    """One ready-to-eat item out of the household's stock (fruit, bread, a snack), as an item they now hold, or None. Bread with something
    to put in it is usually made into a sandwich."""
    household = _household(c, world)
    if not household:
        return None
    if "bread" in groups:
        import random
        if random.random() < SANDWICH_ODDS:
            sandwich = sandwich_item(c, world)
            if sandwich:
                return sandwich
    import uuid
    from data.item_templates import get_template
    from systems import cookware
    rows = [r for r in cookware.stock(household) if (get_template(cookware.row_template(r)) or {}).get("food_group") in groups]
    if not rows:
        return None
    row = max(rows, key=lambda r: ((get_template(cookware.row_template(r)) or {}).get("food_group") == "fruit", r.get("quantity", 0)))
    tid = cookware.row_template(row)
    row["quantity"] -= 1
    if row["quantity"] <= 0:
        household["storage"]["resources"].remove(row)
    return {**get_template(tid), "id": f"item_{tid}_{uuid.uuid4().hex[:6]}", "template_id": tid, "quantity": 1}


def meal_reaction(item, c=None):
    """What they would honestly say about it, for anything that carries a taste (a plate) or calories (an ingredient). Given the
    eater, their own likes for what is in it count (systems/food_habits.py)."""
    from systems import food_scoring as fs, food_habits
    if c is not None and (item.get("taste") is not None or item.get("calories")):
        return fs.reaction(food_habits.personal_taste(c, item))
    if item.get("taste") is not None:
        return fs.reaction(item["taste"])
    if item.get("calories"):
        group = item.get("food_group")
        if group in ("fruit", "bread", "none"):
            health = fs.dish_from_items([item])["health"]
            return fs.reaction(fs.taste_of(health))
    return None


def resolve_meal(c, world, target_id):
    """What they eat: the item they named; else a plate of what is being served; else what they carry or the household keeps."""
    item = find_item(c, world, target_id)
    if not is_food(item):
        item = served_plate(c, world)
        if item:
            c.setdefault("inventory", []).append(item)       # on the plate in their hands until they have eaten it
    if not item:
        item = pick_food(c, world)
    if not item:
        item = stock_item(c, world)
        if item:
            c.setdefault("inventory", []).append(item)
    if not item:
        return None
    return {"item": item, "place": eating_place(c, world)}


def food_context(c, world):
    """What the person knows about food right now: dinner served or cooking in their house, and how their last meal was."""
    lines = []
    household = _household(c, world)
    tick = world.get("tick", 0)
    if household:
        for v in household.get("cookware", []):
            if v["state"] == "ready" and v.get("charges", 0) > 0 and tick < v.get("serve_until_tick", 0):
                lines.append(f"{v['dish']['name']} is served at home ({v['charges']} portion{'s' if v['charges'] != 1 else ''} left).")
            elif v["state"] == "cooking":
                lines.append(f"{v['dish']['name']} is cooking, ready in about {max(1, round((v['done_tick'] - tick) / 60))} minutes.")
        if any(l.get("portions", 0) > 0 for l in household.get("leftovers", [])):
            lines.append("There are leftovers in the fridge.")
    meal = c.get("last_meal")
    if meal and tick - meal.get("tick", 0) < 3 * 3600 and meal.get("reaction"):
        lines.append(f"Your last meal, {meal.get('name') or 'the food'}, was {meal['reaction']}.")
    return lines
