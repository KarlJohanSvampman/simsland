"""
core/lazy.py -- continuous quantities as lazy values of sim time (docs/distributed_architecture_plan.md, principle 4).

A value that changes at a steady rate (a battery draining, alcohol wearing off, a baby getting hungry) is not stepped
every tick. It is stored with the sim time it was last brought up to date, and brought up to date when it is read, when
it is written, and at the moment it will cross a threshold that matters (a timer: brain/agent_wake.py for a
character). The rates are written per TICK (as they always were) and integrated over elapsed ticks, so at the default
one tick per second nothing changes.

    elapsed_ticks(holder, key, world)   ticks since holder's stamp `key` (0 the first time); stamps it now
    time_until_below(parts, threshold)  seconds until a sum of linearly decaying parts [(value, rate per tick)] falls
                                        under `threshold` (each part stops at 0), or None if it never will
"""

from core.tick_schedule import TICK_RATE_SECONDS


def elapsed_ticks(holder, key, world):
    from core.clock import now_ts
    stamps = holder.setdefault("_lazy_ts", {})
    now = now_ts(world)
    last = stamps.get(key)
    stamps[key] = now
    if last is None or now <= last:
        return 0.0
    return (now - last) / TICK_RATE_SECONDS


def decayed(value, rate_per_tick, ticks, floor=0.0):
    return max(floor, value - rate_per_tick * ticks)


def time_until_below(parts, threshold):
    """Seconds until sum(max(0, v - r*t)) < threshold, for decaying parts [(v, r)]; None if never (or already)."""
    parts = [(v, r) for v, r in parts if v > 0]
    total = sum(v for v, _ in parts)
    if total < threshold:
        return None
    t = 0.0
    while parts:
        rate = sum(r for _, r in parts if r > 0)
        if rate <= 0:
            return None
        # the next part to run out
        next_out = min((v / r for v, r in parts if r > 0), default=None)
        need = (total - threshold) / rate
        if next_out is None or need < next_out:
            return (t + need) * TICK_RATE_SECONDS + 1e-6
        t += next_out
        total -= rate * next_out
        parts = [(v - r * next_out, r) for v, r in parts if v - r * next_out > 1e-12]
    return None
