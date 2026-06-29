"""
phone.py — smartphone battery management

Battery lives in item["states"]["battery"] (0–100).
Drains every tick at idle rate; faster while actively using phone interactions.
Charging restores it via the charge_device handler in action_router.

Called from sim_loop every tick for each character that carries a phone.
"""

from systems.personal_items import get_phone


# ── Battery constants ──────────────────────────────────────────────────────────
_IDLE_DRAIN_DEFAULT   = 0.05   # per tick when phone is in pocket
_IN_USE_DRAIN_DEFAULT = 0.30   # per tick when character is mid phone-action
_CHARGE_RATE_DEFAULT  = 0.80   # per tick while charge interaction is running
_MIN_USABLE           = 5.0    # below this, phone actions are blocked
_PHONE_ACTIVE_INTERACTIONS = {
    "phone_call", "phone_answer", "phone_send_text",
    "phone_check", "phone_read_text",
}


# ── Is this character currently doing a phone interaction? ─────────────────────
def _is_using_phone(c):
    act = c.get("activity") or {}
    return act.get("interaction") in _PHONE_ACTIVE_INTERACTIONS


# ── Per-tick drain ─────────────────────────────────────────────────────────────
def update_phone_battery(c):
    """
    Drain (or charge) the character's phone battery each tick.
    Should be called every tick from sim_loop.
    """
    phone = get_phone(c)
    if not phone:
        return

    states = phone.setdefault("states", {})
    battery = float(states.get("battery", 100))

    if battery <= 0:
        states["battery"] = 0
        states["powered_on"] = False
        return

    # Check if actively charging (activity == charge running near wall_socket)
    act = c.get("activity") or {}
    if act.get("interaction") == "charge":
        # charging is handled by the activity completion handler; skip drain
        return

    in_use = _is_using_phone(c)
    drain = (
        phone.get("battery_drain_in_use", _IN_USE_DRAIN_DEFAULT) if in_use
        else phone.get("battery_drain_idle", _IDLE_DRAIN_DEFAULT)
    )

    battery = max(0.0, battery - drain)
    states["battery"] = round(battery, 2)

    if battery <= 0:
        states["powered_on"] = False


# ── Charge handler ─────────────────────────────────────────────────────────────
def charge_phone(c, world):
    """
    Restore battery on the character's phone.
    Called each tick while the 'charge' activity is running.
    Requires phone_charger in inventory.
    Returns True if charging, False if prerequisites not met.
    """
    from systems.personal_items import has_item_template
    if not has_item_template(c, "phone_charger"):
        return False

    phone = get_phone(c)
    if not phone:
        return False

    states = phone.setdefault("states", {})
    battery = float(states.get("battery", 100))
    if battery >= 100:
        return True

    charge_rate = _CHARGE_RATE_DEFAULT
    battery = min(100.0, battery + charge_rate)
    states["battery"] = round(battery, 2)
    if battery >= 5:
        states["powered_on"] = True
    return True


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
