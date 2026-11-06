"""What each requirement asks of the world. Every resolver: fn(c, world) -> bool. A requirement in behaviour.json names
its resolver here; the checker refuses one that names nothing."""

RESOLVERS = {}


def resolver(name):
    def deco(fn):
        RESOLVERS[name] = fn
        return fn
    return deco


def _household(c, world):
    return (world.get("households") or {}).get(c.get("household_id"))


@resolver("food_served")
def food_served(c, world):
    """Someone has cooked and it is still being served, or there are leftover portions."""
    hh = _household(c, world)
    if not hh:
        return False
    from systems import cookware
    return bool(cookware.ready_vessel(hh, world.get("tick", 0)) or any(l.get("portions", 0) > 0 for l in hh.get("leftovers", [])))


@resolver("has_warm_ready_meal")
def has_warm_ready_meal(c, world):
    hh = _household(c, world)
    from systems import ready_meals
    return bool(hh and ready_meals.count(hh, "warm"))


@resolver("has_ready_meal")
def has_ready_meal(c, world):
    hh = _household(c, world)
    from systems import ready_meals
    return bool(hh and ready_meals.count(hh, "cold"))


@resolver("has_stored_meal")
def has_stored_meal(c, world):
    hh = _household(c, world)
    from systems.household_storage import find_household_resource
    return bool(hh and (find_household_resource(hh, resource_type="MEAL") or find_household_resource(hh, resource_type="STORED_MEAL")))


@resolver("has_snack")
def has_snack(c, world):
    hh = _household(c, world)
    if not hh:
        return False
    from systems.household_storage import find_household_resource
    return any(find_household_resource(hh, resource_type=t) for t in ("FOOD_FRUIT", "FOOD_BREAD", "FOOD_SNACK", "PROCESSED_MEAL"))


@resolver("has_ingredients")
def has_ingredients(c, world):
    hh = _household(c, world)
    from systems import cookware
    return bool(hh and cookware.feasible_recipes(hh, 1))


@resolver("can_cook")
def can_cook(c, world):
    from systems.food_habits import can_cook as _can
    return bool(_can(c))


@resolver("cookware_free")
def cookware_free(c, world):
    hh = _household(c, world)
    from systems import cookware
    return bool(hh and any(cookware.vessel_for(hh, k) for k in ("pot", "pan", "oven")))


@resolver("phone_usable")
def phone_usable(c, world):
    from systems.personal_items import phone_is_usable
    return bool(phone_is_usable(c))


@resolver("money_for_takeout")
def money_for_takeout(c, world):
    return (c.get("money") or 0) >= 25


@resolver("money_for_groceries")
def money_for_groceries(c, world):
    return (c.get("money") or 0) >= 20


@resolver("takeout_on_its_way")
def takeout_on_its_way(c, world):
    hh = _household(c, world)
    return bool(hh and hh.get("deliveries"))


def _anchor_offered(world, interaction):
    for p in world.get("props") or []:
        for a in p.get("anchors") or []:
            if a.get("interaction") == interaction:
                return True
    return False


@resolver("store_reachable")
def store_reachable(c, world):
    """Somewhere on the map offers food shopping (an anchor with the shop_food interaction)."""
    return _anchor_offered(world, "shop_food")


@resolver("restaurant_reachable")
def restaurant_reachable(c, world):
    return _anchor_offered(world, "eat_out")


@resolver("caretaker_home")
def caretaker_home(c, world):
    """An adult of the household is in the same building."""
    hh = _household(c, world)
    chars = world.get("characters") or {}
    return bool(hh and any(m != c.get("id") and m in chars and (chars[m].get("age") or 0) >= 18
                           and chars[m].get("building_id") == c.get("building_id") and not chars[m].get("off_grid")
                           for m in hh.get("members") or []))
