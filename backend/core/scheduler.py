"""
core/scheduler.py

A dumb, durable timer service: "deliver this at tick T". It knows nothing about what a
timer means -- the owner that registered the handler does
(docs/distributed_architecture_plan.md: "the scheduler is infrastructure and stays dumb").

    register(owner, fn)                    fn(world, entry) is called when a timer owned by
                                           `owner` fires ("owner" may be a prefix: a timer
                                           owned by "character:42" goes to the handler
                                           registered for "character")
    register_recurring(owner, fn, every, offset=0)
                                           a job that fires every `every` sim SECONDS (anchored
                                           to multiples of `every`, never drifting)
    register_daily(owner, fn, at=0)        a job that fires when the clock reads `at` seconds
                                           past midnight (core/clock.py: 6 * HOUR = 06:00)
    register_hourly(owner, fn, at=0)       ... `at` seconds past every hour
    schedule_at(world, owner, key, ts, payload=None, every=None)
                                           deliver at sim timestamp `ts` (world["sim_time"])
    schedule_in(world, owner, key, seconds, ...)
                                           deliver `seconds` of sim time from now
    schedule(world, owner, key, at, ...)   the same, given a TICK (kept for old callers: the
                                           tick is turned into the timestamp it will be)
    cancel(world, owner, key)
    fire_due(world)                        run everything due, oldest first
    install(world)                         make sure every registered recurring job has its
                                           timer (idempotent; call every tick, it's O(jobs))

Timers live on the world (`world["timers"]`, kept sorted by due TIME) so they persist with it
and survive a restart. (owner, key) is unique: scheduling again replaces the old timer, which
makes "re-arm" safe and idempotent. Time is the sim clock's timestamp (core/clock.py::now_ts),
and every duration is sim seconds written with clock units (5 * MINUTE, DAY) -- never a tick
count. A timer saved by an older version (due at a tick) is converted the first time it is seen.

A handler may schedule more timers, including its own next one; one raising an exception is
logged and does not stop the rest. A recurring timer that fell far behind (the sim was
paused, a restart) fires once and re-anchors, not once per missed period.
"""

import bisect
import traceback

from core import tick_profile
from core.clock import now_ts, next_time_of_day, next_minute_of_hour, HOUR, DAY

_handlers = {}       # owner (or owner prefix) -> fn(world, entry)
_recurring = {}      # owner -> ("every", seconds, offset) | ("daily", at, 0) | ("hourly", at, 0)
_recurring_sig = 0   # changes whenever the set of recurring jobs does (makes install() O(1))

MAX_FIRES_PER_CALL = 500


def register(owner, fn):
    _handlers[owner] = fn


def _register(owner, fn, spec):
    global _recurring_sig
    _handlers[owner] = fn
    _recurring[owner] = spec
    _recurring_sig = hash(tuple(sorted(_recurring.items())))


def register_recurring(owner, fn, every, offset=0):
    """Every `every` sim seconds (anchored to multiples of it, plus `offset`)."""
    _register(owner, fn, ("every", int(every), int(offset)))


def register_daily(owner, fn, at=0):
    """Once a day, when the clock reads `at` seconds past midnight."""
    _register(owner, fn, ("daily", int(at) % DAY, 0))


def register_hourly(owner, fn, at=0):
    """Once an hour, `at` seconds past the hour."""
    _register(owner, fn, ("hourly", int(at) % HOUR, 0))


def _timers(world):
    timers = world.setdefault("timers", [])
    if timers and ("due" not in timers[0] or "due" not in timers[-1]):
        _migrate(world, timers)             # saved before timers were due at a timestamp (all at once, so first/last tells)
    return timers


def _migrate(world, timers):
    """Timers from before timestamps: due at a tick -> due at the timestamp that tick will be."""
    now, tick = now_ts(world), world.get("tick", 0)
    for t in timers:
        if "due" not in t:
            t["due"] = now + (t.get("at", tick) - tick)
    timers.sort(key=lambda t: (t["due"], t["seq"]))


def _remove(world, owner, key):
    timers = _timers(world)
    for i, t in enumerate(timers):
        if t["owner"] == owner and t["key"] == key:
            del timers[i]
            return True
    return False


def schedule_at(world, owner, key, ts, payload=None, every=None, _spec=None):
    """Deliver (owner, key) at sim timestamp `ts`. Replaces an existing timer with the same identity."""
    _remove(world, owner, key)
    seq = world.get("_timer_seq", 0) + 1
    world["_timer_seq"] = seq
    now = now_ts(world)
    entry = {"due": float(ts), "at": world.get("tick", 0) + int(round(ts - now)), "seq": seq, "owner": owner, "key": key,
             "payload": payload or {}}
    if every:
        entry["every"] = int(every)
    if _spec:
        entry["spec"] = list(_spec)
    timers = _timers(world)
    bisect.insort(timers, entry, key=lambda t: (t["due"], t["seq"]))
    return entry


def schedule_in(world, owner, key, seconds, payload=None, every=None):
    """Deliver (owner, key) `seconds` of sim time from now."""
    return schedule_at(world, owner, key, now_ts(world) + max(0, int(seconds)), payload, every)


def schedule(world, owner, key, at, payload=None, every=None):
    """Deliver (owner, key) at TICK `at` -- for callers that still keep ticks; prefer schedule_at/schedule_in."""
    return schedule_at(world, owner, key, now_ts(world) + (int(at) - world.get("tick", 0)), payload, every)


def cancel(world, owner, key):
    return _remove(world, owner, key)


def cancel_owner(world, owner):
    """Drop every timer an owner has (e.g. when a character is removed)."""
    timers = _timers(world)
    before = len(timers)
    world["timers"] = [t for t in timers if t["owner"] != owner]
    return before - len(world["timers"])


def pending(world, owner=None):
    return [t for t in _timers(world) if owner is None or t["owner"] == owner]


def next_due(world):
    timers = _timers(world)
    return timers[0]["due"] if timers else None


def next_due_tick(world):
    """The tick the next timer will fire on (for display and old callers)."""
    due = next_due(world)
    return None if due is None else world.get("tick", 0) + int(round(due - now_ts(world)))


def _handler_for(owner):
    fn = _handlers.get(owner)
    if fn:
        return fn
    prefix = owner.split(":", 1)[0]
    return _handlers.get(prefix)


def _next_for(world, entry, now):
    """When a repeating timer fires next. A clock-anchored one is due at the clock time again; an interval one at the next
    multiple of its period (a timer that fell far behind -- paused, restarted -- fires once and re-anchors)."""
    spec = entry.get("spec")
    if spec and spec[0] == "daily":
        return next_time_of_day(world, spec[1])
    if spec and spec[0] == "hourly":
        return next_minute_of_hour(world, spec[1])
    every = entry["every"]
    nxt = entry["due"] + every
    if nxt <= now:
        nxt = entry["due"] + every * ((now - entry["due"]) // every + 1)
    return nxt


def fire_due(world):
    """Run every timer whose time has come. Returns how many fired."""
    timers = _timers(world)
    now = now_ts(world)
    fired = 0
    while timers and timers[0]["due"] <= now and fired < MAX_FIRES_PER_CALL:
        entry = timers.pop(0)
        if entry.get("every") or entry.get("spec"):
            schedule_at(world, entry["owner"], entry["key"], _next_for(world, entry, now), entry.get("payload"),
                        entry.get("every"), entry.get("spec"))
        handler = _handler_for(entry["owner"])
        fired += 1
        if handler is None:
            continue
        tick_profile.mark(f"timer:{entry['owner'].split(':', 1)[0]}")
        try:
            handler(world, entry)
        except Exception:
            print(f"[scheduler] handler for {entry['owner']}/{entry['key']} failed:")
            traceback.print_exc()
    if fired:
        tick_profile.mark("timer:done")
    return fired


def install(world):
    """Ensure each registered recurring job has a timer (and that an old interval timer of a job that is now clock-anchored
    is replaced)."""
    if not _recurring:
        return
    if world.get("_sched_sig") == _recurring_sig and len(_timers(world)) >= len(_recurring):
        return                       # nothing registered since last time and nothing was wiped
    world["_sched_sig"] = _recurring_sig
    have = {(t["owner"], t["key"]): t for t in _timers(world)}
    now = now_ts(world)
    for owner, (kind, value, offset) in _recurring.items():
        old = have.get((owner, "recurring"))
        if kind == "every":
            if old and old.get("every") == value and not old.get("spec"):
                continue
            schedule_at(world, owner, "recurring", now + ((offset - now) % value), None, value)
        else:
            if old and old.get("spec") == [kind, value, 0]:
                continue
            due = next_time_of_day(world, value) if kind == "daily" else next_minute_of_hour(world, value)
            schedule_at(world, owner, "recurring", due, None, None, (kind, value, 0))
