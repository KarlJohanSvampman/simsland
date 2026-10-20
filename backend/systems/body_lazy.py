"""
systems/body_lazy.py

The needs (hunger, hydration, bladder, bowels, fatigue, energy, hygiene, odor, mouth
hygiene, sleep debt, ...) as lazy values instead of a per-character per-tick update
(docs/distributed_architecture_plan.md: "continuous quantities are lazy").

Every rate in systems/body.py::update_body_needs is per tick and scaled by `dt`, so the
state at any later moment is obtained by integrating the interval since the last sync in
chunks of BODY_STEP ticks, under the regime that held during it (asleep / awake, frozen
off-grid or on a trip, stimulant window). Nothing runs per tick any more except an O(1)
check for a regime change.

  sync(c, world)        catch the body up to now
  tick_check(c, world)  the O(1) per-tick hook (brain/agent_loop.py::update_internal_state):
                        regime flipped (sleep started, went off-grid, stimulant ended) -> sync
                        under the OLD regime first; body touched by a meal/shower/toilet ->
                        re-evaluate; staler than BODY_FRESH_TICKS -> sync
  schedule_next(...)    sets the character's next wake: by *forward probe*. A throwaway copy
                        of the body is advanced chunk by chunk with the real update function
                        and the real intention generator, and the first chunk in which the
                        body-driven intentions would change is the wake time (capped at
                        BODY_MAX_SLEEP_TICKS, because other systems also write to the body:
                        weather exposure, illness, ...). No threshold is hard-coded here.
  on_body_timer(...)    the scheduler handler: sync, regenerate the intentions, reschedule

The timer is what lets a character with nothing happening cost nothing between wakes.
"""

import copy

from core import scheduler

BODY_STEP = 20                 # integration chunk (ticks)
BODY_FRESH_TICKS = 30          # values read by per-tick code are never staler than this
BODY_MAX_SLEEP_TICKS = 120     # longest gap between wakes (other systems write the body too)
BODY_MIN_SLEEP_TICKS = 2
RESCHEDULE_GRACE_TICKS = 10    # a timer this overdue is assumed lost (reset, restart)


def _state(c):
    return c.setdefault("_body_lazy", {})


def regime(c, world):
    """(asleep, frozen, stimulant) -- the things that change how fast the needs move."""
    from systems.travel import TRAVEL_FROZEN_STATES
    b = c.get("body") or {}
    asleep = (c.get("activity") or {}).get("type") == "sleep"
    frozen = bool(c.get("off_grid")) or c.get("travel_state") in TRAVEL_FROZEN_STATES
    stimulant = world.get("tick", 0) < b.get("_stimulant_until_tick", 0)
    return [asleep, frozen, stimulant]


def sync(c, world, under=None):
    """Integrate the body from the last sync to now under `under` (default: the regime
    recorded at the last check). While frozen (off-grid / on a trip) time passes but the
    needs don't move -- the same as the old per-tick loop, which skipped frozen characters."""
    from systems.body import ensure_body, update_body_needs
    ensure_body(c)
    st = _state(c)
    tick = world.get("tick", 0)
    last = st.get("synced")
    if last is None:
        st["synced"] = tick
        return 0
    dt = tick - last
    if dt <= 0:
        return 0
    reg = under if under is not None else st.get("regime") or regime(c, world)
    st["synced"] = tick
    if reg[1]:                                   # frozen: nothing accrues
        return 0
    remaining = dt
    while remaining > 0:
        step = min(BODY_STEP, remaining)
        update_body_needs(c, dt=step, world=world, asleep=bool(reg[0]), stimulant=bool(reg[2]))
        remaining -= step
    return dt


def regenerate_intentions(c, world):
    from systems.body_intentions import generate_body_intentions
    generate_body_intentions(c, world)


# ── forward probe ─────────────────────────────────────────────────────────────

def _shadow(c, world):
    b = copy.deepcopy(c.get("body") or {})
    cal = dict(world.get("calendar") or {})
    day_key = f"{cal.get('year')}-{cal.get('month')}-{cal.get('day')}"
    b["_nutrients_reset_day"] = day_key          # the probe never crosses midnight
    shadow = {
        "id": c.get("id"), "body": b, "traits": list(c.get("traits") or []),
        "physical_traits": list(c.get("physical_traits") or []), "stress": c.get("stress", 0),
        "stamina": c.get("stamina", 1.0), "age_group": c.get("age_group"),
        "active_intentions": [], "_health_events_fired": list(c.get("_health_events_fired") or []),
    }
    shadow_world = {"tick": world.get("tick", 0), "sim_time": world.get("sim_time", 0.0), "calendar": cal}
    return shadow, shadow_world


def _signature(shadow, shadow_world):
    from systems.body_intentions import generate_body_intentions
    shadow["active_intentions"] = []
    generate_body_intentions(shadow, shadow_world)
    return tuple(sorted((i.get("type"), i.get("priority"), str(i.get("reason"))[:24])
                        for i in shadow["active_intentions"]))


def ticks_until_change(c, world, reg=None, horizon=BODY_MAX_SLEEP_TICKS, step=BODY_STEP):
    """How many ticks until the body-driven intentions would differ from what they are now,
    found by running the real update + generator forward on a copy: chunk by chunk, then a
    bisection inside the chunk where the change happened, so the wake lands within a tick or
    two of the real moment."""
    from systems.body import update_body_needs
    from core.tick_schedule import TICK_RATE_SECONDS
    reg = reg or regime(c, world)
    if reg[1]:                                   # frozen: nothing moves until the regime changes
        return horizon
    shadow, sw = _shadow(c, world)
    base = _signature(shadow, sw)

    def advance(sh, w, dt):
        update_body_needs(sh, dt=dt, world=w, asleep=bool(reg[0]), stimulant=bool(reg[2]), check_health=False)
        w["tick"] += dt
        w["sim_time"] += dt * TICK_RATE_SECONDS

    elapsed = 0
    while elapsed < horizon:
        before = (copy.deepcopy(shadow), dict(sw, calendar=dict(sw["calendar"])))
        advance(shadow, sw, step)
        elapsed += step
        if _signature(shadow, sw) != base:
            lo, hi = elapsed - step, elapsed             # changed somewhere in (lo, hi]
            while hi - lo > 2:
                mid = (lo + hi) // 2
                sh, w = copy.deepcopy(before[0]), dict(before[1], calendar=dict(before[1]["calendar"]))
                advance(sh, w, mid - lo)
                if _signature(sh, w) != base:
                    hi = mid
                else:
                    lo = mid
            return hi
    return horizon


def schedule_next(c, world):
    st = _state(c)
    tick = world.get("tick", 0)
    reg = st.get("regime") or regime(c, world)
    delay = max(BODY_MIN_SLEEP_TICKS, min(BODY_MAX_SLEEP_TICKS, ticks_until_change(c, world, reg)))
    until = (c.get("body") or {}).get("_stimulant_until_tick", 0)
    if until and until > tick:                   # the stimulant window ends at a known tick
        delay = max(1, min(delay, until - tick))
    st["next"] = tick + delay
    scheduler.schedule(world, f"body:{c['id']}", "sync", st["next"])


# ── driving it ─────────────────────────────────────────────────────────────────

def tick_check(c, world):
    """Per-tick, per-character, O(1) unless something actually changed."""
    from systems.body import ensure_body
    ensure_body(c)
    st = _state(c)
    tick = world.get("tick", 0)
    reg = regime(c, world)
    if st.get("synced") is None or st.get("regime") is None:
        st["synced"], st["regime"] = tick, reg
        regenerate_intentions(c, world)
        schedule_next(c, world)
        return
    force = bool(st.pop("touched", False))
    if reg != st["regime"]:
        sync(c, world, under=st["regime"])       # the interval that just ended ran under the old regime
        st["regime"] = reg
        force = True
    elif tick - st["synced"] >= BODY_FRESH_TICKS:
        sync(c, world)                           # keep what per-tick readers see fresh
    if force:
        sync(c, world)
        regenerate_intentions(c, world)
        schedule_next(c, world)
    elif st.get("next") is None or tick > st["next"] + RESCHEDULE_GRACE_TICKS:
        schedule_next(c, world)                  # timer lost (reset, restart): re-arm


def on_body_timer(world, entry):
    cid = entry["owner"].split(":", 1)[1]
    c = world.get("characters", {}).get(cid)
    if not c or c.get("alive") is False:
        return
    st = _state(c)
    if st.get("synced") is None:
        return                                   # tick_check initialises it
    if regime(c, world) != st.get("regime"):
        tick_check(c, world)                     # a regime flip is handled there, under the old regime
        return
    sync(c, world)
    regenerate_intentions(c, world)
    schedule_next(c, world)


scheduler.register("body", on_body_timer)
