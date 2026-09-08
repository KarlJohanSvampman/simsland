"""
phone.py — smartphone battery management

Battery lives in item["states"]["battery"] (0–100).
Drains every tick at idle rate; faster while actively using phone interactions.
Charging restores it via the charge_device handler in action_router.

Called from sim_loop every tick for each character that carries a phone.
"""

import random

from systems.personal_items import get_phone
from systems.props import prop_distance


# ── Carry/drop/forget ────────────────────────────────────────────────────────
# The phone isn't meant to sit invisibly in inventory forever -- characters
# set it down once their hands are actually occupied (maybe_set_phone_down),
# tracked via phone_state["last_known_location"] so it can be walked back to
# (action_router.py's retrieve_phone). Leaving the building it was left in
# without it (maybe_forget_phone) is the "genuinely forgot it" case the
# location memory alone doesn't capture -- distance, not time, is what
# turns "set down" into "forgotten", matching "normally won't go too far
# from it."
#
# Live bug report: this used to place the phone at the character's own
# tile via drop_item() no matter where that was -- literally the bare
# ground, in the middle of a yard, a road, anywhere -- which is not where
# a real person sets a phone down. People use a nearby flat surface (a
# table, desk, counter, nightstand) if one's in reach; if there genuinely
# isn't one, the phone stays on them (a pocket), not on the floor.

# Prop templates that read as "a flat surface you'd set something on" --
# no prop_templates entry carries an explicit is_surface/surface tag to
# query generically, so this is a curated content list, same approach
# this session already took for other registry gaps with no clean flag.
_SURFACE_TEMPLATES = {
    "dining_table_a", "dining_table", "desk", "kids_desk", "nightstand",
    "coffee_table", "side_table", "kitchen_counter", "kitchen_island",
    "console_table", "outdoor_table", "art_station",
}
_SURFACE_SEARCH_RADIUS = 8    # tiles -- sitting down, casual, not in a rush
_BUSY_SEARCH_RADIUS = 16      # tiles -- hands genuinely needed right now, search harder

SIT_DROP_CHANCE  = 0.4   # per check, once sitting
BUSY_DROP_CHANCE = 0.85  # per check, once mid-activity (hands needed now)


def ensure_phone_state(c):
    return c.setdefault("phone_state", {"last_known_location": None, "forgotten": False, "pocketed": False})


def _find_nearest_surface(c, world, radius):
    building_id = c.get("building_id")
    best, best_dist = None, radius
    for prop in world.get("props", []):
        if prop.get("template") not in _SURFACE_TEMPLATES:
            continue
        if prop.get("building_id") != building_id:
            continue
        d = prop_distance(c, prop)
        if d <= best_dist:
            best, best_dist = prop, d
    return best


def maybe_set_phone_down(c, world):
    """Sets the phone down on a nearby flat surface once the character's
    hands are actually occupied -- sitting down (casual, moderate chance,
    normal search radius), or genuinely mid-activity (their hands are
    needed now, high chance, wider search since it matters more). No
    surface within reach either way -> stays in their pocket (inventory,
    untouched) rather than ever landing on bare ground."""
    state = ensure_phone_state(c)
    if state["last_known_location"] is not None:
        return  # already set down somewhere
    phone = get_phone(c)
    if not phone:
        return

    is_sitting = c.get("posture") in ("sitting_seat", "sitting_floor")
    act = c.get("activity") or {}
    is_busy = bool(act) and act.get("phase") != "walking"
    if not is_sitting and not is_busy:
        return
    if c.get("is_moving"):
        return

    chance = BUSY_DROP_CHANCE if is_busy else SIT_DROP_CHANCE
    if random.random() >= chance:
        return

    radius = _BUSY_SEARCH_RADIUS if is_busy else _SURFACE_SEARCH_RADIUS
    surface = _find_nearest_surface(c, world, radius)
    if not surface:
        state["pocketed"] = True
        return

    from systems.personal_items import place_item
    placed = place_item(c, phone["id"], surface["x"], surface["y"], world)
    if not placed:
        return
    state["last_known_location"] = {
        "building_id": c.get("building_id"),
        "x": surface["x"],
        "y": surface["y"],
        "prop_id": placed["id"],
        "surface_template": surface.get("template"),
    }
    state["forgotten"] = False
    state["pocketed"] = False


def maybe_forget_phone(c, world, previous_building_id):
    """Call when c["building_id"] changes. If the phone was left behind in
    the building just departed, mark it forgotten -- narrative-only flag,
    doesn't touch last_known_location (still retrievable via
    retrieve_phone, they just don't immediately know where it is)."""
    state = ensure_phone_state(c)
    loc = state.get("last_known_location")
    if not loc or loc.get("building_id") != previous_building_id:
        return
    if get_phone(c) is not None:
        return
    state["forgotten"] = True


def get_phone_context(c):
    """LLM narrative helper for where the phone currently is."""
    state = c.get("phone_state")
    if get_phone(c) is not None:
        return None
    if not state or not state.get("last_known_location"):
        return None
    if state.get("forgotten"):
        return "You're not sure where your phone is -- you think you left it somewhere."
    surface = (state["last_known_location"].get("surface_template") or "").replace("_", " ")
    where = f"on the {surface}" if surface else "nearby"
    return f"Your phone isn't on you -- you set it down {where}."


# ── Battery -- thin wrappers over systems/power.py's generic engine ─────────────
# Was phone-specific hardcoded drain/charge constants; now delegates to the
# generic battery engine (also used by laptops -- see power.py's docstring).
# Kept as phone.py functions so action_router.py/sim_loop.py's existing call
# sites don't need to change.
_MIN_USABLE = 5.0   # below this, phone actions are blocked (personal_items.py)


def update_phone_battery(c):
    """Drain (or skip while charging) the character's phone battery each
    tick. Should be called every tick from sim_loop."""
    from systems.power import tick_battery_items
    tick_battery_items(c)


def charge_phone(c, world):
    """
    Restore battery on the character's phone.
    Called each tick while the 'charge' activity is running.
    Requires phone_charger in inventory.
    Returns True if charging, False if prerequisites not met.
    """
    from systems.power import find_charger_for, charge_battery
    phone = get_phone(c)
    if not phone:
        return False
    charger = find_charger_for(c, phone)
    if not charger:
        return False
    return charge_battery(phone, charger)


# ── Context helper ─────────────────────────────────────────────────────────────
def phone_context(c):
    """Return a small dict for the LLM context about the character's phone."""
    from systems.personal_items import get_phone, phone_is_usable
    phone = get_phone(c)
    if not phone:
        return None
    states = phone.get("states", {})
    battery = states.get("battery", phone.get("battery", 100))
    return {
        "name":       phone.get("name", "Smartphone"),
        "battery":    round(float(battery), 1),
        "usable":     phone_is_usable(c),
        "powered_on": states.get("powered_on", battery > 0),
    }
