"""
phone.py — smartphone battery management

Battery lives in item["states"]["battery"] (0–100).
Drains every tick at idle rate; faster while actively using phone interactions.
Charging restores it via the charge_device handler in action_router.

Called from sim_loop every tick for each character that carries a phone.
"""

import random

from systems.personal_items import get_phone


# ── Carry/drop/forget ────────────────────────────────────────────────────────
# The phone isn't meant to sit invisibly in inventory forever -- characters
# occasionally set it down as a matter of habit (maybe_set_phone_down),
# tracked via phone_state["last_known_location"] so it can be walked back to
# (action_router.py's retrieve_phone). Leaving the building it was left in
# without it (maybe_forget_phone) is the "genuinely forgot it" case the
# location memory alone doesn't capture -- distance, not time, is what
# turns "set down" into "forgotten", matching "normally won't go too far
# from it."

DROP_CHANCE_PER_CHECK = 0.03  # small per cadence-tick chance while stationary


def ensure_phone_state(c):
    return c.setdefault("phone_state", {"last_known_location": None, "forgotten": False})


def maybe_set_phone_down(c, world):
    """Small chance of setting the phone down at the character's current
    spot while stationary -- reuses personal_items.py::drop_item as-is."""
    state = ensure_phone_state(c)
    if state["last_known_location"] is not None:
        return  # already set down somewhere
    if c.get("is_moving"):
        return
    phone = get_phone(c)
    if not phone:
        return
    if random.random() >= DROP_CHANCE_PER_CHECK:
        return

    from systems.personal_items import drop_item
    dropped = drop_item(c, phone["id"], world)
    if not dropped:
        return
    state["last_known_location"] = {
        "building_id": c.get("building_id"),
        "x": c.get("x", 0),
        "y": c.get("y", 0),
        "prop_id": dropped["id"],
    }
    state["forgotten"] = False


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
    if not state or not state.get("last_known_location"):
        return None
    if get_phone(c) is not None:
        return None
    if state.get("forgotten"):
        return "You're not sure where your phone is -- you think you left it somewhere."
    return "Your phone isn't on you -- you set it down nearby."


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
