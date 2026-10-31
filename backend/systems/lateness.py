"""
systems/lateness.py -- running late for something scheduled, and running over.

A work shift or a booked appointment does not always start and end on the minute. A share of the time (LATE_CHANCE) a character
leaves late for it, and a share of the time it runs over; each by 10 to 60 minutes, for a reason that goes into the story of the trip
(systems/offgrid.py writes the summary, systems/offgrid_summary.py the key events). Late and over use the same chance and the same
range: it is as likely that they are held up at the end as that they were late at the start.

Per trip, two records on the character (`c["_trip_late"]`):
    {"start": {"minutes", "reason"}, "over": {"minutes", "reason", "until_tick"}}
and when a shift ran over, `c["late_home"] = {"day", "minutes", "reason"}` is left for the dinner decision (systems/food_habits.py).

A trip is told by its kind: "work" (the shift of the schedule) or "appt" (a booked appointment, systems/offgrid.py::resolve_due_appointments).
"""

import random

from core.tick_schedule import TICK_RATE_SECONDS

LATE_CHANCE = 0.25
MIN_MINUTES = 10
MAX_MINUTES = 60

START_REASONS = {
    "work": ["the bus was late", "the traffic was heavy", "something at home took longer than planned", "could not find the keys",
             "overslept a little", "had to deal with a phone call on the way out", "ran back for something they had forgotten"],
    "appt": ["the bus was late", "the traffic was heavy", "something at home took longer than planned", "could not find the keys",
             "lost track of the time", "ran back for something they had forgotten"],
}
OVER_REASONS = {
    "work": ["a meeting ran over", "had to finish something that could not wait until tomorrow", "a colleague needed a hand",
             "a customer came in just before closing", "a piece of equipment broke down and had to be sorted out",
             "the manager called a short briefing at the end of the day", "a delivery arrived at the last minute"],
    "appt": ["the appointment started late and ran over", "had to wait longer than expected", "there was a queue at the counter",
             "there was more to go through than expected"],
}


def _ticks(minutes):
    return int(minutes * 60 / TICK_RATE_SECONDS)


def _day(world):
    cal = world.get("calendar") or {}
    return (cal.get("year"), cal.get("month"), cal.get("day"))


def roll(kind, reasons, rng=random):
    """None, or (minutes, reason) -- LATE_CHANCE of the time."""
    if rng.random() >= LATE_CHANCE:
        return None
    return rng.randint(MIN_MINUTES, MAX_MINUTES), rng.choice(reasons[kind])


# ---- late for the start ------------------------------------------------------------------------------------------------------------------
def _starts(c):
    return c.setdefault("_late_starts", {})


def holds_start(c, world, kind, rng=random, key=None):
    """True while a character who is due to set off for `kind` is running late. The first call rolls it (`key` tells two trips of one
    kind apart, e.g. two appointments in a day; by default it is the kind, once a day)."""
    recs = _starts(c)
    key = key or kind
    rec = recs.get(key)
    if rec is None or rec["day"] != _day(world):
        got = roll(kind, START_REASONS, rng)
        minutes, reason = got if got else (0, None)
        rec = recs[key] = {"day": _day(world), "minutes": minutes, "reason": reason, "until_tick": world["tick"] + _ticks(minutes), "left": False}
    return not rec["left"] and world["tick"] < rec["until_tick"]


def start_pending(c, world, kind, key=None):
    """A late start that has been rolled today and has not yet set off (its window may be past the usual start time)."""
    rec = _starts(c).get(key or kind)
    return bool(rec and rec["day"] == _day(world) and rec["minutes"] and not rec["left"])


def departed(c, world, kind, key=None):
    """The trip has set off: keep what the late start was for the trip's story."""
    recs = _starts(c)
    rec = recs.get(key or kind)
    trip = c.setdefault("_trip_late", {})
    trip.clear()
    trip["kind"] = kind
    if rec and rec["day"] == _day(world):
        rec["left"] = True
        if rec["minutes"]:
            trip["start"] = {"minutes": rec["minutes"], "reason": rec["reason"]}
    if len(recs) > 12:                               # appointment keys pile up; only today's matter
        for k in [k for k, r in recs.items() if r["day"] != _day(world)]:
            del recs[k]


# ---- running over ------------------------------------------------------------------------------------------------------------------------
def holds_end(c, world, kind, rng=random):
    """True while a trip that is due to end is being held up. The first call at the end rolls it; a hold moves the trip's return tick."""
    trip = c.setdefault("_trip_late", {})
    over = trip.get("over")
    if over is None:
        got = roll(kind, OVER_REASONS, rng)
        minutes, reason = got if got else (0, None)
        over = trip["over"] = {"minutes": minutes, "reason": reason, "until_tick": world["tick"] + _ticks(minutes)}
        if minutes:
            c["return_tick"] = over["until_tick"]
    return world["tick"] < over["until_tick"]


# ---- the story ---------------------------------------------------------------------------------------------------------------------------
def finish(c, world):
    """The trip is over: its lateness record (or None) is handed over and cleared; a run-over leaves `late_home` for dinner."""
    trip = c.pop("_trip_late", None) or {}
    over = trip.get("over")
    if over and over.get("minutes"):
        c["late_home"] = {"day": _day(world), "minutes": over["minutes"], "reason": over["reason"], "tick": world["tick"]}
    return {k: v for k, v in trip.items() if k == "start" or (k == "over" and v.get("minutes"))} or None


def note(late):
    """A sentence or two for the summary; empty when they were not late."""
    if not late:
        return ""
    bits = []
    if late.get("start"):
        bits.append(f"They set off {late['start']['minutes']} minutes late: {late['start']['reason']}.")
    if late.get("over"):
        bits.append(f"It ran {late['over']['minutes']} minutes over: {late['over']['reason']}.")
    return " ".join(bits)


def late_home_today(c, world):
    """Minutes the last shift ran over today, or 0."""
    rec = c.get("late_home")
    return rec["minutes"] if rec and rec.get("day") == _day(world) else 0
