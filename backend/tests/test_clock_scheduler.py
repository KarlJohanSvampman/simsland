"""
Step 2 of the event-driven migration: the sim clock and the scheduler.

Run inside the backend container:   python tests/test_clock_scheduler.py
"""

import copy
import json
import sys
from datetime import datetime

import os
os.environ.setdefault("COGNITION_MODE", "local")     # never reach a live cognition worker
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from core import clock, scheduler, event_bus

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# ── scheduler ─────────────────────────────────────────────────────────────────
saved_handlers, saved_recurring = dict(scheduler._handlers), dict(scheduler._recurring)
scheduler._handlers.clear(); scheduler._recurring.clear()
log = []
scheduler.register("char", lambda w, e: log.append(("char", e["owner"], e["key"], w["tick"], e["payload"])))
scheduler.register("boom", lambda w, e: (_ for _ in ()).throw(RuntimeError("bug")))

w = {"tick": 100}
scheduler.schedule(w, "char:7", "a", 130, {"n": 1})
scheduler.schedule(w, "char:7", "b", 110)
scheduler.schedule_in(w, "char:9", "c", 20)
check("timers are kept in due order", [t["key"] for t in w["timers"]] == ["b", "c", "a"], str(w["timers"]))
scheduler.schedule(w, "char:7", "a", 125, {"n": 2})
check("scheduling the same (owner, key) replaces it", sum(1 for t in w["timers"] if t["key"] == "a") == 1 and w["timers"][-1]["at"] == 125)
check("cancel removes it", scheduler.cancel(w, "char:9", "c") and not scheduler.cancel(w, "char:9", "c"))

w["tick"] = 109; check("nothing fires early", scheduler.fire_due(w) == 0 and not log)
w["tick"] = 110; check("fires at its tick, owner prefix routes to the handler", scheduler.fire_due(w) == 1 and log[-1][:3] == ("char", "char:7", "b"), str(log))
w["tick"] = 130; scheduler.fire_due(w)
check("payload is delivered and the replaced timer fired once", log[-1][4] == {"n": 2} and [l[2] for l in log] == ["b", "a"], str(log))
check("fired timers are gone", w["timers"] == [])

# durable across a JSON round trip (the world is persisted as JSON)
w2 = {"tick": 0}
scheduler.schedule(w2, "char:1", "later", 50, {"x": [1, 2]})
w3 = json.loads(json.dumps(w2)); w3["tick"] = 50; log.clear()
scheduler.fire_due(w3)
check("timers survive persistence", log and log[0][2] == "later" and log[0][4] == {"x": [1, 2]}, str(log))

# a failing handler doesn't stop the rest
w4 = {"tick": 10}
scheduler.schedule(w4, "boom:1", "x", 10); scheduler.schedule(w4, "char:1", "after", 10)
log.clear(); n = scheduler.fire_due(w4)
check("an exception in one handler is isolated", n == 2 and log and log[0][2] == "after")

# recurring: anchored to multiples, idempotent install, no drift, re-anchors after a gap
fires = []
scheduler.register_recurring("job", lambda w, e: fires.append(w["tick"]), every=60, offset=0)
w5 = {"tick": 1}
scheduler.install(w5); scheduler.install(w5)
check("install is idempotent", len(scheduler.pending(w5, "job")) == 1)
for t in range(1, 200):
    w5["tick"] = t; scheduler.install(w5); scheduler.fire_due(w5)
check("recurring job fires on multiples of its period", fires == [60, 120, 180], str(fires))
fires.clear(); w5["tick"] = 100000; scheduler.fire_due(w5)
check("a long gap fires once, not once per missed period", fires == [100000] and scheduler.next_due_tick(w5) == 100020, f"{fires} next={scheduler.next_due_tick(w5)}")
off = []
scheduler.register_recurring("job2", lambda w, e: off.append(w["tick"]), every=30, offset=5)
w6 = {"tick": 0}
for t in range(0, 100):
    w6["tick"] = t; scheduler.install(w6); scheduler.fire_due(w6)
check("offsets are honoured", off == [5, 35, 65, 95], str(off))
check("cancel_owner drops everything an owner has", (scheduler.schedule(w6, "char:3", "k1", 999), scheduler.schedule(w6, "char:3", "k2", 999), scheduler.cancel_owner(w6, "char:3"))[2] == 2)

scheduler._handlers.clear(); scheduler._recurring.clear()
scheduler._handlers.update(saved_handlers); scheduler._recurring.update(saved_recurring)

# ── clock ─────────────────────────────────────────────────────────────────────
import sim_loop

event_bus.clear()
got = []
for ev in ("time.hour", "time.day", "time.week", "time.month"):
    event_bus.subscribe(ev, lambda d, w, ev=ev: got.append((ev, d["stamp"])))

def run(start_dt, ticks, world=None):
    world = world or {"tick": 0}
    world["sim_time"] = start_dt.timestamp() - 1
    for i in range(ticks):
        world["tick"] += 1
        sim_loop.advance_calendar(world)
        clock.advance(world)
        if i == 0:                      # the very first tick stamps the current period; not a boundary
            event_bus.flush(world)
            got.clear()
    event_bus.flush(world)
    return world

# Sunday 2026-10-31 23:58:30 -> Monday 2026-11-02 is not a month start; use a real month start: Sat 2026-10-31 23:59:00 -> Sun 11-01 00:02
w = run(datetime(2026, 10, 31, 23, 59, 0), 240)
kinds = [k for k, _ in got]
check("crossing midnight into the 1st fires hour, day and month once each", kinds.count("time.hour") == 1 and kinds.count("time.day") == 1 and kinds.count("time.month") == 1 and kinds.count("time.week") == 0, str(got))
got.clear()
w = run(datetime(2026, 11, 1, 23, 59, 0), 240)    # Sunday night -> Monday 2 Nov
kinds = [k for k, _ in got]
check("crossing into Monday fires the week boundary once", kinds.count("time.week") == 1 and kinds.count("time.day") == 1 and kinds.count("time.month") == 0, str(got))
got.clear()
w2 = run(datetime(2026, 11, 3, 10, 0, 0), 7300)      # two hours of an ordinary Tuesday morning
check("an ordinary two hours fires hour boundaries only", set(k for k, _ in got) == {"time.hour"} and len(got) == 2, str(got))
got.clear()
w["tick"] += 0; clock.advance(w); event_bus.flush(w)
check("calling advance again in the same period fires nothing", got == [])

# ── the real tick with the real handlers ───────────────────────────────────────
from db import load_world
from core.definitions import load_definitions
import core.event_handlers  # noqa: F401  (registers the calendar handlers + recurring jobs)
import llm.llm_gate as _g
_g.run_llm_call = lambda coro, *a, **k: (coro.close(), None)[1]
from systems.schema_defaults import ensure_world_defaults
from core import tick_profile

base = copy.deepcopy(load_world("default")); base["definitions"] = load_definitions("default")
base.pop("timers", None)

# recurring jobs fire on schedule through tick()
import systems.calendar_handlers as ch
fired = {"popularity_decay": [], "post_engagement": [], "orphan_props": [], "background_services": []}
for name in fired:
    scheduler.register_recurring(name, (lambda n: lambda w, e: fired[n].append(w["tick"]))(name), every=scheduler._recurring[name][0], offset=scheduler._recurring[name][1])
w = copy.deepcopy(base)
w["tick"] = 7199 - 125
for _ in range(130):
    ensure_world_defaults(w); sim_loop.tick(w)
check("popularity decay runs every 60 ticks via the scheduler", all(t % 60 == 0 for t in fired["popularity_decay"]) and len(fired["popularity_decay"]) >= 2, str(fired["popularity_decay"]))
check("post engagement runs at the hour tick", fired["post_engagement"] == [7200], str(fired["post_engagement"]))
check("orphan sweep and background services run on their offsets", all(t % 30 == 5 for t in fired["orphan_props"]) and all(t % 5 == 2 for t in fired["background_services"]) and fired["background_services"])

# the weekly/hourly/daily/monthly handlers run for real, no exceptions
import traceback
errs = []
for name, fn in (("week", ch.on_week), ("hour", ch.on_hour), ("day", ch.on_day), ("month", ch.on_month)):
    ww = copy.deepcopy(base)
    try:
        fn({}, ww)
    except Exception:
        errs.append((name, traceback.format_exc().strip().splitlines()[-1]))
check("weekly / hourly / daily / monthly handlers run without errors", not errs, str(errs))

# a full tick across a week boundary triggers them through the bus exactly once
ww = copy.deepcopy(base)
ww["sim_time"] = datetime(2026, 11, 1, 23, 59, 50).timestamp() - 1
calls = []
event_bus.subscribe("time.week", lambda d, w_: calls.append("week"))
event_bus.subscribe("time.month", lambda d, w_: calls.append("month"))
for _ in range(40):
    ensure_world_defaults(ww); sim_loop.tick(ww)
check("a real tick across Monday midnight fires the week handlers once", calls.count("week") == 1, str(calls))

# sections no longer present in tick(), new section present
tick_profile.reset()
for _ in range(20):
    ensure_world_defaults(ww); sim_loop.tick(ww)
secs = {r["section"] for r in tick_profile.report()["sections"]}
check("tick profile shows the clock/scheduler section", "clock_and_scheduler" in secs and not any(s.startswith("calendar:") for s in secs), str(sorted(secs)[:6]))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
