"""
systems/grocery.py -- shopping by recipe, ratio and budget (docs/food_system.md, section 7).

A trip is planned before the shopper leaves: they choose which dinners they want over the coming days (by their own tastes), and the
plan is those recipes' ratios times the people they are cooking for. What they can spend is a number of units (the money they can lay
their hands on, at the going price of an ingredient); if the plan costs more than that, the last dinners are dropped until it fits. The
plan puts the recipes on the household's evening dinners -- `household["dinner_plan"] = {weekday: recipe_id}` and the `recipe_id` on the
adults' evening "eat" schedule block -- and the cook follows it when they start dinner (cookware.start_dinner).

    household["shopping_plan"] = {"meals": [{"day", "recipe_id", "people"}], "need": {group: units}, "budget_units": n, "shopper_id": id}

`buy(world, household, shopper)` is the trip itself: it picks named ingredients for each group (the shopper's tastes, mindful of price),
pays for them, and lays in a few extras (fruit, bread, a snack) with what is left over.
"""

import random

from data.dishes import DISH_RECIPES
from data.ingredients import INGREDIENTS
from systems import food_habits, food_scoring as fs

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DINNERS_PER_TRIP = 4
EXTRAS_PER_PERSON = {"fruit": 2, "bread": 1, "none": 1}        # not part of any recipe: breakfasts, lunches, something to nibble
MIN_FUNDS = 5.0                                                 # nobody goes home without anything at all


def price_of(template_id):
    return INGREDIENTS[template_id]["base_price"]


def average_price(group):
    prices = [t["base_price"] for t in INGREDIENTS.values() if t["food_group"] == group or (group == "spice" and t.get("spice"))]
    return sum(prices) / len(prices) if prices else 1.0


def funds(shopper, household):
    return max(MIN_FUNDS, (shopper.get("money", 0) or 0)) + 0.0


def _next_days(world, n):
    today = (world.get("calendar", {}).get("weekday") or "monday").lower()
    i = WEEKDAYS.index(today) if today in WEEKDAYS else 0
    return [WEEKDAYS[(i + k) % 7] for k in range(1, n + 1)]


def cost_of_units(need):
    return sum(units * average_price(group) for group, units in need.items())


def need_for(meals):
    need = {}
    for meal in meals:
        for group, n in fs.units_needed(DISH_RECIPES[meal["recipe_id"]], meal["people"]).items():
            need[group] = need.get(group, 0) + n
    return need


def make_plan(world, household, shopper, rng=random):
    """The shopper's list for the coming days, kept within their budget. Stored on the household and returned."""
    chars = world.get("characters", {})
    people = max(1, len([m for m in household.get("members", []) if m in chars]))
    pool = [rid for rid in DISH_RECIPES]
    taste = {rid: max(0.05, 1.0 + 2.0 * _fancy(shopper, rid)) for rid in pool}
    meals, last = [], None
    for day in _next_days(world, DINNERS_PER_TRIP):
        weights = [taste[r] * (0.3 if r == last else 1.0) for r in pool]
        rid = rng.choices(pool, weights=weights, k=1)[0]
        meals.append({"day": day, "recipe_id": rid, "people": people})
        last = rid
    budget_units = int(funds(shopper, household) / max(0.2, _mean_unit_price(meals)))
    while len(meals) > 1 and sum(need_for(meals).values()) > budget_units:
        meals.pop()                                                # cannot afford the last one: leave it for the next trip
    plan = {"meals": meals, "need": need_for(meals), "budget_units": budget_units, "shopper_id": shopper.get("id"),
            "tick": world.get("tick", 0)}
    household["shopping_plan"] = plan
    return plan


def _fancy(c, rid):
    """How much they fancy a dish from the ingredients of its kind they like best (the recipe is only a ratio of groups)."""
    rec = DISH_RECIPES[rid]
    total, n = 0.0, 0
    for group in fs.units_needed(rec, 1):
        liked = [food_habits.liking(c, tid) for tid, t in INGREDIENTS.items() if t["food_group"] == group or (group == "vitamin" and t["food_group"] in ("fruit", "vegetable"))]
        if liked:
            total += max(liked)
            n += 1
    return (total / n if n else 0.0) + 0.5 * food_habits.craving(c) * (1 - _health_guess(rec))


def _health_guess(rec):
    """Roughly how healthy a recipe is from its ratio alone (vitamins are what lift it)."""
    per = fs.units_needed(rec, 1)
    total = sum(per.values()) or 1
    return min(1.0, 0.3 + 1.2 * per.get("vitamin", 0) / total)


def _mean_unit_price(meals):
    need = need_for(meals)
    units = sum(need.values()) or 1
    return cost_of_units(need) / units


def _pick(shopper, group, rng):
    """One ingredient of a group: what they like, held back by price."""
    options = [tid for tid, t in INGREDIENTS.items() if (t["food_group"] == group and not t.get("spice")) or (group == "spice" and t.get("spice"))
               or (group == "vitamin" and t["food_group"] in ("fruit", "vegetable"))]
    weights = [max(0.05, 1.0 + 2.0 * food_habits.liking(shopper, tid) - 0.25 * price_of(tid)) for tid in options]
    return rng.choices(options, weights=weights, k=1)[0]


def buy(world, household, shopper, rng=random):
    """The trip: buy what the plan needs (planning it now if the shopper hadn't), pay, and lay in the extras. Returns {"units", "cost"}."""
    from systems.cookware import add_stock
    plan = household.get("shopping_plan") or make_plan(world, household, shopper, rng)
    bought, cost = {}, 0.0
    for group, units in plan["need"].items():
        for _ in range(units):
            tid = _pick(shopper, group, rng)
            add_stock(household, tid, 1)
            bought[tid] = bought.get(tid, 0) + 1
            cost += price_of(tid)
    people = max(1, len(household.get("members", [])))
    left = funds(shopper, household) - cost
    for group, per_person in EXTRAS_PER_PERSON.items():
        for _ in range(per_person * people):
            tid = _pick(shopper, group, rng)
            if left < price_of(tid):
                break
            add_stock(household, tid, 1)
            bought[tid] = bought.get(tid, 0) + 1
            cost += price_of(tid)
            left -= price_of(tid)
    from data.ready_meals import READY_MEALS, STORE_MEALS
    from systems import ready_meals
    for _ in range(round(people * (0.3 + food_habits.pressure(shopper) / 60.0))):
        tid = rng.choice(STORE_MEALS)
        if left < READY_MEALS[tid]["store_price"]:
            break
        ready_meals.add(household, tid, world.get("tick", 0))
        bought[tid] = bought.get(tid, 0) + 1
        cost += READY_MEALS[tid]["store_price"]
        left -= READY_MEALS[tid]["store_price"]
    paid = min(cost, shopper.get("money", 0) or 0)
    shopper["money"] = (shopper.get("money", 0) or 0) - paid
    if cost > paid:
        household["wealth"] = max(0, (household.get("wealth", 0) or 0) - (cost - paid))
    put_on_schedule(world, household, plan)
    household.pop("shopping_plan", None)
    return {"units": sum(bought.values()), "cost": round(cost, 2), "bought": bought}


def put_on_schedule(world, household, plan):
    """The planned recipes go on the household's evenings, and onto the adults' own schedule blocks for dinner."""
    dinner_plan = household.setdefault("dinner_plan", {})
    for meal in plan["meals"]:
        dinner_plan[meal["day"]] = meal["recipe_id"]
    for mid in household.get("members", []):
        week = ((world.get("characters", {}).get(mid) or {}).get("schedule") or {}).get("week") or {}
        for day, rid in dinner_plan.items():
            for block in week.get(day, []):
                if block.get("activity") == "eat" and block.get("start") == "18:00":
                    block["recipe_id"] = rid


def planned_recipe(household, world):
    """Tonight's planned recipe, if the household shopped for one."""
    day = (world.get("calendar", {}).get("weekday") or "").lower()
    return (household.get("dinner_plan") or {}).get(day)


def consumed(household, world):
    """Tonight's planned dinner has been started: it comes off the plan."""
    day = (world.get("calendar", {}).get("weekday") or "").lower()
    (household.get("dinner_plan") or {}).pop(day, None)
