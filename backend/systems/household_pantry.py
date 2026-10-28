"""
systems/household_pantry.py -- food in the house when somebody moves in.

A household created in the editor (or generated) started with nothing in its fridge or cupboards. Everybody was hungry within
hours, a hungry adult's only way out was an off-grid shopping trip or takeout (strategy.py::resolve_hunger_strategy -> "buy_food"),
and a hungry child could only wait for a parent. stock_pantry() gives a household that has no food at all one starter supply,
once (household["_pantry_stocked"]); after that, keeping the house stocked is the household's own business (shopping).
"""

import random

from systems.household_storage import ensure_household_storage

FOOD_TYPES = ("FOOD_PROTEIN", "FOOD_CARB", "FOOD_VEGETABLE", "FOOD_FRUIT", "FOOD_DAIRY", "FOOD_BREAD", "FOOD_SNACK", "FOOD_SPICE", "MEAL", "STORED_MEAL", "PROCESSED_MEAL")
# units per household member, by ingredient group (the actual ingredients are picked from data/ingredients.py)
STARTER_SUPPLY = (("protein", 6), ("carb", 6), ("vegetable", 6), ("fruit", 4), ("dairy", 3), ("bread", 2), ("none", 3), ("spice", 2))


def food_units(household):
    ensure_household_storage(household)
    return sum(r.get("quantity", 0) or 0 for r in household["storage"]["resources"] if r.get("resource_type") in FOOD_TYPES)


def stock_pantry(world, household):
    """Returns the number of units added (0 when the house already has food or was stocked before)."""
    if household.get("_pantry_stocked") is not None or food_units(household) > 0:
        household.setdefault("_pantry_stocked", world.get("tick", 0))
        return 0
    members = max(1, len(household.get("members", [])))
    added = 0
    for group, per_person in STARTER_SUPPLY:
        added += stock_group(household, group, per_person * members)
    household["_pantry_stocked"] = world.get("tick", 0)
    return added


def stock_group(household, group, units, rng=random):
    """Put `units` of a food group into the household's stock, spread over a few of the ingredients of that group."""
    from data.ingredients import INGREDIENTS
    from systems.cookware import add_stock
    choices = [tid for tid, t in INGREDIENTS.items() if t["food_group"] == group]
    if not choices or units <= 0:
        return 0
    for _ in range(units):
        add_stock(household, rng.choice(choices), 1)
    return units


def restock(world, household, shopper):
    """A grocery trip (systems/grocery.py): the shopper buys what their plan for the coming dinners needs, paid from their money (or, with
    none, the household's wealth, and failing that on credit -- nobody comes home empty-handed from a food shop). {"units", "cost"} or None."""
    if not household:
        return None
    from systems import grocery
    got = grocery.buy(world, household, shopper)
    return {"units": got["units"], "cost": got["cost"]}
