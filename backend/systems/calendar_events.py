# =========================================================
# CALENDAR EVENTS
#
# Handles recurring annual events:
#   - Fixed holidays (Christmas, Thanksgiving, 4th of July, New Years)
#   - Character birthdays (randomly assigned, recur annually)
#
# Each event carries prep_requirements so the anticipatory-intention
# system knows what preparation a character should do beforehand.
#
# Prep types:
#   buy_gift        shop for a gift for someone
#   buy_supplies    food, decorations, party supplies
#   get_outfit      buy or pick an outfit to wear
#   book_transport  arrange a ride or buy tickets
#   send_card       send a physical or digital card
#   plan_gathering  organise a party / gathering at home
#   cook_meal       prepare a special meal
#
# Thresholds:  30d → awareness (priority 15)
#              14d → start shopping (priority 40)
#               7d → escalate (priority 65)
#               3d → urgent (priority 80)
#               1d → final prep (priority 90)
#               0d → day-of celebration (priority 95)
# =========================================================

import time
import random
from datetime import date, timedelta


# ----------------------------------------------------------
# HOLIDAY DEFINITIONS
# ----------------------------------------------------------

def _nth_weekday(year, month, weekday, n):
    """Return date of nth occurrence of weekday (0=Mon…6=Sun) in month/year."""
    d      = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    first  = d + timedelta(days=offset)
    return first + timedelta(weeks=n - 1)


def _thanksgiving_date(year):
    """4th Thursday of November."""
    d = _nth_weekday(year, 11, 3, 4)
    return d.month, d.day


HOLIDAYS = [
    {
        "id":               "new_years",
        "name":             "New Year's Eve / Day",
        "emoji":            "🎆",
        "resolver":         (1, 1),
        "prep_requirements": ["buy_supplies", "get_outfit", "plan_gathering"],
        "description":      "Ring in the new year with friends and family.",
    },
    {
        "id":               "fourth_of_july",
        "name":             "4th of July",
        "emoji":            "🎇",
        "resolver":         (7, 4),
        "prep_requirements": ["buy_supplies", "cook_meal"],
        "description":      "Independence Day — fireworks, BBQs, and celebration.",
    },
    {
        "id":               "thanksgiving",
        "name":             "Thanksgiving",
        "emoji":            "🦃",
        "resolver":         _thanksgiving_date,
        "prep_requirements": ["buy_supplies", "cook_meal", "plan_gathering"],
        "description":      "Gather with family for a big meal and gratitude.",
    },
    {
        "id":               "christmas",
        "name":             "Christmas",
        "emoji":            "🎄",
        "resolver":         (12, 25),
        "prep_requirements": ["buy_gift", "buy_supplies", "get_outfit", "plan_gathering", "send_card"],
        "description":      "Exchange gifts and celebrate with loved ones.",
    },
]


# ----------------------------------------------------------
# DATE HELPERS
# ----------------------------------------------------------

_MONTH_LENGTHS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _resolve_holiday(holiday, year):
    r = holiday["resolver"]
    if callable(r):
        return r(year)
    return r


def days_until(month, day, world):
    """
    Days until next occurrence of month/day based on world calendar.
    Returns a value in [0, 365].
    """
    cal   = world.get("calendar", {})
    today = date(cal.get("year", 2025), cal.get("month", 1), cal.get("day", 1))
    try:
        target = date(today.year, month, day)
    except ValueError:
        target = date(today.year, month, day - 1) + timedelta(days=1)
    if target < today:
        try:
            target = date(today.year + 1, month, day)
        except ValueError:
            target = date(today.year + 1, month, day - 1) + timedelta(days=1)
    return (target - today).days


# ----------------------------------------------------------
# BIRTHDAY ASSIGNMENT
# ----------------------------------------------------------

def assign_birthday(c, world):
    """Assign a random birth month/day to a character (avoids today)."""
    cal     = world.get("calendar", {})
    today_m = cal.get("month", 1)
    today_d = cal.get("day",   1)
    month   = random.randint(1, 12)
    day     = random.randint(1, _MONTH_LENGTHS[month - 1])
    if month == today_m and day == today_d:
        day = (day % _MONTH_LENGTHS[month - 1]) + 1
    c["birthday"] = {"month": month, "day": day}


# ----------------------------------------------------------
# UPCOMING EVENT AGGREGATION
# ----------------------------------------------------------

def get_upcoming_events(c, world, horizon_days=60):
    """
    Return upcoming calendar events for character c within horizon_days,
    sorted by days_until ascending.
    """
    events = []
    cal    = world.get("calendar", {})
    year   = cal.get("year", 2025)

    for h in HOLIDAYS:
        m, d = _resolve_holiday(h, year)
        n    = days_until(m, d, world)
        if callable(h["resolver"]) and n > 180:
            m2, d2 = h["resolver"](year + 1)
            n2 = days_until(m2, d2, world)
            if n2 < n:
                m, d, n = m2, d2, n2
        if n <= horizon_days:
            events.append({
                "id":               h["id"],
                "name":             h["name"],
                "emoji":            h["emoji"],
                "type":             "holiday",
                "days_until":       n,
                "month":            m,
                "day":              d,
                "prep_requirements": list(h["prep_requirements"]),
                "description":      h["description"],
                "for_char_id":      None,
            })

    chars_to_check = [c]
    hh_id = c.get("household_id")
    if hh_id:
        for other in world.get("characters", {}).values():
            if other["id"] != c["id"] and other.get("household_id") == hh_id:
                chars_to_check.append(other)

    for char in chars_to_check:
        bd = char.get("birthday")
        if not bd:
            continue
        n = days_until(bd["month"], bd["day"], world)
        if n > horizon_days:
            continue
        is_own    = char["id"] == c["id"]
        char_name = char.get("name", "Someone")
        ev_name   = "Your birthday" if is_own else (char_name + "'s birthday")
        ev_desc   = "Your birthday is coming up." if is_own else (char_name + "'s birthday is coming up.")
        events.append({
            "id":               "birthday_" + char["id"],
            "name":             ev_name,
            "emoji":            "🎂",
            "type":             "birthday",
            "days_until":       n,
            "month":            bd["month"],
            "day":              bd["day"],
            "prep_requirements": [] if is_own else ["buy_gift", "send_card", "plan_gathering"],
            "description":      ev_desc,
            "for_char_id":      char["id"],
        })

    events.sort(key=lambda e: e["days_until"])
    return events


# ----------------------------------------------------------
# ANTICIPATORY INTENTIONS
# ----------------------------------------------------------

_THRESHOLDS = [
    (0,  95, "Today is"),
    (1,  90, "Tomorrow is"),
    (3,  80, "In 3 days:"),
    (7,  65, "In a week:"),
    (14, 40, "In 2 weeks:"),
    (30, 15, "In a month:"),
]


def _threshold_for_days(n):
    for t, priority, prefix in _THRESHOLDS:
        if n <= t:
            return t, priority, prefix
    return None, None, None


def _already_has_intention(c, intent_type, event_id):
    for i in c.get("active_intentions", []):
        if i.get("type") == intent_type and i.get("event_id") == event_id:
            return True
    return False


def _inject_intention(c, intent_type, priority, event, extra=None):
    if _already_has_intention(c, intent_type, event["id"]):
        return
    intent = {
        "type":        intent_type,
        "priority":    priority,
        "source":      "calendar",
        "event_id":    event["id"],
        "event_name":  event["name"],
        "occasion":    event["type"],
        "days_until":  event["days_until"],
        "for_char_id": event.get("for_char_id"),
    }
    if extra:
        intent.update(extra)
    c.setdefault("active_intentions", []).append(intent)


def _inject_intentions_for_event(c, event):
    n    = event["days_until"]
    prep = event["prep_requirements"]

    if n == 0:
        _inject_intention(c, "celebrate_event", 95, event)
        return

    t, priority, _ = _threshold_for_days(n)
    if priority is None:
        return

    _inject_intention(c, "prepare_for_event", priority, event, {
        "prep_requirements": prep,
    })

    if "buy_gift" in prep and n <= 14:
        _inject_intention(c, "buy_gift", min(priority + 5, 95), event, {
            "for_char_id": event.get("for_char_id"),
        })

    if "get_outfit" in prep and n <= 7:
        _inject_intention(c, "get_outfit", priority - 5, event)

    if "buy_supplies" in prep and n <= 7:
        _inject_intention(c, "buy_supplies", priority - 10, event)

    if "cook_meal" in prep and n <= 1:
        _inject_intention(c, "cook_special_meal", priority, event)

    if "plan_gathering" in prep and n <= 14:
        _inject_intention(c, "plan_gathering", priority - 15, event)

    if "send_card" in prep and n <= 7:
        _inject_intention(c, "send_card", priority - 20, event)

    if "book_transport" in prep and n <= 3:
        _inject_intention(c, "book_transport", priority - 5, event)


def _inject_intentions_for_social_rsvp(c, world):
    """
    Inject prep intentions for social events the character has RSVP'd yes to,
    including dress_code and cost-budgeting reminders.
    """
    now_ts = time.time()
    for evt in world.get("social_events", {}).values():
        if evt.get("status") != "published":
            continue
        if c["id"] not in evt.get("attendees", []):
            continue
        start_ts = evt.get("start_ts")
        if not start_ts or start_ts < now_ts:
            continue
        days_left = int((start_ts - now_ts) / 86400)
        if days_left > 60:
            continue
        t, priority, _ = _threshold_for_days(days_left)
        if priority is None:
            continue

        fake_event = {
            "id":               "social_" + evt["id"],
            "name":             evt.get("title", "social event"),
            "type":             "social_event",
            "days_until":       days_left,
            "for_char_id":      None,
            "prep_requirements": evt.get("prep_requirements", []),
        }

        _inject_intention(c, "prepare_for_event", priority, fake_event, {
            "social_event_id":  evt["id"],
            "prep_requirements": evt.get("prep_requirements", []),
        })

        dress_code = evt.get("dress_code")
        if dress_code and dress_code != "casual" and days_left <= 7:
            if not _already_has_intention(c, "get_outfit", fake_event["id"]):
                _inject_intention(c, "get_outfit", priority, fake_event, {
                    "dress_code":      dress_code,
                    "social_event_id": evt["id"],
                })

        cost = evt.get("cost_per_person", 0)
        if cost > 0 and days_left <= 14:
            if not _already_has_intention(c, "budget_for_event", fake_event["id"]):
                _inject_intention(c, "budget_for_event", max(priority - 20, 10), fake_event, {
                    "amount":          cost,
                    "social_event_id": evt["id"],
                })


# ----------------------------------------------------------
# MAIN DAILY CHECK
# ----------------------------------------------------------

def check_calendar_reminders(world):
    """
    Run periodically in sim_loop; internally guards to fire once per real day.
    Injects anticipatory intentions for every non-service-worker character.
    """
    cal       = world.get("calendar", {})
    today_key = "{}-{}-{}".format(
        cal.get("year", 0), cal.get("month", 0), cal.get("day", 0)
    )
    if world.get("_cal_reminder_day") == today_key:
        return
    world["_cal_reminder_day"] = today_key

    for c in world.get("characters", {}).values():
        if c.get("is_service_worker"):
            continue
        upcoming = get_upcoming_events(c, world, horizon_days=60)
        for event in upcoming:
            _inject_intentions_for_event(c, event)
        _inject_intentions_for_social_rsvp(c, world)
