"""
systems/power.py

Generic battery engine, reusable by any item with states.battery -- not
phone-specific. Reads decay/charge rates off the item's OWN template
fields (battery_drain_idle/battery_drain_in_use on the device,
charges_per_tick on the charger) rather than hardcoded per-device-type
constants, so a new battery-powered item/charger pair works with zero
new code, just content.

systems/phone.py's update_phone_battery/charge_phone are now thin
wrappers over this module (action_router.py's call sites are
unchanged). This is also what makes laptop battery drain real for the
first time -- laptop_basic/laptop_gaming already had battery_drain_idle
authored in definitions.json, but nothing ever ticked it before this.
"""

DEFAULT_IDLE_DRAIN   = 0.05   # per tick, device sitting idle
DEFAULT_IN_USE_DRAIN = 0.30   # per tick, device actively being used
DEFAULT_CHARGE_RATE  = 0.80   # per tick while charging
MIN_USABLE           = 5.0    # battery floor below which a device is unusable

# object_type -> charger item template, naming convention. New
# battery-powered device types just need an entry here (or, if their
# charger template is named "<object_type>_charger", none at all -- see
# find_charger_for's fallback).
CHARGER_BY_OBJECT_TYPE = {
    "phone":    "phone_charger",
    "computer": "laptop_charger",
}

# interaction -> device object_type actively being used, for
# tick_battery_items' idle-vs-in-use drain rate selection.
_PHONE_INTERACTIONS = {
    "phone_call", "phone_answer", "phone_send_text",
    "phone_check", "phone_read_text",
}
_COMPUTER_INTERACTIONS = {
    "computer_social_media", "computer_videos", "computer_game",
    "computer_wiki_research", "computer_window_shopping", "computer_dating",
    "computer_job_search", "computer_apply_for_job", "computer_send_email",
    "computer_respond_email", "computer_check_email",
}


def is_battery_powered(item):
    return item is not None and "battery" in item.get("states", {})


def drain_battery(item, in_use=False):
    """Decay one item's battery by one tick. No-op if not battery-powered."""
    if not is_battery_powered(item):
        return
    states = item.setdefault("states", {})
    battery = float(states.get("battery", 100))
    if battery <= 0:
        states["battery"] = 0
        states["powered_on"] = False
        return
    drain = (
        item.get("battery_drain_in_use", DEFAULT_IN_USE_DRAIN) if in_use
        else item.get("battery_drain_idle", DEFAULT_IDLE_DRAIN)
    )
    battery = max(0.0, battery - drain)
    states["battery"] = round(battery, 2)
    if battery <= 0:
        states["powered_on"] = False


def charge_battery(item, charger):
    """Restore one item's battery by one tick, reading the charger's own
    charges_per_tick. Returns True if charging (even once full), False
    if the item isn't battery-powered."""
    if not is_battery_powered(item):
        return False
    states = item.setdefault("states", {})
    battery = float(states.get("battery", 100))
    if battery >= 100:
        return True
    rate = (charger or {}).get("charges_per_tick", DEFAULT_CHARGE_RATE)
    battery = min(100.0, battery + rate)
    states["battery"] = round(battery, 2)
    if battery >= MIN_USABLE:
        states["powered_on"] = True
    return True


def find_charger_for(c, device):
    """The matching charger item (by naming-convention lookup off the
    device's object_type) in the character's inventory, or None."""
    charger_template = CHARGER_BY_OBJECT_TYPE.get((device or {}).get("object_type"))
    if not charger_template:
        return None
    from systems.personal_items import get_item_by_template
    return get_item_by_template(c, charger_template)


def _active_device_type(c):
    interaction = (c.get("activity") or {}).get("interaction")
    if interaction in _PHONE_INTERACTIONS:
        return "phone"
    if interaction in _COMPUTER_INTERACTIONS:
        return "computer"
    return None


def charge_device(c, world):
    """Charge whichever device the character's current "charge" activity
    is targeting (action_router.py::_route_charge_device sets
    activity["device_item_id"]). Generic replacement for the old
    phone-only charge_phone -- works for any battery-powered item with a
    matching charger (see CHARGER_BY_OBJECT_TYPE)."""
    device_item_id = (c.get("activity") or {}).get("device_item_id")
    if not device_item_id:
        return False
    from systems.personal_items import get_item_by_id
    device = get_item_by_id(c, device_item_id)
    if not device:
        return False
    charger = find_charger_for(c, device)
    if not charger:
        return False
    return charge_battery(device, charger)


def tick_battery_items(c):
    """Sweep every battery-powered item in inventory, draining each --
    "in use" for whichever ones match the character's current phone/
    computer activity, idle otherwise. Skips entirely while a "charge"
    activity is running (that's charge_battery's job, called separately
    from the charge activity's own tick)."""
    if (c.get("activity") or {}).get("interaction") == "charge":
        return
    from systems.personal_items import get_inventory
    active_type = _active_device_type(c)
    for item in get_inventory(c):
        if not is_battery_powered(item):
            continue
        in_use = active_type is not None and item.get("object_type") == active_type
        drain_battery(item, in_use=in_use)
