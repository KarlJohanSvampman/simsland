"""
systems/vehicles.py

Off-grid physical travel (see the "off-grid physical travel" plan): a
household's garage + car, and the public bus stop. Spawned once at world
generation (generate_world.py::generate_initial_world()); no per-tick logic
lives here -- the car/bus movement state machines are in travel.py and
transit.py.
"""

from systems.transforms import local_to_world

# Offset (in the building's local space) from house_1's origin to the
# garage -- clear of the confirmed real footprint (rooms bounds x2=6,y2=6,
# door at (6,3)), and short of world["road_y"] (10) so there's room for the
# character/car to walk/drive the last stretch to the road.
GARAGE_LOCAL_OFFSET = (8, 2)


def spawn_household_garage_and_car(world, household, building):
    garage_x, garage_y = local_to_world(building, *GARAGE_LOCAL_OFFSET)

    garage = {
        "id": f"garage_{household['id'][:8]}",
        "template": "garage_a",
        "x": garage_x,
        "y": garage_y,
        "rotation": 0,
        "household_id": household["id"],
        "hidden": False,
        "state": {},
    }

    car = {
        "id": f"car_{household['id'][:8]}",
        "template": "car_sedan_a",
        "x": garage_x,
        "y": garage_y,
        "rotation": 0,
        "household_id": household["id"],
        "hidden": False,
        "state": {"in_use": False},
    }

    world["props"].append(garage)
    world["props"].append(car)
    return garage, car


def spawn_bus_stop(world, road_y):
    # Sidewalk row carved by world_tiles.py::generate_world_tiles()
    # immediately south of the through-road, at the same x as the garage
    # so the stop reads as "outside the house" -- see GARAGE_LOCAL_OFFSET.
    stop = {
        "id": "bus_stop_1",
        "template": "bus_stop_a",
        "x": GARAGE_LOCAL_OFFSET[0],
        "y": road_y + 1,
        "rotation": 0,
        "household_id": None,
        "hidden": False,
        "state": {},
    }
    world["props"].append(stop)
    return stop


def household_car(world, household_id):
    """The household's car prop, or None if it doesn't have one (any
    household other than the one seeded in generate_initial_world() today).
    """
    for p in world.get("props", []):
        if p.get("template") == "car_sedan_a" and p.get("household_id") == household_id:
            return p
    return None


def household_garage(world, household_id):
    for p in world.get("props", []):
        if p.get("template") == "garage_a" and p.get("household_id") == household_id:
            return p
    return None


def bus_stop(world):
    """The one public bus stop. Multiple stops aren't modeled -- there's
    exactly one through-road, spawned once in generate_initial_world()."""
    for p in world.get("props", []):
        if p.get("template") == "bus_stop_a":
            return p
    return None


def household_home_entrance(world, household_id):
    """(x, y) of the household's home building's first door, for routing a
    character back inside after a car/bus trip -- or None if the household
    owns no building with a door (e.g. no garage/no home at all, see Round 5's
    no-garage-household fallback)."""
    household = world.get("households", {}).get(household_id)
    if not household:
        return None
    buildings_by_id = {b["id"]: b for b in world.get("buildings", [])}
    for bid in household.get("building_ids", []):
        building = buildings_by_id.get(bid)
        doors = building.get("doors") if building else None
        if doors:
            d = doors[0]
            return (d["x"], d["y"])
    return None
