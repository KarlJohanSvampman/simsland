"""
brain/agent_wake.py -- when a character's update_agent() runs (docs/distributed_architecture_plan.md, step 3: "a
character actor wakes on events addressed to it and on its own timers").

update_agent() used to run for every character on every step. Most of those runs change nothing: the values that do
change with time are lazy (body, memories, habits, desires, mood -- functions of sim time, the same however often they
are refreshed). So a character's update runs only when

    * something woke it                    wake(c, world, reason)       -- an event about them, a decision coming
                                                                           back, being spoken to (cognition's
                                                                           wake_character() calls this too)
    * one of its own timers is due         wake_at(c, world, ts, reason) -- a check inside update_agent() that knows
                                                                           when it next has something to do (an
                                                                           alarm, a shift starting, a deadline)
    * its decision cycle is due            cognition's next_think_tick
    * the heartbeat ran out                HEARTBEAT_SECONDS since its last update: a bounded fallback for anything
                                           that changes without telling anyone

AGENT_GATING (environment, or set_mode()):
    on       (default) only due characters run
    off      every character every step (the old behaviour)
    shadow   every character every step, but each step the gate WOULD have skipped is checked: if the run changed
             real state (not just lazy values catching up), it is recorded as a miss -- which keys, in which state.
             This is how each wake source was proven before the gate was turned on (misses() / tests/test_agent_wake.py).

State per character: c["_wake"] = {"at": ts the next own wake is due, "why": reason, "last": ts of the last update}.
"""

import os
from collections import Counter, deque

MODE = os.getenv("AGENT_GATING", "on").lower()
HEARTBEAT_SECONDS = float(os.getenv("AGENT_HEARTBEAT_SECONDS", "60"))
NEVER = float("inf")

IN_SKIPPABLE = False          # shadow mode: True while running a step the gate would have skipped
_stats = Counter()
_misses = deque(maxlen=500)
_miss_keys = Counter()


def set_mode(mode):
    global MODE
    MODE = mode


def _now(world):
    from core.clock import now_ts
    return now_ts(world)


def _rec(c):
    w = c.get("_wake")
    if not isinstance(w, dict):
        w = c["_wake"] = {"at": None, "why": None, "last": None}
    return w


def wake(c, world, reason="event"):
    """Due now (this step if the character has not been updated yet, else the next)."""
    wake_at(c, world, _now(world), reason)


def wake_now(c, reason="event"):
    """Due on the next look, for callers that have no world at hand (add_intention, ...)."""
    if c is None:
        return
    w = _rec(c)
    w["at"], w["why"] = 0.0, reason      # any time in the past is due (and, unlike -inf, it is valid JSON)
    _woken.add(c.get("id"))


def wake_at(c, world, ts, reason="timer"):
    """Due at sim time `ts` at the latest (an earlier wake already set stays)."""
    if c is None or ts is None:
        return
    w = _rec(c)
    if w["at"] is None or ts < w["at"]:
        w["at"], w["why"] = ts, reason
        _push(world, ts, c.get("id"))


# ── the due index (step 5a): who is due, without asking every character every step ──────────────────────────────────
# A heap of (time, character id) per world, pushed whenever a character's next wake moves earlier; stale entries
# (the character ran meanwhile, or its wake moved) are dropped when popped. Characters woken without a world at hand
# (wake_now) are collected in _woken. The movement loop's members (walking) are due every step.

import heapq

_heaps = {}              # id(world) -> heap of (ts, cid)
_woken = set()


def _push(world, ts, cid):
    if world is None or cid is None:
        _woken.add(cid)
        return
    heap = _heaps.get(id(world))
    if heap is not None:
        heapq.heappush(heap, (ts, cid))


def _build_index(world):
    """First use with this world (a load): everyone is looked at once, and their pending wakes are indexed."""
    heap = []
    for cid in dict.keys(world.get("characters") or {}):
        heap.append((float("-1"), cid))
    heapq.heapify(heap)
    _heaps[id(world)] = heap
    return heap


_pending = {}            # id(world) -> candidate ids popped from the index but not yet run


def _candidates(world):
    chars = world.get("characters") or {}
    heap = _heaps.get(id(world)) or _build_index(world)
    cand = _pending.setdefault(id(world), set())
    now = _now(world)
    while heap and heap[0][0] <= now:
        cand.add(heapq.heappop(heap)[1])
    if _woken:
        from core import partitions
        mine = {i for i in _woken if dict.__contains__(chars, i) and partitions.here(world, "characters", i)}
        cand |= mine
        _woken.difference_update(mine | {i for i in _woken if not dict.__contains__(chars, i)})
    return cand


def iter_due(world):
    """Yield (cid, c, why) for each character due this step, in the characters' own order -- re-checked after each one
    runs, so someone an earlier character wakes (spoken to, ...) runs in this same step when they come later in the
    order, exactly as the old sweep over everyone did; someone earlier in the order is left for the next step."""
    from core import active_loops
    chars = world.get("characters") or {}
    order = {cid: n for n, cid in enumerate(dict.keys(chars))}
    pos = -1
    while True:
        cand = _candidates(world)
        movers = set(active_loops.members(world, "movement"))
        nxt = None
        for cid in sorted((cand | movers), key=lambda i: order.get(i, 1 << 30)):
            n = order.get(cid)
            if n is None or not _here(world, cid):
                cand.discard(cid)                     # gone, or another partition's character (core/partitions.py)
                continue
            if n <= pos:
                continue
            c = dict.__getitem__(chars, cid)
            ok, why = due(c, world)
            if not ok:
                cand.discard(cid)
                continue
            nxt = (cid, c, why)
            break
        if nxt is None:
            return
        cand.discard(nxt[0])
        pos = order[nxt[0]]
        yield nxt


def _here(world, cid):
    from core import partitions
    return partitions.here(world, "characters", cid)


def reindex(world, cid):
    """A character's wake changed somewhere else (a patch from another partition): put it on this world's index."""
    c = dict.get(world.get("characters") or {}, cid)
    w = (c or {}).get("_wake") or {}
    if w.get("at") is not None:
        _push(world, w["at"], cid)


def due_set(world):
    """The characters due right now, in order (a snapshot: iter_due is what the step runs)."""
    chars = world.get("characters") or {}
    from core import active_loops
    cand = set(_candidates(world)) | set(active_loops.members(world, "movement"))
    out = []
    for cid in cand:
        if not dict.__contains__(chars, cid):
            continue
        c = dict.__getitem__(chars, cid)
        ok, why = due(c, world)
        if ok:
            out.append((cid, c, why))
    if len(out) > 1:
        order = {cid: n for n, cid in enumerate(dict.keys(chars))}
        out.sort(key=lambda t: order.get(t[0], 1 << 30))
    return out


def defer(c, world, reason="excluded"):
    """A due character the step does not run (incapacitated, a service worker...): its own periodic work still runs
    (core/flow.py PERCHAR -- the old sweeps covered them too), and it is looked at again later."""
    from core.flow import run_perchar
    run_perchar(c, world)                       # each job's own check says whether it concerns this character
    wake_at(c, world, _now(world) + HEARTBEAT_SECONDS, reason)


def due(c, world):
    """(True, why) if this character's update should run this step."""
    w = c.get("_wake")
    if not isinstance(w, dict) or w.get("last") is None:
        return True, "first"
    now = _now(world)
    if w.get("at") is not None and now >= w["at"]:
        return True, w.get("why") or "timer"
    if c.get("is_moving") or c.get("pushing_prop_id"):
        return True, "moving"                 # their room, guest status and arrival follow them step by step
    cog = c.get("cognition") or {}
    if not c.get("activity") and world.get("tick", 0) >= cog.get("next_think_tick", 0) and not cog.get("pending"):
        return True, "think"                  # free, and their decision cycle is due
    if now - w["last"] >= HEARTBEAT_SECONDS:
        return True, "heartbeat"
    return False, None


def begin_run(c, world):
    """Called just before the update runs: the wakes that brought it here are spent. (The checks inside re-arm what
    they still need while it runs -- which is why this is cleared before, not after.)"""
    w = _rec(c)
    w["at"], w["why"] = None, None


def note_run(c, world):
    """Called after the update ran: when it last ran; the activity under way sets its next wake by its own clock; the
    heartbeat, and -- free, with no decision pending -- the moment its decision cycle is due, are armed (the index finds
    them; due() would also find them by asking)."""
    now = _now(world)
    _rec(c)["last"] = now
    _arm_activity(c, world)
    wake_at(c, world, now + HEARTBEAT_SECONDS, "heartbeat")
    cog = c.get("cognition") or {}
    if not c.get("activity") and not cog.get("pending"):
        wake_at(c, world, at_tick(world, cog.get("next_think_tick", 0)), "think")


def wake_at_minute(c, world, minute_of_day, reason="clock"):
    """Due at the next moment the clock reads `minute_of_day` (0..1439), local sim time."""
    if minute_of_day is None:
        return
    cal = world.get("calendar") or {}
    now_min = cal.get("hour", 0) * 60 + cal.get("minute", 0)
    ahead = (int(minute_of_day) - now_min) % 1440 or 1440
    wake_at(c, world, _now(world) + ahead * 60 - cal.get("second", 0), reason)


def at_tick(world, tick):
    """The sim time a tick-stamped deadline falls at (the codebase still counts some in ticks)."""
    from core.tick_schedule import TICK_RATE_SECONDS
    return _now(world) + (tick - world.get("tick", 0)) * TICK_RATE_SECONDS


def _arm_activity(c, world):
    """An activity's own clock (systems/activities.py::execute_activity): the "using" phase ends at
    phase_started_tick + duration; every other phase (finishing, picking up, short waits) moves on within a step or a
    few, so it is looked at on the next step. Walking is due every step anyway (due())."""
    act = c.get("activity")
    if not act:
        return
    phase = act.get("phase", "using")
    if phase == "using" and act.get("duration") is not None and act.get("phase_started_tick") is not None:
        wake_at(c, world, at_tick(world, act["phase_started_tick"] + act["duration"]), "activity_clock")
    else:
        wake_at(c, world, at_tick(world, world.get("tick", 0) + 1), "activity_phase")


# ── per-tick chances, without running every tick ─────────────────────────────────────────────────────────────────────

def chance(c, world, key, p):
    """True on the step a per-tick chance `p` comes up, for as long as the caller's condition holds (call this only
    while it does; chance_off() when it stops). Instead of a roll on every step, the step it next comes up is drawn
    once -- geometrically, the same distribution -- and a wake is set for it, so the update need not run in between."""
    import math
    import random
    if p <= 0:
        return False
    tick = world.get("tick", 0)
    slots = c.setdefault("_chance", {})
    nxt = slots.get(key)
    if nxt is None:
        u = random.random()
        k = 1 if p >= 1 else 1 + int(math.log(1.0 - u) / math.log(1.0 - p))
        nxt = slots[key] = tick + k - 1
    if tick >= nxt:
        slots.pop(key, None)
        return True
    wake_at(c, world, at_tick(world, nxt), "chance:" + key)
    return False


def chance_off(c, key):
    (c.get("_chance") or {}).pop(key, None)


# ── events wake the characters they are about ────────────────────────────────────────────────────────────────────────
_ID_KEYS = ("character_id", "listener_id", "speaker_id", "observer_id", "target_id", "actor_id", "victim_id",
            "attacker_id", "witness_id", "ignorer_id", "subject_id", "other_id", "char_id", "person_id")


def _event_ids(data):
    out = []
    if not isinstance(data, dict):
        return out
    for k in _ID_KEYS:
        v = data.get(k)
        if isinstance(v, str):
            out.append(v)
    for k in ("character_ids", "participants", "ids"):
        for v in data.get(k) or ():
            if isinstance(v, str):
                out.append(v)
    return out


def _on_event(event_type, data, world):
    """A character wakes when an event about them happens: whatever a handler changed about them, their update sees it
    on the next step -- as it did when everyone ran every step."""
    if MODE == "off" or not isinstance(world, dict):
        return
    chars = world.get("characters") or {}
    for cid in _event_ids(data):
        c = chars.get(cid)
        if c is not None:
            wake(c, world, "event:" + event_type)


def wake_near(world, x, y, building_id=None, radius=24, reason="nearby"):
    """Wake whoever could notice something at (x, y): the same building, or outdoors within `radius` tiles."""
    for c in (world.get("characters") or {}).values():
        if c.get("is_workplace_npc"):
            continue
        b = c.get("_in_building", c.get("building_id"))
        if building_id and b == building_id:
            wake(c, world, reason)
        elif not building_id and not b and abs((c.get("x") or 0) - (x or 0)) + abs((c.get("y") or 0) - (y or 0)) <= radius:
            wake(c, world, reason)


def _on_incident(data, world):
    """An incident (a fire, a fight) wakes whoever is near it -- curiosity, alarm, helping."""
    if MODE == "off":
        return
    inc = next((i for i in world.get("incidents") or [] if i.get("id") == (data or {}).get("incident_id")), None)
    if inc:
        wake_near(world, inc.get("x"), inc.get("y"), inc.get("building_id"), reason="incident")


def _hourly(world, entry=None):
    """Top of the hour (a CLOCK job, so at the start of the step): everyone's update runs -- the hour-grained things
    (habit hours, daily plans and reminders, a day's first look at the bills) are seen at the boundary itself."""
    if MODE == "off":
        return
    for c in (world.get("characters") or {}).values():
        if not c.get("is_workplace_npc"):
            wake(c, world, "hour")


def install():
    from core import event_bus
    event_bus.after_dispatch(_on_event)
    event_bus.subscribe("incident_created", _on_incident)


install()


# ── shadow comparison ────────────────────────────────────────────────────────────────────────────────────────────────
# Keys whose change on an otherwise idle step is only a lazy value catching up with sim time, or this module's own
# bookkeeping. They are compared by what they really contain (which memories, which desires, which habits), not by
# their numbers.
_LAZY_STAMPS = {"_wake", "_habits_ts", "_desires_ts", "_emotion_seen_ts", "body", "_body_lazy", "emotion",
                "emotional_temperature", "_step",
                "_curiosity_last_check", "_curiosity_target",
                "stamina", "_chance",
                # outputs of the lazy body's sync (systems/body.py::update_body_needs writes them outside "body"):
                # they change when the body is brought up to date, at most BODY_MAX_SLEEP_TICKS late
                "stress", "weight_kg", "food_habits", "physical_health", "_health_events_fired"}   # only spaces the curiosity checks; a target present re-arms its own timer


def _real_view(c):
    from core.entity_versions import _digest
    out = {}
    for k, v in c.items():
        if k in _LAZY_STAMPS:
            continue
        if k == "memories":
            v = [m.get("id") for m in v or []]
        elif k == "persistent_desires":
            v = [{kk: vv for kk, vv in (d or {}).items() if kk not in ("frustration", "importance")} for d in v or []]
        elif k == "habits":
            v = sorted((v or {}).keys())
        elif k in _LAZY_FIELDS:
            v = {kk: vv for kk, vv in (v or {}).items() if kk not in _LAZY_FIELDS[k] and kk != "_lazy_ts"}
        elif k == "relationships":
            v = {oid: {kk: vv for kk, vv in (r or {}).items() if kk != "arousal_level"} for oid, r in (v or {}).items()}
        elif k == "inventory":                      # battery levels are lazy (systems/power.py); the rest of an item is not
            v = [dict(it, states={sk: sv for sk, sv in ((it or {}).get("states") or {}).items()
                                  if sk not in ("battery", "powered_on")}) for it in (v or [])]
        out[k] = _digest(v)
    return out


# Values inside these holders fall lazily (core/lazy.py): compared without them and their stamps. A real rise goes
# through a function that wakes the character (add_anger_pressure, consume_alcohol, apply_topic_blush, ...).
_LAZY_FIELDS = {
    "impulse_state": ("anger_pressure",),
    "intoxication_state": ("alcohol_level", "drug_level", "libido_boost"),
    "baby_needs": ("hunger", "sleep", "comfort", "stimulation"),
}
_LAZY_STAMPS.update({"_crush", "_intimacy", "_baby", "blush_score", "is_blushing", "_battery"})


def shadow_before(c):
    return _real_view(c)


def shadow_after(c, world, before, would_run, why):
    """Record a miss if the gate would have skipped this step but the update changed real state."""
    _stats["steps"] += 1
    if would_run:
        _stats["run:" + str(why)] += 1
        return
    _stats["skippable"] += 1
    after = _real_view(c)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    if not changed:
        return
    _stats["misses"] += 1
    for k in changed:
        _miss_keys[k] += 1
    act = (c.get("activity") or {}).get("type")
    _misses.append({"tick": world.get("tick"), "id": c.get("id"), "keys": changed, "activity": act,
                    "moving": bool(c.get("is_moving"))})


def stats():
    return dict(_stats)


def misses():
    return list(_misses)


def miss_keys():
    return dict(_miss_keys)


def reset_stats():
    _stats.clear()
    _misses.clear()
    _miss_keys.clear()
