"""
systems/electrical.py

Guarantees every zone (systems/chores.py's room_id-or-building_id
convention -- no real per-building room subdivision exists for most
floorplans, see chores.py's own module docstring) has at least one
power_outlet prop, and exposes the "is there one nearby" check the
vacuum-cleaning chore gates on (systems/chores.py::clean_floors_ready).
"""

import copy
import uuid

POWER_OUTLET_TEMPLATE_ID = "power_outlet"


def zone_has_power_outlet(world, zone_key):
    if not zone_key:
        return False
    from systems.chores import zone_key_for_prop
    for prop in world.get("props", []):
        if prop.get("template") == POWER_OUTLET_TEMPLATE_ID and zone_key_for_prop(prop) == zone_key:
            return True
    return False


def ensure_power_outlets(world, defs):
    """Backfill pass (mirrors schema_defaults.py's per-building loops),
    called from db.py on every load_world() -- both the cache-hit AND
    cold-load paths, which turns out to mean far more often than "once"
    (every tick, every API request that touches world state). Under
    concurrent access (the live tick loop plus ordinary request traffic,
    both calling load_world()/save_world() independently) a plain
    check-before-add was NOT actually safe -- confirmed live: a single
    2-building world accumulated 140 power_outlet props in one building
    over a session's worth of restarts and requests, all in "house_1"'s
    one zone. Fixed by making this pass self-healing -- it prunes any
    EXTRA outlets found beyond the first in an already-covered zone on
    every call, so duplicates introduced by a future race collapse back
    to one on the very next load rather than accumulating forever."""
    from systems.prop_placement import find_clear_tile_near
    from systems.chores import zone_key_for_prop
    from systems.room_assignment import assign_prop_room

    props = world.setdefault("props", [])
    buildings = {b["id"]: b for b in world.get("buildings", []) if b.get("id")}

    zone_anchor = {}
    zone_outlets = {}
    for prop in props:
        bid = prop.get("building_id")
        if not bid or bid not in buildings:
            continue
        zk = zone_key_for_prop(prop)
        if not zk:
            continue
        zone_anchor.setdefault(zk, (bid, prop["x"], prop["y"]))
        if prop.get("template") == POWER_OUTLET_TEMPLATE_ID:
            zone_outlets.setdefault(zk, []).append(prop)

    # Prune duplicates -- keep the first found per zone, drop the rest.
    extra_ids = {p["id"] for outlets in zone_outlets.values() for p in outlets[1:]}
    if extra_ids:
        world["props"] = [p for p in props if p.get("id") not in extra_ids]
        props = world["props"]

    template = defs.get("prop_templates", {}).get(POWER_OUTLET_TEMPLATE_ID, {})
    if not template:
        return

    for zone_key, (bid, ax, ay) in zone_anchor.items():
        if zone_key in zone_outlets:
            continue
        spot = find_clear_tile_near(world, defs, bid, POWER_OUTLET_TEMPLATE_ID, ax, ay)
        if not spot:
            continue
        x, y = spot
        outlet = {
            "id":            f"power_outlet_{uuid.uuid4().hex[:6]}",
            "template":      POWER_OUTLET_TEMPLATE_ID,
            "x": x, "y": y,
            "rotation":      0,
            "carryable":     False,
            "building_id":   bid,
            "household_id":  buildings[bid].get("owner_household_id"),
            "anchors":       copy.deepcopy(template.get("anchors", [])),
            "footprint":     template.get("footprint"),
            "category":      template.get("category"),
        }
        assign_prop_room(buildings[bid], outlet)
        props.append(outlet)
        zone_outlets[zone_key] = [outlet]
