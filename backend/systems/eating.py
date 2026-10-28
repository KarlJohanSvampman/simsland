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


def resolve_meal(c, world, target_id):
    item = find_item(c, world, target_id)
    if not is_food(item):
        item = pick_food(c, world)
    if not item:
        return None
    return {"item": item, "place": eating_place(c, world)}
