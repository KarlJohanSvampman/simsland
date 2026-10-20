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


def now(world):
    return world.get("tick", 0)


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
