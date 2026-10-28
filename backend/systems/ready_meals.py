"""
systems/ready_meals.py -- processed food and takeout (docs/food_system.md, section 7).

Every ready meal is its own item in `household["ready_meals"]`, with its own temperature:

    {"id", "template_id", "name", "calories", "fat_pct", "health", "taste", "addictive", "temperature": "cold" | "warm", "warm_until_tick"}

  * bought in a shop (systems/grocery.py): cold -- it needs the microwave (the `heat_meal` activity, `warm_one`) before it is eaten
  * ordered as takeout (`order_takeout`): paid for now, delivered a little later, warm -- and cold again once `WARM_FOR` has passed
  * eaten (`take`): a plated item like any other meal, so calories, fat, craving and taste work the same way
"""

import random
import uuid

from data.ready_meals import READY_MEALS, TAKEOUT_MEALS
from systems import food_scoring as fs

WARM_FOR = 40 * 60                  # a warm meal stays warm for about forty minutes (ticks are sim seconds)
DELIVERY = (20 * 60, 45 * 60)       # takeout turns up this long after it is ordered
PROCESSED_BOOST = 0.04              # engineered to taste good


def meals(household):
    return household.setdefault("ready_meals", [])


def instance(template_id, tick, temperature="cold"):
    t = READY_MEALS[template_id]
    health = t["health"]
    meal = {"id": f"ready_{uuid.uuid4().hex[:8]}", "template_id": template_id, "name": t["name"], "calories": t["calories"], "fat_pct": t["fat_pct"],
            "health": health, "taste": min(1.0, fs.taste_of(health, t["spice_taste"], 1) + PROCESSED_BOOST), "addictive": fs.addictive_of(health),
            "temperature": temperature, "ready_made": True}
    if temperature == "warm":
        meal["warm_until_tick"] = tick + WARM_FOR
    return meal


def add(household, template_id, tick, quantity=1, temperature="cold"):
    for _ in range(quantity):
        meals(household).append(instance(template_id, tick, temperature))


def count(household, temperature=None):
    return len([m for m in meals(household) if temperature is None or m["temperature"] == temperature])


def cool_down(world):
    """Warm meals that have been left go cold."""
    tick = world.get("tick", 0)
    for household in world.get("households", {}).values():
        for m in household.get("ready_meals", []):
            if m["temperature"] == "warm" and tick >= m.get("warm_until_tick", 0):
                m["temperature"] = "cold"
                m.pop("warm_until_tick", None)


def warm_one(household, tick):
    """The microwave: the first cold meal becomes warm. Returns it, or None."""
    for m in meals(household):
        if m["temperature"] == "cold":
            m["temperature"] = "warm"
            m["warm_until_tick"] = tick + WARM_FOR
            return m
    return None


def take(household, c=None):
    """A warm ready meal as the item to eat (it leaves the household), or None."""
    for m in meals(household):
        if m["temperature"] == "warm":
            meals(household).remove(m)
            return dict(m, category="food", food_group="dish", edible=True, consumable=True, uses=1, size=1, stackable=False,
                        dish_name=m["name"], ingredients=[], nutrition=round(m["calories"] / 2000, 3), hunger_restore=round(m["calories"] / 8))
    return None


def order_takeout(c, world, household, rng=random):
    """Order for the people at home: paid for now, delivered a little later by `deliver`. Returns the order, or None if they can't pay."""
    chars = world.get("characters", {})
    here = [chars[m] for m in household.get("members", []) if m in chars and chars[m].get("building_id") == c.get("building_id")] or [c]
    choices = sorted(TAKEOUT_MEALS, key=lambda t: -(1.0 + 1.5 * (1 - READY_MEALS[t]["health"]) * _craving(c)))
    pick = rng.choice(choices[:4])
    cost = READY_MEALS[pick]["takeout_price"] * len(here)
    if (c.get("money", 0) or 0) < cost:
        pick = min(TAKEOUT_MEALS, key=lambda t: READY_MEALS[t]["takeout_price"])
        cost = READY_MEALS[pick]["takeout_price"] * len(here)
        if (c.get("money", 0) or 0) < cost:
            return None
    c["money"] = c["money"] - cost
    order = {"template_id": pick, "portions": len(here), "cost": cost, "orderer_id": c.get("id"),
             "arrives_tick": world.get("tick", 0) + rng.randint(*DELIVERY)}
    household.setdefault("deliveries", []).append(order)
    return order


def _craving(c):
    from systems import food_habits
    return food_habits.craving(c)


def deliver(world):
    """Takeout that has arrived is put on the table, warm, and the people at home are called to eat it."""
    from brain.intentions import add_intention
    tick = world.get("tick", 0)
    chars = world.get("characters", {})
    for household in world.get("households", {}).values():
        for order in list(household.get("deliveries", [])):
            if tick < order["arrives_tick"]:
                continue
            household["deliveries"].remove(order)
            add(household, order["template_id"], tick, order["portions"], "warm")
            orderer = chars.get(order["orderer_id"])
            if orderer:
                here = orderer.get("building_id")
                for m in household.get("members", []):
                    who = chars.get(m)
                    if who and who.get("building_id") == here:
                        add_intention(who, {"type": "eat_food", "category": "survival", "priority": 55, "reason": "the takeout has arrived"})
