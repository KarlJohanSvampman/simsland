"""
systems/bedtime.py -- going to bed on a night before a day that needs them.

Until now a character went to sleep only when fatigue crossed 75 at night -- which takes about 36 hours awake -- so a
household that was not already worn out simply stayed up all night, work or school the next morning or not. The schedule
has always had a sleep block (23:00-07:00) but nothing acted on it by itself.

wants_bed(c, world) is true when ALL of these hold:
  - it is night for them: their schedule's current block is `sleep` (or, with no schedule yet, the clock says 23:00-07:00);
  - they are not already asleep, not away from the grid and not travelling;
  - the day the night leads into has a daytime obligation: a work block starting between 05:00 and 15:00 in their schedule
    for that day, or -- for a child with a school -- a weekday. With no schedule for that day yet, a weekday counts
    (so Sunday night and Monday-Thursday nights send people to bed, a Friday or Saturday night does not by itself).
The morning in question is tomorrow's from 23:00 to midnight and today's from midnight to the end of the sleep block.

generate_body_intentions (systems/body_intentions.py) turns it into a `sleep` intention (reason "bedtime").
"""

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WORK_START_EARLIEST, WORK_START_LATEST = 5, 15
SLEEP_FALLBACK = (23, 7)                 # used when the schedule has no sleep block to read


def _next_day(day):
    return WEEKDAYS[(WEEKDAYS.index(day) + 1) % 7]


def in_sleep_time(c, world):
    block = c.get("active_schedule_block")
    if block:
        return block.get("activity") == "sleep"
    hour = (world.get("calendar") or {}).get("hour")
    return hour is not None and (hour >= SLEEP_FALLBACK[0] or hour < SLEEP_FALLBACK[1])


def morning_day(world):
    """The weekday of the morning this night leads into."""
    cal = world.get("calendar") or {}
    today = str(cal.get("weekday", "")).lower()
    if today not in WEEKDAYS:
        return None
    return _next_day(today) if cal.get("hour", 0) >= 12 else today


def has_daytime_obligation(c, day):
    """Work in the daytime (or school, for a child) on `day`."""
    if day not in WEEKDAYS:
        return False
    plan = (c.get("schedule") or {}).get("week", {}).get(day)
    if plan is not None:
        for b in plan:
            if b.get("activity") == "work":
                try:
                    if WORK_START_EARLIEST <= int(b["start"][:2]) <= WORK_START_LATEST:
                        return True
                except (KeyError, ValueError):
                    pass
    child_at_school = (c.get("age") or 99) < 18 and bool(c.get("current_school"))
    if child_at_school:
        return day in WEEKDAYS[:5]
    if plan is None:
        return day in WEEKDAYS[:5] and bool((c.get("job") or {}).get("id")) and c["job"]["id"] != "retired"
    return False


def wants_bed(c, world):
    if not world or c.get("off_grid") or c.get("travel_state") or c.get("travel"):
        return False
    if (c.get("activity") or {}).get("type") in ("sleep", "nap"):
        return False
    if not in_sleep_time(c, world):
        return False
    return has_daytime_obligation(c, morning_day(world))
