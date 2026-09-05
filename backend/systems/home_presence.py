"""
systems/home_presence.py

General-purpose "how much of today (and recent days) has this character
spent at home" tracking -- its own small module rather than buried
inside systems/telecom.py (the first consumer) since systems/
withdrawal_concern.py (a sustained-high-home-time drama mechanic) needs
the SAME data too. That second consumer is exactly why this round
replaced the original consume-and-reset single-shot API with a proper
daily rollover into a rolling history: two independent systems both
wanting "today's fraction" can't both destructively consume it.

Sampled roughly once per sim-hour (see sim_loop.py's CADENCE
["home_presence"]) rather than continuously -- a single "are they home
right now" check per hour, not a genuine start-of-hour/end-of-hour pair;
close enough for a life-sim, and every other periodic check in this
codebase already works this way (chores, plants, ...).
"""

HOME_PRESENCE_TICKS_PER_HOUR = 3600  # 1 tick = 1 nominal game-second (sim_loop.py::advance_calendar())
HOME_FRACTION_HISTORY_DAYS = 14


def is_character_home(c, world):
    household = world.get("households", {}).get(c.get("household_id"))
    if not household:
        return False
    home_building_id = household.get("home_id")
    return home_building_id is not None and c.get("building_id") == home_building_id


def tick_home_presence_sample(c, world):
    """Called ~once per sim-hour. Accumulates two running counters on the
    character (how many hourly samples were taken today, how many of
    those found them home) -- rolled into history once a day by
    roll_over_home_presence_day() below, not read directly."""
    c["_home_hours_total_today"] = c.get("_home_hours_total_today", 0) + 1
    if is_character_home(c, world):
        c["_home_hours_today"] = c.get("_home_hours_today", 0) + 1


def roll_over_home_presence_day(c):
    """Called once per real calendar day (see sim_loop.py -- the SAME
    daily cadence systems/telecom.py's data tick and systems/
    subscriptions.py's peer-desire check already run on). Computes the
    day that just completed, appends it to a rolling, capped history,
    resets the hourly counters, and returns the fraction -- the ONE
    place responsible for the daily reset, so multiple consumers can
    each read the history afterward without stepping on each other via
    a destructive read (the original design's mistake -- fixed here)."""
    total = c.get("_home_hours_total_today", 0)
    home = c.get("_home_hours_today", 0)
    fraction = (home / total) if total else 0.0

    history = c.setdefault("_home_fraction_history", [])
    history.append(fraction)
    del history[:-HOME_FRACTION_HISTORY_DAYS]

    c["_home_hours_total_today"] = 0
    c["_home_hours_today"] = 0
    return fraction


def recent_home_fraction_average(c, days=3):
    history = c.get("_home_fraction_history", [])
    recent = history[-days:] if days else history
    return sum(recent) / len(recent) if recent else 0.0


def consecutive_high_home_days(c, threshold):
    """How many of the most recent COMPLETED days (walking backward from
    yesterday) had a home fraction at/above threshold -- stops counting
    at the first day that dips below. Used to detect a SUSTAINED
    pattern (systems/withdrawal_concern.py), not a single unusual day."""
    history = c.get("_home_fraction_history", [])
    count = 0
    for frac in reversed(history):
        if frac >= threshold:
            count += 1
        else:
            break
    return count


def consecutive_low_home_days(c, threshold):
    """The mirror image of consecutive_high_home_days() -- how many of the
    most recent COMPLETED days had a home fraction AT/BELOW threshold,
    i.e. a sustained pattern of being away too much rather than staying
    home too much. Used by systems/absence_suspicion.py."""
    history = c.get("_home_fraction_history", [])
    count = 0
    for frac in reversed(history):
        if frac <= threshold:
            count += 1
        else:
            break
    return count
