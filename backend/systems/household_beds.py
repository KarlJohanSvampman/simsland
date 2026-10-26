"""
systems/household_beds.py -- a bed for everyone who lives in the house.

The starter house comes with two single beds. A family of three or four then had adults and children lying down on the
dining-room or kitchen floor (a "sleep" activity with no free bed anchor falls back to wherever the character stands).
ensure_household_beds() adds single beds until the building has a sleeping place per member of the household that owns it.

It runs whenever someone joins a household (systems/household_manager.py::add_member_to_household, so also births, moves and
editor spawns) and from the settle step (systems/spawn_setup.py). It is idempotent: with enough beds it does nothing.

Where: the first free 2x2 block (a bed's footprint) inside, in order, a bedroom, the living room, the dining room, the laundry
and the corridor of the floorplan, that keeps the usual clearance from the other furniture (systems/prop_placement.py). If no
block keeps the clearance, a free block is still used (a bed in a cramped room beats a person on the floor). If there is no free
block at all the household is left one short and that is reported.
"""

import copy
import uuid

BED_TEMPLATE = "bed_single"
ROOM_PREFERENCE = ("bedroom", "living_room", "dining_room", "laundry", "corridor")


def _templates(world):
    return (world.get("definitions") or {}).get("prop_templates", {})


def _building(world, household):
    ids = household.get("building_ids") or ([household["home_id"]] if household.get("home_id") else [])
    by_id = {b.get("id"): b for b in world.get("buildings", [])}
    return next((by_id[i] for i in ids if i in by_id), None)


def sleeper_count(world, household):
    chars = world.get("characters", {})
    return sum(1 for mid in household.get("members", []) if mid in chars and chars[mid].get("alive") is not False)


def bed_capacity(world, building_id):
    """Sleeping places in the building: one per 'sleep' anchor on a bed-tagged prop."""
    templates = _templates(world)
    count = 0
    for prop in world.get("props", []):
        if prop.get("building_id") != building_id:
            continue
        tags = set((templates.get(prop.get("template")) or {}).get("tags") or []) | set(prop.get("extra_tags") or [])
        if "bed" not in tags and "bed" not in str(prop.get("template", "")):
            continue
        count += sum(1 for a in (prop.get("anchors") or []) if a.get("interaction") == "sleep")
    return count


def _occupied_tiles(world, building_id):
    from systems.prop_placement import _prop_tiles
    templates = _templates(world)
    taken = set()
    for prop in world.get("props", []):
        if prop.get("building_id") != building_id:
            continue
        taken.update(_prop_tiles(prop, templates.get(prop.get("template")) or {}))
    return taken


def _free_blocks(world, building, floorplan):
    """[(room_type, (world_x, world_y))] of free 2x2 blocks, in room preference order."""
    from systems.transforms import local_to_world
    taken = _occupied_tiles(world, building["id"])
    out = []
    rooms = sorted(floorplan.get("rooms", []),
                   key=lambda r: ROOM_PREFERENCE.index(r.get("type")) if r.get("type") in ROOM_PREFERENCE else 99)
    for room in rooms:
        if room.get("type") not in ROOM_PREFERENCE:
            continue
        tiles = {(t["x"], t["y"]) for t in room.get("tiles", [])}
        for lx, ly in sorted(tiles, key=lambda t: (t[1], t[0])):
            block = [(lx, ly), (lx + 1, ly), (lx, ly + 1), (lx + 1, ly + 1)]
            if not all(t in tiles for t in block):
                continue
            world_tiles = [tuple(local_to_world(building, x, y)) for x, y in block]
            if any(t in taken for t in world_tiles):
                continue
            # the prop's anchor tile is its (dx=0, dy=0) corner: the smallest world x and y of the block
            out.append((room["type"], (min(t[0] for t in world_tiles), min(t[1] for t in world_tiles))))
    return out


def _new_bed(world, building, household, x, y):
    template = _templates(world).get(BED_TEMPLATE) or {}
    prop = {
        "id": f"{BED_TEMPLATE}_{uuid.uuid4().hex[:6]}", "template": BED_TEMPLATE, "x": x, "y": y, "rotation": 0,
        "carryable": False, "building_id": building["id"], "household_id": household["id"],
        "anchors": copy.deepcopy(template.get("anchors", [])), "footprint": template.get("footprint"),
        "category": template.get("category"), "storage": copy.deepcopy(template.get("storage")),
        "catalog": template.get("catalog"), "extra_tags": [],
    }
    from systems.room_assignment import assign_prop_room
    assign_prop_room(building, prop)
    return prop


def ensure_household_beds(world, household):
    """Add beds until there is a sleeping place per member. Returns the number added (and sets household["beds_short"] when it
    could not add enough)."""
    building = _building(world, household)
    templates = _templates(world)
    if not building or BED_TEMPLATE not in templates:
        return 0
    from systems.templates import get_floorplan_template
    floorplan = get_floorplan_template(world, building)
    if not floorplan:
        return 0
    missing = sleeper_count(world, household) - bed_capacity(world, building["id"])
    added = 0
    while missing > 0:
        blocks = _free_blocks(world, building, floorplan)
        if not blocks:
            break
        from systems.prop_placement import check_placement
        defs = world.get("definitions") or {}
        spot = next((xy for _, xy in blocks if check_placement(world, defs, building["id"], BED_TEMPLATE, *xy)[0]), None)
        if spot is None:
            spot = blocks[0][1]                       # cramped, but not the floor
        world.setdefault("props", []).append(_new_bed(world, building, household, *spot))
        added += 1
        missing -= 1
    household["beds_short"] = max(0, missing)
    return added
