"""
systems/household_generation.py -- move whole families into the neighbourhood: a house, a household and its members.

generate_households(world, sim_id, count=3, members=3) does, for each new household:

  1. a house: a building of a floorplan template (starter_house by default) on the first free lot -- inside the world,
     clear of the through-road and its sidewalk, and a few tiles away from every other building -- built straight away
     (walls, rooms, furniture: systems/building_manager.py::build_world_geometry)
  2. a household that owns it (systems/household_manager.py: home, mortgage, insurance, keys, beds, a stocked fridge)
  3. its members, related to each other: a family record (systems/family.py) with the kinship and relationship labels
     stamped on, a shared surname, children's traits and hobbies derived from a parent (systems/relative_gen.py)
  4. each member standing on free floor in their living room, settled (systems/spawn_setup.py: schedule, body clock)
     and knowing the people next door (systems/neighbours.py)
  5. the household's car, when the house has room for one

The shapes of the households rotate through COMPOSITIONS, so three households are three different kinds of family.
Returns a summary of what was made.
"""

import random

DEFAULT_TEMPLATE = "starter_house"
LOT_MARGIN = 2                      # free tiles kept between a new house and any other building

# role, age range, relation to the head ("self" for the head), sex rule ("any", "opposite" of the head)
COMPOSITIONS = [
    {"kind": "couple with a child", "members": [
        ("head",   (28, 45), "self",   "any"),
        ("spouse", (26, 47), "spouse", "opposite"),
        ("child",  (5, 15),  "child",  "any"),
    ]},
    {"kind": "single parent with two children", "members": [
        ("head",   (32, 50), "self",  "any"),
        ("child",  (9, 17),  "child", "any"),
        ("child",  (4, 12),  "child", "any"),
    ]},
    {"kind": "three generations", "members": [
        ("head",   (34, 48), "self",   "any"),
        ("parent", (60, 80), "parent", "any"),
        ("child",  (6, 16),  "child",  "any"),
    ]},
    {"kind": "young couple with a toddler", "members": [
        ("head",   (24, 34), "self",   "any"),
        ("spouse", (23, 35), "spouse", "opposite"),
        ("child",  (2, 6),   "child",  "any"),
    ]},
    {"kind": "adult siblings", "members": [
        ("head",    (22, 40), "self",    "any"),
        ("sibling", (20, 42), "sibling", "any"),
        ("sibling", (20, 42), "sibling", "any"),
    ]},
]


# =========================================================
# LOTS
# =========================================================

def _size(world, template_id):
    fp = (world.get("definitions", {}).get("floorplan_templates") or {}).get(template_id) or {}
    return fp.get("width", 20), fp.get("height", 20)


def _rects(world):
    for b in world.get("buildings", []):
        w, h = _size(world, b.get("template"))
        yield b.get("x", 0), b.get("y", 0), w, h


def find_free_lot(world, width, height, margin=LOT_MARGIN):
    """The first (x, y), scanning row by row from the top-left, where a width x height building fits inside the world,
    off the through-road and its sidewalk, with `margin` free tiles to every other building. None when the map is full."""
    world_w, world_h = world.get("world_width", 100), world.get("world_height", 100)
    taken = list(_rects(world))
    for y in range(0, world_h - height + 1):
        if _crosses_road(world, y, height):
            continue                                     # would sit on the road or its sidewalk
        for x in range(0, world_w - width + 1):
            if all(x + width + margin <= ox or ox + ow + margin <= x or
                   y + height + margin <= oy or oy + oh + margin <= y for ox, oy, ow, oh in taken):
                return x, y
    return None


def _crosses_road(world, y, height):
    """Rows road_y (the road) and road_y + 1 (its sidewalk) are not building land."""
    road_y = world.get("road_y", 10)
    return y <= road_y + 1 and road_y < y + height


STREETS = ["Maple Street", "Birch Lane", "Elm Avenue", "Willow Road", "Cedar Court", "Juniper Way"]


def _address(world, building):
    """A house number from the lot's position along its row, on a street named after its row of the map."""
    row = building["y"] // 20
    return f"{building['x'] // 2 * 2 + 1 + row % 2} {STREETS[row % len(STREETS)]}"


# =========================================================
# PEOPLE
# =========================================================

def _member_overrides(defs, head, relation, ages, sex_rule, surname, household_id, taken_names=()):
    lo, hi = ages
    if head is not None:
        if relation == "child":                         # born when the head was 18-45
            hi = min(hi, head["age"] - 18)
            lo = min(lo, hi)
        elif relation == "parent":
            lo = max(lo, head["age"] + 18)
            hi = max(hi, lo)
    sex = random.choice(["male", "female"])
    if head is not None and sex_rule == "opposite":
        sex = "female" if head.get("sex") == "male" else "male"
    overrides = {"age": random.randint(max(1, lo), max(1, lo, hi)), "sex": sex, "household_id": household_id}
    from systems.character_gen import _random_name
    for _ in range(20):                                  # nobody shares a first name with someone they live with
        first, _ = _random_name(defs, sex)
        if first not in taken_names:
            break
    overrides["first_name"] = first
    overrides["family_name"] = surname
    overrides["name"] = f"{first} {surname}"
    if head is not None and relation in ("child", "parent", "sibling", "spouse"):
        try:
            from systems.relative_gen import derive_relative, _fallback_bio
            derived = derive_relative(head, relation, defs, sex=sex)
            overrides["traits"] = derived["traits"]
            overrides["hobbies"] = derived["hobbies"]
            overrides["physical_traits"] = derived["physical_traits"]
            overrides["bio"] = _fallback_bio(head, relation, derived["traits"])
        except Exception as exc:                         # a fully random person is still a person
            print(f"[household_generation] derive_relative({relation}) failed: {exc!r}")
        if relation == "child" and head.get("values"):
            overrides["parent_values"] = [head["values"]]
    return overrides


def _link_family(world, family, head, people):
    """people: [(character, role, relation-to-head)]. Kinship between every pair of them, not only to the head."""
    from systems.family import _add_member, _set_relation
    for c, role, relation in people:
        _add_member(family, c["id"])
        c["family_id"] = family["id"]
        c["family_role"] = role
    children = [c for c, _, rel in people if rel == "child"]
    spouses = [c for c, _, rel in people if rel == "spouse"]
    parents = [c for c, _, rel in people if rel == "parent"]
    siblings = [c for c, _, rel in people if rel == "sibling"]
    for s in spouses:
        _set_relation(family, head["id"], s["id"], "spouse")
    for kid in children:
        for p in [head] + spouses:
            _set_relation(family, p["id"], kid["id"], "parent")
        for gp in parents:
            _set_relation(family, gp["id"], kid["id"], "grandparent")
    for i, a in enumerate(children):
        for b in children[i + 1:]:
            _set_relation(family, a["id"], b["id"], "sibling")
    for gp in parents:
        _set_relation(family, gp["id"], head["id"], "parent")
    sibs = [head] + siblings
    for i, a in enumerate(sibs):
        for b in sibs[i + 1:]:
            _set_relation(family, a["id"], b["id"], "sibling")


def _free_floor(world, building, room_type="living_room"):
    """Absolute floor tiles of the building's room of that type (any room when it has none) that no furniture stands on."""
    from systems.prop_placement import _prop_tiles
    fp = (world["definitions"].get("floorplan_templates") or {}).get(building["template"]) or {}
    rooms = fp.get("rooms") or []
    room = next((r for r in rooms if r.get("type") == room_type), None) or (rooms[0] if rooms else None)
    templates = world["definitions"].get("prop_templates") or {}
    blocked = set()
    for p in world.get("props", []):
        if p.get("building_id") == building["id"]:
            for t in _prop_tiles(p, templates.get(p.get("template")) or {}):
                blocked.add(tuple(t) if not isinstance(t, tuple) else t)
    bx, by = building["x"], building["y"]
    tiles = [(bx + t["x"], by + t["y"]) for t in (room or {}).get("tiles", [])]
    free = [t for t in tiles if t not in blocked]
    return free or tiles or [(bx + 1, by + 1)]


# =========================================================
# MAIN
# =========================================================

def generate_households(world, sim_id="default", count=3, members=3, template=DEFAULT_TEMPLATE):
    from systems.building_manager import build_world_geometry
    from systems.character_gen import generate_character, _random_name
    from systems.household_manager import create_household, assign_building_to_household, add_member_to_household
    from systems.family import _new_family, sync_kinship_to_relationships

    defs = world.get("definitions") or {}
    if not (defs.get("floorplan_templates") or {}).get(template):
        from core.definitions import load_definitions
        defs = load_definitions(sim_id)
        world["definitions"] = defs
    if not (defs.get("floorplan_templates") or {}).get(template):
        raise ValueError(f"no floorplan template '{template}'")
    width, height = _size(world, template)
    world.setdefault("households", {})
    world.setdefault("families", {})
    world.setdefault("characters", {})

    # 1. the houses, all built in one geometry pass
    existing = {b["id"] for b in world.get("buildings", [])}
    new_buildings = []
    for _ in range(count):
        lot = find_free_lot(world, width, height)
        if lot is None:
            break
        n = 1
        while f"{template}_{n}" in existing:
            n += 1
        b = {"id": f"{template}_{n}", "template": template, "x": lot[0], "y": lot[1], "rotation": 0,
             "address": None, "owner_household_id": None}
        existing.add(b["id"])
        world.setdefault("buildings", []).append(b)
        new_buildings.append(b)
    if new_buildings:
        build_world_geometry(sim_id, world)
        defs = world["definitions"]

    made = []
    used_surnames = {h.get("name") for h in world["households"].values()}
    offset = random.randrange(len(COMPOSITIONS))
    for i, building in enumerate(new_buildings):
        comp = COMPOSITIONS[(offset + i) % len(COMPOSITIONS)]
        roles = list(comp["members"])[:max(1, members)]
        while len(roles) < members:                     # more members than the shape has: more children
            roles.append(("child", (3, 17), "child", "any"))

        surname = None
        for _ in range(10):
            _, surname = _random_name(defs, random.choice(["male", "female"]))
            if f"The {surname} Household" not in used_surnames:
                break
        used_surnames.add(f"The {surname} Household")

        household = create_household(world, f"The {surname} Household")
        assign_building_to_household(world, building, household)
        building["address"] = building.get("address") or _address(world, building)

        spots = _free_floor(world, building)
        random.shuffle(spots)
        head, people = None, []
        for j, (role, ages, relation, sex_rule) in enumerate(roles):
            ov = _member_overrides(defs, head, relation, ages, sex_rule, surname, household["id"],
                                    taken_names={c["first_name"] for c, _, _ in people})
            ov["x"], ov["y"] = spots[j % len(spots)]
            c = generate_character(defs, ov, world=world)
            c["family_name"], c["name"] = surname, f"{c['first_name']} {surname}"
            world["characters"][c["id"]] = c
            add_member_to_household(world, c, household)
            if head is None:
                head = c
            people.append((c, role, relation))

        family = _new_family(surname)
        _link_family(world, family, head, people)
        world["families"][family["id"]] = family
        sync_kinship_to_relationships(family, world)

        from systems.spawn_setup import settle_new_character
        from systems.neighbours import seed_neighbour_ties
        for c, _, _ in people:
            try:
                settle_new_character(world, c)
            except Exception as exc:
                print(f"[household_generation] settling {c['name']} failed: {exc!r}")
            try:
                seed_neighbour_ties(world, c)
            except Exception as exc:
                print(f"[household_generation] neighbour ties for {c['name']} failed: {exc!r}")

        car = None
        try:
            from systems.vehicles import spawn_household_car
            car = spawn_household_car(world, household, building)
        except Exception as exc:
            print(f"[household_generation] no car for {household['name']}: {exc!r}")

        made.append({
            "household_id": household["id"],
            "name": household["name"],
            "kind": comp["kind"],
            "building_id": building["id"],
            "address": building["address"],
            "x": building["x"], "y": building["y"],
            "car": (car or {}).get("id") if isinstance(car, dict) else None,
            "members": [{"id": c["id"], "name": c["name"], "age": c["age"], "sex": c["sex"], "role": role}
                        for c, role, _ in people],
        })
    return {"households": made, "requested": count, "made": len(made),
            "out_of_room": len(made) < count}
