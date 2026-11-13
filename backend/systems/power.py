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


# ── batteries as lazy values of sim time (core/lazy.py) ───────────────────────────────────────────────────────────────
# A battery drains (idle / in use) or charges at a steady per-tick rate that depends only on what its owner is doing --
# the "regime". It is brought up to date (sync_batteries) in the owner's own update and right after it, under the
# regime recorded at the last sync, and a scheduler timer fires at the next moment that matters: a draining device
# hitting 0 (it switches off), a charging one becoming usable or full. The old per-second job drained everyone's
# devices, the off-grid included; so does this.

def battery_regime(c):
    act = c.get("activity") or {}
    if act.get("interaction") == "charge":
        return ["charge", act.get("device_item_id")]
    return ["use", _active_device_type(c)]


def _apply_regime(c, regime, ticks):
    from systems.personal_items import get_inventory, get_item_by_id
    if regime[0] == "charge":
        device = get_item_by_id(c, regime[1]) if regime[1] else None
        charger = find_charger_for(c, device) if device else None
        if not device or not charger or not is_battery_powered(device):
            return                      # (as before: a charge activity drains nothing, and charges only with a charger)
        states = device.setdefault("states", {})
        battery = min(100.0, float(states.get("battery", 100)) + charger.get("charges_per_tick", DEFAULT_CHARGE_RATE) * ticks)
        states["battery"] = round(battery, 2)
        if battery >= MIN_USABLE:
            states["powered_on"] = True
        return
    for item in get_inventory(c):
        if not is_battery_powered(item):
            continue
        in_use = regime[1] is not None and item.get("object_type") == regime[1]
        rate = item.get("battery_drain_in_use", DEFAULT_IN_USE_DRAIN) if in_use else item.get("battery_drain_idle", DEFAULT_IDLE_DRAIN)
        states = item.setdefault("states", {})
        battery = max(0.0, float(states.get("battery", 100)) - rate * ticks)
        states["battery"] = round(battery, 2)
        if battery <= 0:
            states["powered_on"] = False


def sync_batteries(c, world):
    """Bring c's batteries up to now under the regime that held since the last sync, then note the current one and set
    the timer for the next battery moment."""
    from core.lazy import elapsed_ticks
    st = c.setdefault("_battery", {})
    ticks = elapsed_ticks(st, "t", world)
    if ticks and st.get("regime"):
        _apply_regime(c, st["regime"], ticks)
    st["regime"] = battery_regime(c)
    _arm_battery_timer(c, world, st["regime"])


def _arm_battery_timer(c, world, regime):
    from core import scheduler
    from core.clock import now_ts
    from core.tick_schedule import TICK_RATE_SECONDS
    from systems.personal_items import get_inventory, get_item_by_id
    waits = []
    if regime[0] == "charge":
        device = get_item_by_id(c, regime[1]) if regime[1] else None
        charger = find_charger_for(c, device) if device else None
        if device and charger and is_battery_powered(device):
            b = float(device.get("states", {}).get("battery", 100))
            rate = charger.get("charges_per_tick", DEFAULT_CHARGE_RATE)
            if rate > 0:
                for target in (MIN_USABLE, 100.0):
                    if b < target:
                        waits.append((target - b) / rate)
    else:
        for item in get_inventory(c):
            if not is_battery_powered(item):
                continue
            b = float(item.get("states", {}).get("battery", 100))
            in_use = regime[1] is not None and item.get("object_type") == regime[1]
            rate = item.get("battery_drain_in_use", DEFAULT_IN_USE_DRAIN) if in_use else item.get("battery_drain_idle", DEFAULT_IDLE_DRAIN)
            if b > 0 and rate > 0:
                waits.append(b / rate)
    owner = f"battery:{c.get('id')}"
    if waits:
        scheduler.schedule_at(world, owner, "next", now_ts(world) + min(waits) * TICK_RATE_SECONDS + 1e-6)
    else:
        scheduler.cancel(world, owner, "next")


def _on_battery_timer(world, entry):
    c = (world.get("characters") or {}).get(entry["owner"].split(":", 1)[1])
    if c:
        sync_batteries(c, world)


def sync_all_batteries(world, entry=None):
    """Everyone (a loaded world, a newcomer): batteries brought up to date and timed."""
    for c in (world.get("characters") or {}).values():
        if not c.get("is_workplace_npc"):
            sync_batteries(c, world)


from core import scheduler as _scheduler      # noqa: E402
_scheduler.register("battery", _on_battery_timer)
