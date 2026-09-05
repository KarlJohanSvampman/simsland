"""
systems/home_presence.py

General-purpose "how much of today has this character spent at home"
tracking -- deliberately its own small module rather than buried inside
systems/telecom.py, since that's the first consumer (mobile data doesn't
cost anything for the fraction of the day spent home on a household's
own ISP wifi) but not expected to be the only one.

Sampled roughly once per sim-hour (see sim_loop.py's CADENCE
["home_presence"]) rather than continuously -- a single "are they home
right now" check per hour, not a genuine start-of-hour/end-of-hour pair;
close enough for a life-sim, and every other periodic check in this
codebase already works this way (chores, plants, ...).
"""

HOME_PRESENCE_TICKS_PER_HOUR = 3600  # 1 tick = 1 nominal game-second (sim_loop.py::advance_calendar())


def is_character_home(c, world):
    household = world.get("households", {}).get(c.get("household_id"))
    if not household:
        return False
    home_building_id = household.get("home_id")
    return home_building_id is not None and c.get("building_id") == home_building_id


def tick_home_presence_sample(c, world):
    """Called ~once per sim-hour. Accumulates two running counters on the
    character (how many hourly samples were taken today, how many of
    those found them home) -- read/reset together via
    consume_home_fraction_today() below, not exposed as raw fields other
    systems should poke at directly."""
    c["_home_hours_total_today"] = c.get("_home_hours_total_today", 0) + 1
    if is_character_home(c, world):
        c["_home_hours_today"] = c.get("_home_hours_today", 0) + 1


def consume_home_fraction_today(c):
    """Returns the fraction (0.0-1.0) of today's tracked hours spent at
    home, and resets the daily tally. "Consuming" rather than just
    reading keeps ownership of the daily rollover in ONE place -- the
    caller's own daily tick -- rather than every consumer separately
    guessing when the day rolled over. If no samples were taken yet
    today (e.g. a character created partway through a day), returns 0.0
    -- conservative: assume no home-time credit rather than fabricating
    some."""
    total = c.get("_home_hours_total_today", 0)
    home = c.get("_home_hours_today", 0)
    c["_home_hours_total_today"] = 0
    c["_home_hours_today"] = 0
    return (home / total) if total else 0.0
