"""
systems/refurnishing.py

Tracks how long it's been, and how many times today, a zone's furniture
has actually changed (a prop created/moved -- see prop_events.py's
on_prop_created/on_prop_moved for World-Editor-driven changes, and this
module's own in-sim redecorate_room chore below for sim-driven ones),
and drives a character's want to refurnish once their own randomized
day-threshold (c["redecorate_threshold_days"]) is crossed. "Refurnish"
can mean relocating an existing prop OR just swapping in a new
decorative item (a poster/painting) -- the user's own explicit
"something to that effect" framing, kept as a cheap, always-available
alternative to a full furniture move.
"""

import copy
import random
import uuid

TICKS_PER_DAY = 24  # matches health.py/plants.py's TICKS_PER_DAY convention
REDECORATE_NUDGE_PRIORITY = 30
DEFAULT_REDECORATE_THRESHOLD_RANGE = (20, 60)  # days -- an arbitrary per-sim number, per the user's own framing


def random_redecorate_threshold_days():
    return random.randint(*DEFAULT_REDECORATE_THRESHOLD_RANGE)


# =========================================================
# CHANGE TRACKING
# =========================================================

def record_furniture_change(world, zone_key):
    """Called from prop_events.py (editor-driven) and this module's own
    _perform_redecoration (in-sim). Bumps changes_today (day-key gated,
    same convention libido.py/expectations.py already use) and stamps
    last_changed_tick."""
    if not zone_key:
        return
    store = world.setdefault("zone_furniture_changes", {})
    entry = store.setdefault(zone_key, {
        "last_changed_tick": world.get("tick", 0),
        "changes_today": 0,
        "day_stamp": None,
    })
    cal = world.get("calendar", {})
    today = (cal.get("year"), cal.get("month"), cal.get("day"))
    if entry["day_stamp"] != today:
        entry["changes_today"] = 0
        entry["day_stamp"] = today
    entry["changes_today"] += 1
    entry["last_changed_tick"] = world.get("tick", 0)


def days_since_last_change(world, zone_key):
    """None means "never tracked" (no data) -- distinct from 0, and
    deliberately NOT treated as "overdue" by the caller below (a zone
    with no history shouldn't immediately nag every occupant the moment
    tracking starts)."""
    entry = world.get("zone_furniture_changes", {}).get(zone_key)
    if not entry:
        return None
    return (world.get("tick", 0) - entry["last_changed_tick"]) / TICKS_PER_DAY


# =========================================================
# THE DRIVING MECHANISM -- called on a slow cadence (see sim_loop.py)
# =========================================================

def maybe_want_to_redecorate(c, world):
    """Self-directed only -- nobody else is "to blame" for stale decor,
    so this never nags/feeds a grievance the way chores.py's mess/plant-
    neglect reactions do."""
    household_id = c.get("household_id")
    if not household_id:
        return
    household = world.get("households", {}).get(household_id)
    building_id = household.get("home_id") if household else None
    if not building_id:
        return

    from systems.chores import zone_key_for_character
    zone_key = zone_key_for_character(c) or building_id
    days = days_since_last_change(world, zone_key)
    threshold = c.get("redecorate_threshold_days") or random_redecorate_threshold_days()
    if days is None or days < threshold:
        return

    from brain.intentions import add_intention
    add_intention(c, {
        "type":     "redecorate_room",
        "category": "chores",
        "priority": REDECORATE_NUDGE_PRIORITY,
        "reason":   "the place could use a change -- it's been a while",
    })


# =========================================================
# THE ACTUAL CHORE -- called from activities.py's complete_activity()
# =========================================================

def _new_prop_from_template(defs, template_id, building_id, household_id, x, y):
    template = defs.get("prop_templates", {}).get(template_id, {})
    return {
        "id":           f"{template_id}_{uuid.uuid4().hex[:6]}",
        "template":     template_id,
        "x": x, "y": y,
        "rotation":     0,
        "carryable":    False,
        "building_id":  building_id,
        "household_id": household_id,
        "anchors":      copy.deepcopy(template.get("anchors", [])),
        "footprint":    template.get("footprint"),
        "category":     template.get("category"),
    }


def perform_redecoration(c, world):
    """Either relocates one existing movable piece of furniture to a new
    valid nearby spot (systems/prop_placement.py's margin rules apply --
    a redecorate can't just shove something into another prop) or, when
    that's not possible/half the time anyway, adds a new painting to the
    wall -- always available, no existing prop required. Either way
    counts as a real furniture change (record_furniture_change)."""
    household = world.get("households", {}).get(c.get("household_id"))
    if not household:
        return
    building_id = household.get("home_id")
    if not building_id:
        return

    from systems.chores import zone_key_for_character
    from systems.prop_placement import find_clear_tile_near

    zone_key = zone_key_for_character(c) or building_id
    defs = world.get("definitions") or {}
    prop_templates = defs.get("prop_templates", {})
    props = world.setdefault("props", [])

    candidates = [
        p for p in props
        if p.get("building_id") == building_id
        and prop_templates.get(p.get("template"), {}).get("category") == "furniture"
        and not prop_templates.get(p.get("template"), {}).get("wall_mounted")
    ]

    if candidates and random.random() < 0.5:
        prop = random.choice(candidates)
        spot = find_clear_tile_near(world, defs, building_id, prop["template"], prop["x"], prop["y"])
        if spot:
            prop["x"], prop["y"] = spot
            record_furniture_change(world, zone_key)
            return

    anchor_prop = next((p for p in props if p.get("building_id") == building_id), None)
    ax, ay = (anchor_prop["x"], anchor_prop["y"]) if anchor_prop else (c["x"], c["y"])
    spot = find_clear_tile_near(world, defs, building_id, "wall_painting", ax, ay)
    if not spot:
        return

    from systems.room_assignment import assign_prop_room
    buildings = {b["id"]: b for b in world.get("buildings", []) if b.get("id")}
    building = buildings.get(building_id)

    painting = _new_prop_from_template(defs, "wall_painting", building_id, household["id"], spot[0], spot[1])
    if building:
        assign_prop_room(building, painting)
    props.append(painting)
    record_furniture_change(world, zone_key)
