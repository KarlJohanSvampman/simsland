"""
systems/vehicles.py

Off-grid physical travel (see the "off-grid physical travel" plan): a
household's vehicles and the public bus stop. Spawned once at world
generation (generate_world.py::generate_initial_world()); no per-tick
logic lives here -- the car/bus movement state machines are in travel.py
and transit.py.

Vehicles are real, world-positioned props (like every other placed
object -- they need x/y/rendering/anchors the same as furniture), whose
static specs (top_speed/seats/gasoline cost/trunk capacity/base value)
come from a prop_template's "vehicle" sub-object (see car_sedan_a/
bike_a/motorcycle_a in definitions.json) and whose per-instance state
(owner, condition, insurance, value, legal status...) is stamped on the
instance at spawn_vehicle() time.

The garage is NOT a prop (it used to be -- "garage_a" -- removed this
round). It's now a room TYPE: a floorplan's "rooms" array may include an
entry with "type": "garage" (same convention bedroom_assignment.py
already uses for "type": "bedroom"), and household_garage() below
prefers that real room's center when the household's home building's
floorplan defines one. Most floorplans in this codebase have no real
room subdivision at all (confirmed elsewhere this session -- only
"starter_house" defines rooms), so this falls back to the exact fixed
offset the old garage_a prop always spawned at -- honest about today's
reality, forward-compatible the moment a floorplan actually draws a
garage room.
"""

import copy
import uuid

from systems.transforms import local_to_world

# Offset (in the building's local space) from a building's origin to
# where a vehicle waits absent a real garage room -- clear of the
# confirmed real footprint (rooms bounds x2=6,y2=6, door at (6,3)) and
# short of world["road_y"] (10) so there's room for the character/car to
# walk/drive the last stretch to the road.
GARAGE_LOCAL_OFFSET = (8, 2)

VEHICLE_CONDITIONS = ("new", "good", "ok", "bad", "broken")

# RepairCost = value / divisor, divisor keyed by condition, New..Broken
# left-to-right per the user's own spec (10, 8, 6, 4, 2).
CONDITION_REPAIR_DIVISOR = {
    "new": 10, "good": 8, "ok": 6, "bad": 4, "broken": 2,
}


# =========================================================
# GARAGE (room type, not a prop -- see module docstring)
# =========================================================

def household_garage(world, household_id):
    """{'x','y','building_id','zone_key'} -- the point a character walks
    to before driving off (travel.py reads garage['x']/['y']), and the
    zone_key systems/chores.py-style zone lookups can key off. None if
    the household has no home building at all."""
    household = world.get("households", {}).get(household_id)
    if not household:
        return None
    building_id = (household.get("building_ids") or [None])[0]
    buildings_by_id = {b["id"]: b for b in world.get("buildings", [])}
    building = buildings_by_id.get(building_id)
    if not building:
        return None

    defs = world.get("definitions", {})
    floorplan = defs.get("floorplan_templates", {}).get(building.get("template"), {})
    garage_room = next(
        (r for r in floorplan.get("rooms", []) if r.get("type") == "garage"),
        None,
    )

    if garage_room and garage_room.get("tiles"):
        xs, ys = [], []
        for tile in garage_room["tiles"]:
            wx, wy = local_to_world(building, tile["x"], tile["y"])
            xs.append(wx)
            ys.append(wy)
        return {
            "x": sum(xs) / len(xs),
            "y": sum(ys) / len(ys),
            "building_id": building_id,
            "zone_key": f"{building_id}:{garage_room['id']}",
        }

    x, y = local_to_world(building, *GARAGE_LOCAL_OFFSET)
    return {"x": x, "y": y, "building_id": building_id, "zone_key": building_id}


# =========================================================
# VEHICLES
# =========================================================

def compute_repair_cost(vehicle):
    value = vehicle.get("value", 0)
    divisor = CONDITION_REPAIR_DIVISOR.get(vehicle.get("condition", "good"), 8)
    return round(value / divisor, 2) if divisor else value


def can_drive(vehicle):
    """A vehicle in condition "broken" can't be used until repaired --
    per the user's own spec. is_legal/is_inspected are informational/
    consequence flags (a future round's problem -- getting pulled over,
    fines), not a hard block on driving, so they're deliberately not
    checked here."""
    return vehicle is not None and vehicle.get("condition") != "broken"


def spawn_vehicle(world, household, building, template_id="car_sedan_a", owner_id=None, **overrides):
    """Creates a real vehicle prop instance. Placed at the household's
    garage (see household_garage() above). If the template's "vehicle"
    sub-object says has_trunk_container, a companion "trunk" prop
    (systems/containers.py-compatible -- items/capacity pre-stamped,
    same instance-level-capacity-override pattern systems/plants.py's
    fruit container already uses) is spawned alongside it, tagged with
    the vehicle's id (parent_vehicle_id) so find_vehicle_trunk() can
    locate it later. overrides can set any of the per-instance fields
    below (name, condition, value, owner-facing identity, insurance,
    legal status...) -- anything not given gets a sensible default."""
    defs = world.get("definitions", {})
    template = defs.get("prop_templates", {}).get(template_id, {})
    stats = template.get("vehicle", {})

    garage = household_garage(world, household["id"])
    if garage:
        x, y = garage["x"], garage["y"]
    else:
        x, y = local_to_world(building, *GARAGE_LOCAL_OFFSET)

    vehicle = {
        "id":           f"vehicle_{uuid.uuid4().hex[:8]}",
        "template":     template_id,
        "x": x, "y": y,
        "rotation":     0,
        "household_id": household["id"],
        "hidden":       False,
        "state":        {"in_use": False},
        "anchors":      copy.deepcopy(template.get("anchors", [])),
        "footprint":    template.get("footprint"),
        "category":     template.get("category"),

        # ---- identity ----
        "name":                overrides.get("name") or template.get("name", "Vehicle"),
        "model_name":          overrides.get("model_name"),
        "manufacturer":        overrides.get("manufacturer"),
        "manufacturing_year":  overrides.get("manufacturing_year"),
        "owner_id":            owner_id,

        # ---- economy ----
        "value":                  overrides.get("value", stats.get("base_value", 0)),
        "insurance_pays":         overrides.get("insurance_pays", 0),
        "insurance_premium_cost": overrides.get("insurance_premium_cost", 0),
        "condition":              overrides.get("condition", "good"),
        "gasoline_cost_per_use":  stats.get("gasoline_cost_per_use", 0),

        # ---- legal ----
        "is_inspected": overrides.get("is_inspected", True),
        "is_legal":     overrides.get("is_legal", True),
        "next_mandatory_inspection_before": overrides.get("next_mandatory_inspection_before"),

        # ---- static specs (copied from the template for cheap per-instance access) ----
        "top_speed":           stats.get("top_speed", 0),
        "seats":               stats.get("seats", 1),
        "has_trunk_container": stats.get("has_trunk_container", False),
        "container_size":      stats.get("container_size", 0),
        "vehicle_class":       stats.get("vehicle_class", "car"),
    }
    world.setdefault("props", []).append(vehicle)

    if vehicle["has_trunk_container"]:
        trunk_template = defs.get("prop_templates", {}).get("trunk", {})
        trunk = {
            "id":                f"trunk_{vehicle['id'][9:]}",
            "template":          "trunk",
            "x": x, "y": y,
            "rotation":          0,
            "household_id":      household["id"],
            "hidden":            False,
            "parent_vehicle_id": vehicle["id"],
            "anchors":           copy.deepcopy(trunk_template.get("anchors", [])),
            "footprint":         trunk_template.get("footprint"),
            "category":          "storage",
            "items":             [],
            "capacity":          vehicle["container_size"],
        }
        world["props"].append(trunk)

    return vehicle


def find_vehicle_trunk(world, vehicle):
    if not vehicle:
        return None
    for p in world.get("props", []):
        if p.get("parent_vehicle_id") == vehicle.get("id"):
            return p
    return None


def attempt_repair_vehicle(world, vehicle):
    """Deducts compute_repair_cost() from the vehicle's owning
    household's wealth (if affordable) and resets condition to "good" --
    a repair shop restoring a car to factory-"new" isn't realistic
    either. Returns True on success, False if unaffordable or the
    vehicle has no owning household."""
    household = world.get("households", {}).get(vehicle.get("household_id"))
    if not household:
        return False
    cost = compute_repair_cost(vehicle)
    if household.get("wealth", 0) < cost:
        return False
    household["wealth"] = household.get("wealth", 0) - cost
    vehicle["condition"] = "good"
    return True


def household_vehicles(world, household_id):
    """Every vehicle prop (car/bike/motorcycle) owned by this household."""
    defs = world.get("definitions", {})
    prop_templates = defs.get("prop_templates", {})
    out = []
    for p in world.get("props", []):
        if p.get("household_id") != household_id:
            continue
        if prop_templates.get(p.get("template"), {}).get("vehicle"):
            out.append(p)
    return out


def household_car(world, household_id):
    """The household's first CAR-class vehicle, or None. travel.py's
    trip state machine only knows how to drive a car today -- bikes/
    motorcycles are real, ownable, drivable-in-principle vehicles (see
    can_drive() above) but aren't wired into off-grid trip mode
    selection this round."""
    defs = world.get("definitions", {})
    prop_templates = defs.get("prop_templates", {})
    for p in world.get("props", []):
        if p.get("household_id") != household_id:
            continue
        if prop_templates.get(p.get("template"), {}).get("vehicle", {}).get("vehicle_class") == "car":
            return p
    return None


def spawn_household_car(world, household, building, template_id="car_sedan_a"):
    """Convenience wrapper -- spawns a household's first car, matching
    generate_world.py's original one-call spawn shape (garage/car
    together), minus the garage prop (no longer a thing -- see module
    docstring)."""
    return spawn_vehicle(world, household, building, template_id=template_id)


def spawn_bus_stop(world, road_y):
    # Sidewalk row carved by world_tiles.py::generate_world_tiles()
    # immediately south of the through-road, at the same x as the garage
    # offset so the stop reads as "outside the house" -- see
    # GARAGE_LOCAL_OFFSET.
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


def bus_stop(world):
    """The one public bus stop. Multiple stops aren't modeled -- there's
    exactly one through-road, spawned once in generate_initial_world()."""
    for p in world.get("props", []):
        if p.get("template") == "bus_stop_a":
            return p
    return None


def ensure_vehicle_fields(world, defs):
    """Migration backfill, called from db.py on every load_world() (see
    systems/electrical.py's own ensure_power_outlets(), which taught the
    lesson this function follows: that means far more often than
    "once," under real concurrent access, so any add-if-missing logic
    has to be self-healing -- prune extras found, not just check-then-
    add). Two jobs: drop any leftover "garage_a" prop (dangling now that
    garage is a room type, not a prop template -- see module docstring),
    and backfill this round's new per-instance fields onto any vehicle
    prop that predates them (setdefault-only, safe to re-run), including
    a missing companion trunk prop for an old car that used to carry its
    own "storage" field directly."""
    props = world.setdefault("props", [])
    if any(p.get("template") == "garage_a" for p in props):
        world["props"] = [p for p in props if p.get("template") != "garage_a"]
        props = world["props"]

    prop_templates = defs.get("prop_templates", {})

    for p in props:
        stats = prop_templates.get(p.get("template"), {}).get("vehicle")
        if not stats:
            continue
        p.setdefault("name", prop_templates.get(p.get("template"), {}).get("name", "Vehicle"))
        p.setdefault("model_name", None)
        p.setdefault("manufacturer", None)
        p.setdefault("manufacturing_year", None)
        p.setdefault("owner_id", None)
        p.setdefault("value", stats.get("base_value", 0))
        p.setdefault("insurance_pays", 0)
        p.setdefault("insurance_premium_cost", 0)
        p.setdefault("condition", "good")
        p.setdefault("gasoline_cost_per_use", stats.get("gasoline_cost_per_use", 0))
        p.setdefault("is_inspected", True)
        p.setdefault("is_legal", True)
        p.setdefault("next_mandatory_inspection_before", None)
        p.setdefault("top_speed", stats.get("top_speed", 0))
        p.setdefault("seats", stats.get("seats", 1))
        p.setdefault("has_trunk_container", stats.get("has_trunk_container", False))
        p.setdefault("container_size", stats.get("container_size", 0))
        p.setdefault("vehicle_class", stats.get("vehicle_class", "car"))

    vehicle_ids_needing_trunk = {
        p["id"] for p in props
        if prop_templates.get(p.get("template"), {}).get("vehicle") and p.get("has_trunk_container")
    }
    trunks_by_vehicle = {}
    for p in props:
        pvid = p.get("parent_vehicle_id")
        if pvid:
            trunks_by_vehicle.setdefault(pvid, []).append(p)

    extra_ids = {t["id"] for trunks in trunks_by_vehicle.values() for t in trunks[1:]}
    if extra_ids:
        world["props"] = [p for p in props if p.get("id") not in extra_ids]
        props = world["props"]
        trunks_by_vehicle = {k: v[:1] for k, v in trunks_by_vehicle.items()}

    trunk_template = prop_templates.get("trunk", {})
    for vid in vehicle_ids_needing_trunk:
        if vid in trunks_by_vehicle:
            continue
        vehicle = next((p for p in props if p.get("id") == vid), None)
        if not vehicle:
            continue
        props.append({
            "id":                f"trunk_{vid[-8:]}_{uuid.uuid4().hex[:4]}",
            "template":          "trunk",
            "x": vehicle.get("x"), "y": vehicle.get("y"),
            "rotation":          0,
            "household_id":      vehicle.get("household_id"),
            "hidden":            False,
            "parent_vehicle_id": vid,
            "anchors":           copy.deepcopy(trunk_template.get("anchors", [])),
            "footprint":         trunk_template.get("footprint"),
            "category":          "storage",
            "items":             [],
            "capacity":          vehicle.get("container_size", 0),
        })


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
