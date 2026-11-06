"""
core/clock.py

The simulation clock: time exists, and it announces meaningful boundaries. It never
iterates over characters or "asks everyone" anything -- that is the point of the
event-driven architecture (docs/distributed_architecture_plan.md): NO global
tick that does work, YES a clock that says what time it is and when an hour/day/
week/month starts.

  now(world)        the current simulation tick (1 tick = 1 nominal sim second at 1x)
  calendar(world)   the calendar dict (year/month/day/hour/minute/...)
  advance(world)    called once per tick right after the calendar moves: emits the
                    boundary events below, each exactly once per period

Events (data = the calendar dict plus the stamp that identifies the period):
  time.hour    the first tick of a new sim hour
  time.day     the first tick of a new calendar day
  time.week    the first tick of Monday 00:xx
  time.month   the first tick of the 1st of a month, hour 0

Each is guarded by a stamp stored on the world as a STRING (not a tuple, so the JSON round
trip can't silently break the comparison), so a restart can't re-fire a period that already
fired, and `cal["minute"] == 0` staying true for 60 ticks can't fire it 60 times.
"""

from core.event_bus import emit

# Durations are sim time, in seconds. Write them with these: 5 * MINUTE, 2 * HOUR, DAY -- never as a bare tick count
# (a tick is one step of the loop; that it currently equals one sim second is a fact about TICK_RATE_SECONDS, not a unit).
SECOND = 1
MINUTE = 60 * SECOND
HOUR = 60 * MINUTE
DAY = 24 * HOUR
WEEK = 7 * DAY


def now(world):
    return world.get("tick", 0)


def now_ts(world):
    """The simulation's current time as a timestamp (sim seconds, world["sim_time"]). A world without a sim clock (a bare
    test world) counts its ticks as seconds."""
    ts = world.get("sim_time")
    return float(ts) if ts is not None else float(world.get("tick", 0))


def seconds_into_day(world):
    """Sim seconds since midnight, from the calendar the sim keeps (or the timestamp when there is none)."""
    cal = world.get("calendar") or {}
    if cal.get("hour") is not None:
        return cal.get("hour", 0) * HOUR + cal.get("minute", 0) * MINUTE + int(cal.get("second", 0) or 0)
    if world.get("sim_time") is None:
        return int(now_ts(world)) % DAY
    from datetime import datetime
    d = datetime.fromtimestamp(world["sim_time"])
    return d.hour * HOUR + d.minute * MINUTE + d.second


def next_time_of_day(world, at_seconds):
    """The timestamp of the next time the clock reads `at_seconds` past midnight (strictly after now)."""
    now = now_ts(world)
    due = now - seconds_into_day(world) + at_seconds
    while due <= now:
        due += DAY
    return due


def next_minute_of_hour(world, at_seconds):
    """The timestamp of the next time the clock reads `at_seconds` past the hour (strictly after now)."""
    now = now_ts(world)
    due = now - (seconds_into_day(world) % HOUR) + at_seconds
    while due <= now:
        due += HOUR
    return due


def calendar(world):
    return world.get("calendar", {})


def _fire_once(world, stamp_key, stamp, event, cal):
    if world.get(stamp_key) == stamp:
        return False
    world[stamp_key] = stamp
    emit(event, dict(cal, stamp=stamp, tick=world.get("tick", 0)))
    return True


def advance(world):
    """Emit this tick's boundary events. Call after the calendar has been advanced."""
    cal = calendar(world)
    if not cal:
        return []
    fired = []
    day_stamp = f"{cal.get('year')}-{cal.get('month')}-{cal.get('day')}"
    if cal.get("minute") == 0:
        if _fire_once(world, "_clock_hour", f"{day_stamp}-{cal.get('hour')}", "time.hour", cal):
            fired.append("time.hour")
    if _fire_once(world, "_clock_day", day_stamp, "time.day", cal):
        fired.append("time.day")
    if cal.get("weekday") == "Monday" and cal.get("hour") == 0:
        if _fire_once(world, "_clock_week", day_stamp, "time.week", cal):
            fired.append("time.week")
    if cal.get("day") == 1 and cal.get("hour") == 0:
        if _fire_once(world, "_clock_month", f"{cal.get('year')}-{cal.get('month')}", "time.month", cal):
            fired.append("time.month")
    return fired
