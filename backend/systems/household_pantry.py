"""
systems/household_pantry.py -- food in the house when somebody moves in.

A household created in the editor (or generated) started with nothing in its fridge or cupboards. Everybody was hungry within
hours, a hungry adult's only way out was an off-grid shopping trip or takeout (strategy.py::resolve_hunger_strategy -> "buy_food"),
and a hungry child could only wait for a parent. stock_pantry() gives a household that has no food at all one starter supply,
once (household["_pantry_stocked"]); after that, keeping the house stocked is the household's own business (shopping).
"""

from systems.household_storage import create_household_resource, ensure_household_storage

FOOD_TYPES = ("FOOD_PROTEIN", "FOOD_CARB", "FOOD_VEGETABLE", "FOOD_FRUIT", "FOOD_SNACK", "FOOD_SPICE", "MEAL", "STORED_MEAL", "PROCESSED_MEAL")
# units per household member
STARTER_SUPPLY = (("FOOD_PROTEIN", 6), ("FOOD_CARB", 6), ("FOOD_VEGETABLE", 6), ("FOOD_FRUIT", 4), ("FOOD_SNACK", 4), ("FOOD_SPICE", 2))


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
    for resource_type, per_person in STARTER_SUPPLY:
        create_household_resource(household, resource_type, quantity=per_person * members)
        added += per_person * members
    household["_pantry_stocked"] = world.get("tick", 0)
    return added


TRIP_PER_PERSON = (("FOOD_PROTEIN", 4), ("FOOD_CARB", 4), ("FOOD_VEGETABLE", 4), ("FOOD_FRUIT", 3), ("FOOD_SNACK", 3))
COST_PER_PERSON = 14.0


def restock(world, household, shopper):
    """A grocery trip brings home a few days of food for the household, paid from the shopper's money (or, with none, the household's
    wealth, and failing that on credit -- nobody comes home empty-handed from a food shop). Returns {"units", "cost"} or None."""
    if not household:
        return None
    members = max(1, len(household.get("members", [])))
    cost = COST_PER_PERSON * members
    paid = min(cost, shopper.get("money", 0) or 0)
    shopper["money"] = (shopper.get("money", 0) or 0) - paid
    rest = cost - paid
    if rest > 0:
        household["wealth"] = max(0, (household.get("wealth", 0) or 0) - rest)
    units = 0
    for resource_type, per_person in TRIP_PER_PERSON:
        create_household_resource(household, resource_type, quantity=per_person * members)
        units += per_person * members
    return {"units": units, "cost": cost}
