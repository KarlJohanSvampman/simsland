"""
A character's update_agent() runs only when it is due (brain/agent_wake.py): woken by an event about them, a timer of
their own, their decision cycle, walking, or the heartbeat. Checked here:

  * the gate: due on first sight, on a wake, on a timer, while walking, when free and due to think, on the heartbeat --
    and not otherwise; wakes set while the update runs survive it (begin_run clears before, not after);
  * an event naming a character wakes them (event bus hook); an incident wakes whoever is near it;
  * per-tick chances drawn ahead (agent_wake.chance) keep the per-tick rate;
  * wake_at_minute lands on the next time the clock reads that minute;
  * an activity's own clock sets the next wake;
  * shadow mode records a step the gate would have skipped but which changed real state.

Run inside the backend container:   python tests/test_agent_wake.py
"""

import os
import random
import sys

os.environ.setdefault("COGNITION_MODE", "local")
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from brain import agent_wake as aw

aw.set_mode("on")


def world_at(ts, tick=100, minute_of_day=600):
    return {"sim_time": float(ts), "tick": tick,
            "calendar": {"hour": minute_of_day // 60, "minute": minute_of_day % 60, "second": 0}, "characters": {}}


# ── the gate ─────────────────────────────────────────────────────────────────────────────────────────────────────────
w = world_at(1000)
LONG = {"type": "watch_tv", "phase": "using", "phase_started_tick": 100, "duration": 10 ** 6}
c = {"id": "a", "activity": dict(LONG), "cognition": {"next_think_tick": 10 ** 9}}
check("first sight: due", aw.due(c, w)[0])
aw.begin_run(c, w)
aw.wake_at(c, w, 1030, "alarm")                    # set by a check while the update runs ...
aw.note_run(c, w)
check("... a wake set during the update survives it", c["_wake"]["at"] == 1030, c["_wake"])
c2 = {"id": "b", "activity": {"type": "watch_tv"}}
aw.begin_run(c2, w)
aw.note_run(c2, w)
check("an activity with no clock of its own is looked at again on the next step", c2["_wake"]["at"] == 1001, c2["_wake"])
w["sim_time"] = 1010
check("nothing due in between: skipped", not aw.due(c, w)[0])
w["sim_time"] = 1030
check("its timer: due", aw.due(c, w) == (True, "alarm"))
aw.begin_run(c, w)
aw.note_run(c, w)
w["sim_time"] = 1031
aw.wake(c, w, "heard_speech")
check("an event wake: due", aw.due(c, w) == (True, "heard_speech"))
aw.begin_run(c, w)
aw.note_run(c, w)
c["is_moving"] = True
check("walking: due every step", aw.due(c, w) == (True, "moving"))
c["is_moving"] = False
c["activity"] = None
c["cognition"]["next_think_tick"] = w["tick"]
check("free and due to think: due", aw.due(c, w) == (True, "think"))
c["cognition"]["pending"] = {"tick": 1}
check("... not while a decision is with the model", not aw.due(c, w)[0])
c["cognition"]["pending"] = None
c["activity"] = dict(LONG)
w["sim_time"] = 1031 + aw.HEARTBEAT_SECONDS
check("the heartbeat: due", aw.due(c, w) == (True, "heartbeat"))
aw.wake_now(c, "intention_added")
check("wake_now (no world at hand): due", aw.due(c, w)[0])

# ── events wake the characters they name ────────────────────────────────────────────────────────────────────────────
w = world_at(5000)
w["characters"] = {"x": {"id": "x"}, "y": {"id": "y"}, "z": {"id": "z", "x": 3, "y": 3, "building_id": None}}
aw._on_event("character_fired", {"character_id": "x", "character_ids": ["y"]}, w)
check("an event naming characters wakes them", w["characters"]["x"]["_wake"]["at"] == 5000 and w["characters"]["y"]["_wake"]["at"] == 5000)
check("... and nobody else", "_wake" not in w["characters"]["z"])
w["incidents"] = [{"id": "inc1", "x": 4, "y": 4, "building_id": None}]
aw._on_incident({"incident_id": "inc1"}, w)
check("an incident wakes whoever is near it", (w["characters"]["z"].get("_wake") or {}).get("why") == "incident")

# ── chances drawn ahead keep the per-tick rate ───────────────────────────────────────────────────────────────────────
random.seed(7)
p, ticks, hits = 0.02, 200000, 0
c = {"id": "r"}
w = world_at(0, tick=0)
for t in range(ticks):
    w["tick"], w["sim_time"] = t, float(t)
    if aw.chance(c, w, "roll", p):
        hits += 1
check("a chance drawn ahead comes up at the per-tick rate", abs(hits / ticks - p) < 0.002, hits / ticks)
c = {"id": "r2"}
w = world_at(0, tick=0)
fired_at = None
for t in range(10000):
    w["tick"], w["sim_time"] = t, float(t)
    c.pop("_wake", None)
    if aw.chance(c, w, "roll", 0.01):
        fired_at = t
        break
    nxt = c["_wake"]["at"]
check("... and its wake is set for the step it comes up", fired_at is not None and nxt == fired_at, (fired_at, nxt))

# ── clock minutes, activity clocks ───────────────────────────────────────────────────────────────────────────────────
w = world_at(10000, minute_of_day=6 * 60 + 50)
c = {"id": "m"}
aw.wake_at_minute(c, w, 7 * 60, "alarm")
check("wake_at_minute: the next time the clock reads it", c["_wake"]["at"] == 10000 + 10 * 60, c["_wake"])
c = {"id": "m2"}
aw.wake_at_minute(c, w, 6 * 60, "alarm")
check("... tomorrow if that minute has passed today", c["_wake"]["at"] == 10000 + (23 * 60 + 10) * 60)
c = {"id": "act", "activity": {"type": "eat", "phase": "using", "phase_started_tick": 90, "duration": 50}}
w = world_at(2000, tick=100)
aw.begin_run(c, w)
aw.note_run(c, w)
check("an activity's own clock sets the next wake", c["_wake"]["at"] == 2000 + 40, c["_wake"])

# ── shadow mode ──────────────────────────────────────────────────────────────────────────────────────────────────────
aw.reset_stats()
c = {"id": "s", "mood": None, "_habits_ts": 1}
before = aw.shadow_before(c)
c["_habits_ts"] = 2                                  # only a lazy value's stamp: not a miss
aw.shadow_after(c, w, before, False, None)
before = aw.shadow_before(c)
c["activity"] = {"type": "sleep"}                    # real state: a miss
aw.shadow_after(c, w, before, False, None)
check("shadow: a lazy stamp is not a miss, a real change is", aw.stats().get("misses") == 1 and aw.miss_keys() == {"activity": 1},
      (aw.stats(), aw.miss_keys()))

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
