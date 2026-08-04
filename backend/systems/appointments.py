# =========================================================
# APPOINTMENTS
# Deterministic (non-LLM) slot-picking for book_appointment -- resolves
# immediately if the business's phone line is currently open, no LLM
# call involved (see systems/business_hours.py for the open/closed
# check itself). Real tailored responses/callbacks for the *support*
# side (contact_business) are generated later by the async background
# job in systems/business_support.py (Round 6), not here.
# =========================================================

import random

from core.tick_schedule import TICK_RATE_SECONDS

_TICKS_PER_HOUR = round(3600 / TICK_RATE_SECONDS)
_TICKS_PER_DAY  = _TICKS_PER_HOUR * 24


def next_available_slot(business, world, days_ahead_range=(1, 3)):
    """Pick a tick some days out, at a random hour inside the business's
    opening_hours window. Only meaningful for service-kind businesses
    with real opening_hours -- callers should already have checked
    business_hours.is_open(..., "phone") before calling this."""
    hours = business.get("opening_hours") or {"open": 9, "close": 17}
    open_h, close_h = hours.get("open", 9), hours.get("close", 17)
    if close_h <= open_h:
        close_h = open_h + 1

    days_out = random.randint(*days_ahead_range)
    hour = random.randint(open_h, close_h - 1)

    cal = world.get("calendar", {})
    ticks_since_midnight = (
        cal.get("hour", 0) * _TICKS_PER_HOUR
        + cal.get("minute", 0) * (_TICKS_PER_HOUR // 60)
    )
    start_of_today = world.get("tick", 0) - ticks_since_midnight
    return start_of_today + days_out * _TICKS_PER_DAY + hour * _TICKS_PER_HOUR


def book(c, world, business_key, business, reason):
    """Store a confirmed appointment on the character. Returns the
    appointment dict."""
    appt = {
        "id":        f"appt_{world.get('tick', 0)}_{len(c.get('appointments', []))}",
        "business":  business_key,
        "reason":    reason,
        "tick":      next_available_slot(business, world),
        "fulfilled": False,
    }
    c.setdefault("appointments", []).append(appt)
    return appt


def has_upcoming_appointment(c, business_key=None):
    """Whether the character has a confirmed, not-yet-fulfilled
    appointment -- optionally scoped to one business (e.g. "hospital"/
    "gp_clinic" for the doctor-visit gate in systems/offgrid.py)."""
    for appt in c.get("appointments", []):
        if appt.get("fulfilled"):
            continue
        if business_key and appt.get("business") != business_key:
            continue
        return appt
    return None


def is_appointment_due(appt, world):
    return appt is not None and world.get("tick", 0) >= appt.get("tick", 0)
