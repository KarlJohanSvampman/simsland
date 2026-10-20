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
                                           a job that fires every `every` ticks (anchored to
                                           multiples of `every`, never drifting)
    schedule(world, owner, key, at, payload=None, every=None)
    schedule_in(world, owner, key, delay, ...)
    cancel(world, owner, key)
    fire_due(world)                        run everything due, oldest first
    install(world)                         make sure every registered recurring job has its
                                           timer (idempotent; call every tick, it's O(jobs))

Timers live on the world (`world["timers"]`, kept sorted by due tick) so they persist with it
and survive a restart. (owner, key) is unique: scheduling again replaces the old timer, which
makes "re-arm" safe and idempotent. Time is in sim ticks, the unit every duration in the code
already uses.

A handler may schedule more timers, including its own next one; one raising an exception is
logged and does not stop the rest. A recurring timer that fell far behind (the sim was
paused, a restart) fires once and re-anchors, not once per missed period.
"""

import bisect
import traceback

from core import tick_profile

_handlers = {}       # owner (or owner prefix) -> fn(world, entry)
_recurring = {}      # owner -> (every, offset)
_recurring_sig = 0   # changes whenever the set of recurring jobs does (makes install() O(1))

MAX_FIRES_PER_CALL = 500


def register(owner, fn):
    _handlers[owner] = fn


def register_recurring(owner, fn, every, offset=0):
    global _recurring_sig
    _handlers[owner] = fn
    _recurring[owner] = (int(every), int(offset))
    _recurring_sig = hash(tuple(sorted(_recurring.items())))


def _timers(world):
    return world.setdefault("timers", [])


def _remove(world, owner, key):
    timers = _timers(world)
    for i, t in enumerate(timers):
        if t["owner"] == owner and t["key"] == key:
            del timers[i]
            return True
    return False


def schedule(world, owner, key, at, payload=None, every=None):
    """Deliver (owner, key) at tick `at`. Replaces an existing timer with the same identity."""
    _remove(world, owner, key)
    seq = world.get("_timer_seq", 0) + 1
    world["_timer_seq"] = seq
    entry = {"at": int(at), "seq": seq, "owner": owner, "key": key, "payload": payload or {}}
    if every:
        entry["every"] = int(every)
    timers = _timers(world)
    bisect.insort(timers, entry, key=lambda t: (t["at"], t["seq"]))
    return entry


def schedule_in(world, owner, key, delay, payload=None, every=None):
    return schedule(world, owner, key, world.get("tick", 0) + max(0, int(delay)), payload, every)


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


def next_due_tick(world):
    timers = _timers(world)
    return timers[0]["at"] if timers else None


def _handler_for(owner):
    fn = _handlers.get(owner)
    if fn:
        return fn
    prefix = owner.split(":", 1)[0]
    return _handlers.get(prefix)


def fire_due(world):
    """Run every timer whose time has come. Returns how many fired."""
    timers = _timers(world)
    now = world.get("tick", 0)
    fired = 0
    while timers and timers[0]["at"] <= now and fired < MAX_FIRES_PER_CALL:
        entry = timers.pop(0)
        every = entry.get("every")
        if every:
            nxt = entry["at"] + every
            if nxt <= now:                      # fell behind: re-anchor instead of replaying
                nxt = entry["at"] + every * ((now - entry["at"]) // every + 1)
            schedule(world, entry["owner"], entry["key"], nxt, entry.get("payload"), every)
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
    """Ensure each registered recurring job has a timer."""
    if not _recurring:
        return
    if world.get("_sched_sig") == _recurring_sig and len(_timers(world)) >= len(_recurring):
        return                       # nothing registered since last time and nothing was wiped
    world["_sched_sig"] = _recurring_sig
    have = {(t["owner"], t["key"]) for t in _timers(world)}
    now = world.get("tick", 0)
    for owner, (every, offset) in _recurring.items():
        if (owner, "recurring") in have:
            continue
        nxt = now + ((offset - now) % every)
        schedule(world, owner, "recurring", nxt, None, every)
