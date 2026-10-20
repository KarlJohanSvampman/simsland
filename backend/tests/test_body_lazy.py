"""
Lazy needs: the integrate-on-demand body (systems/body_lazy.py) tracks the old per-tick
update, and costs (almost) nothing between wakes.

Scenario over ~5.5 sim hours with the same actions applied to both characters: awake,
a meal, a stimulant window, a long sleep, a spell off-grid, a shower, a toilet visit.
OLD: update_body_needs + generate_body_intentions every tick.
NEW: scheduler timers + tick_check (the O(1) per-tick hook).

Run inside the backend container:   python tests/test_body_lazy.py
"""

import copy
import sys
import time
from datetime import datetime

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401  (registers the body timer handler)
from core import scheduler, event_bus
from db import load_world
from systems import body as B
from systems import body_lazy as L
from systems.body_intentions import generate_body_intentions

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


live = load_world("default")
proto = next(c for c in live["characters"].values() if not c.get("is_workplace_npc"))
base = copy.deepcopy(proto)
base["active_intentions"] = []
base.pop("_body_lazy", None)
base["activity"] = None
base["off_grid"] = False
base["travel_state"] = None
B.ensure_body(base)
bd = base["body"]
bd.update({"hunger": 20.0, "hydration": 80.0, "bladder": 10.0, "bowels": 10.0, "fatigue": 20.0, "energy": 90.0,
           "hygiene": 70.0, "odor": 0.0, "mouth_hygiene": 70.0, "sleep_debt": 10.0, "hours_awake": 4.0,
           "recent_intake": 0.0, "stomach_discomfort": 0.0})
T0 = datetime(2026, 10, 20, 12, 0, 0).timestamp()
bd["_wake_sim_time"] = T0 - 4 * 3600
cal0 = {"year": 2026, "month": 10, "day": 20, "hour": 12}


def make_world(c):
    return {"tick": 0, "sim_time": T0, "calendar": dict(cal0), "characters": {c["id"]: c}, "timers": []}


def set_time(w, t):
    w["tick"] = t
    w["sim_time"] = T0 + t
    w["calendar"]["hour"] = (12 + t // 3600) % 24       # day stays fixed: no midnight settlement


old, new = copy.deepcopy(base), copy.deepcopy(base)
wo, wn = make_world(old), make_world(new)

# (tick, action) applied identically to both
SLEEP_FROM, SLEEP_TO = 6000, 13000
OFFGRID_FROM, OFFGRID_TO = 16000, 17500


def apply(c, w, t):
    if t == 1500:
        B.on_eat_complete(c, 0.7)
    if t == 3000:
        c["body"]["_stimulant_until_tick"] = 3000 + 1800
    if t == SLEEP_FROM:
        c["activity"] = {"type": "sleep"}
    if t == SLEEP_TO:
        c["activity"] = None
        B.on_sleep_complete(c, (SLEEP_TO - SLEEP_FROM) / 60, world=w)
    if t == OFFGRID_FROM:
        c["off_grid"] = True
    if t == OFFGRID_TO:
        c["off_grid"] = False
    if t == 18500:
        B.on_shower_complete(c)
    if t == 19000:
        B.on_toilet_complete(c)


def sig(c):
    return tuple(sorted((i["type"], i["priority"], str(i["reason"])[:24]) for i in c["active_intentions"]))


N = 20000
timeline_old, timeline_new = [], []
last_o = last_n = None
t_old = t_new = 0.0
ticks_new_work = 0

import random
random.seed(7)
state = random.getstate()

for t in range(1, N + 1):
    set_time(wo, t)
    set_time(wn, t)
    random.setstate(state)                   # on_toilet_complete is jittered: same draw for both
    apply(old, wo, t)
    state_after_old = random.getstate()
    random.setstate(state)
    apply(new, wn, t)
    state = state_after_old

    s = time.perf_counter()
    if not old["off_grid"]:                  # the old loop skipped frozen characters entirely
        B.update_body_needs(old, world=wo)
        generate_body_intentions(old, wo)
    t_old += time.perf_counter() - s
    so = sig(old)
    if so != last_o:
        timeline_old.append((t, so)); last_o = so

    s = time.perf_counter()
    scheduler.fire_due(wn)
    L.tick_check(new, wn)
    t_new += time.perf_counter() - s
    sn = sig(new)
    if sn != last_n:
        timeline_new.append((t, sn)); last_n = sn

    if t in (1000, 2999, 5990, 9000, 12999, 15990, 17400, 18400, 19990):
        L.sync(new, wn)
        keys = ("hunger", "hydration", "bladder", "bowels", "fatigue", "energy", "hygiene", "odor", "mouth_hygiene", "sleep_debt", "hours_awake")
        worst = max(abs(old["body"][k] - new["body"][k]) for k in keys)
        worst_key = max(keys, key=lambda k: abs(old["body"][k] - new["body"][k]))
        check(f"tick {t}: every need within 1.5 points of the per-tick result", worst < 1.5,
              f"{worst_key}: old {old['body'][worst_key]:.2f} new {new['body'][worst_key]:.2f}")

print(f"   per-tick body+intentions: {t_old * 1000:.0f} ms over {N} ticks;  lazy (timers + O(1) check): {t_new * 1000:.0f} ms")
check("lazy path is much cheaper than the per-tick path", t_new < t_old * 0.5, f"{t_new:.3f}s vs {t_old:.3f}s")

# the same intentions appear, in the same order, at nearly the same time
types_old = [s for _, s in timeline_old]
types_new = [s for _, s in timeline_new]
check("the same sequence of body-driven intention sets", types_old == types_new,
      f"old {len(types_old)} changes, new {len(types_new)}\n old: {[ (t, [x[0] for x in s]) for t, s in timeline_old]}\n new: {[ (t, [x[0] for x in s]) for t, s in timeline_new]}")
lat = [tn - to for (to, _), (tn, _) in zip(timeline_old, timeline_new)]
print("   old:", [(t, [i[0] for i in s]) for t, s in timeline_old])
print("   new:", [(t, [i[0] for i in s]) for t, s in timeline_new])
print("   latency of each intention change (ticks late):", lat)
# A need moves ~0.01 points per tick, so a 0.2-point integration difference is ~20 ticks of
# lateness at a threshold crossing; touch/regime changes (meal, shower, sleep start) are exact.
check("each change lands within half a sim-minute of the per-tick time", all(-1 <= l <= 40 for l in lat), str(lat))

# a frozen (off-grid) stretch doesn't age the body
frozen_check = copy.deepcopy(base)
B.ensure_body(frozen_check)
wf = make_world(frozen_check)
set_time(wf, 1); L.tick_check(frozen_check, wf)
hunger0 = frozen_check["body"]["hunger"]
frozen_check["off_grid"] = True
for t in range(2, 3000):
    set_time(wf, t); scheduler.fire_due(wf); L.tick_check(frozen_check, wf)
frozen_check["off_grid"] = False
set_time(wf, 3000); L.tick_check(frozen_check, wf); L.sync(frozen_check, wf)
check("3000 off-grid ticks leave hunger where it was", abs(frozen_check["body"]["hunger"] - hunger0) < 0.2,
      f"{hunger0:.2f} -> {frozen_check['body']['hunger']:.2f}")

# a quiet character wakes rarely: count timer fires over 2 hours awake and idle
quiet = copy.deepcopy(base); B.ensure_body(quiet)
quiet["body"].update({"hunger": 5.0, "hydration": 95.0, "fatigue": 5.0, "energy": 95.0, "hygiene": 95.0, "mouth_hygiene": 95.0, "sleep_debt": 0, "bladder": 5.0, "bowels": 2.0, "hours_awake": 1.0})
quiet["body"]["_wake_sim_time"] = T0 - 3600
wq = make_world(quiet)
fires = []
orig = scheduler._handlers["body"]
scheduler._handlers["body"] = lambda w, e: (fires.append(w["tick"]), orig(w, e))[1]
for t in range(1, 7200):
    set_time(wq, t); scheduler.fire_due(wq); L.tick_check(quiet, wq)
scheduler._handlers["body"] = orig
print(f"   quiet character, 7200 ticks: {len(fires)} body wakes (per-tick would be 7200)")
check("an idle, comfortable character wakes at most every ~120 ticks", len(fires) <= 7200 // 100, str(len(fires)))

# probe emits no events and doesn't touch the real body
events = []
event_bus.clear(); event_bus.subscribe("health_threshold_crossed", lambda d, w: events.append(d))
probe_c = copy.deepcopy(base); B.ensure_body(probe_c); probe_c["body"]["hunger"] = 99.5
wp = make_world(probe_c)
snap = copy.deepcopy(probe_c["body"])
L.ticks_until_change(probe_c, wp)
event_bus.flush(wp)
check("the forward probe doesn't change the real body or emit health events", probe_c["body"] == snap and not events, str(events))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
