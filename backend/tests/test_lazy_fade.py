"""
Memories and habits fade as lazy values of sim time (docs/distributed_architecture_plan.md, "continuous quantities
are lazy"): the same result whether refreshed every tick or once a day, at the half-life asked for
(MEMORY_HALF_LIFE_HOURS, default 38.5; HABIT_HALF_LIFE_DAYS, default 3). Both used to be multiplied a little on every
tick, so how fast they faded depended on the tick rate -- and memory importance compounded (gone in ~20 minutes).

Run inside the backend container:   python tests/test_lazy_fade.py
"""

import os
import sys

os.environ.setdefault("COGNITION_MODE", "local")
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from brain.memory import refresh_memory_importance, rewrite_memory_salience, MEMORY_HALF_LIFE_SECONDS
from systems.habits import refresh_habits, record_habit, HABIT_HALF_LIFE_SECONDS

H = 3600.0


def mem_world():
    return {"sim_time": 1000.0}, {"id": "m", "memories": [{"id": "a", "text": "a", "importance": 0.8},
                                                          {"id": "b", "text": "b", "importance": 0.05}]}


# ── memories ─────────────────────────────────────────────────────────────────────────────────────────────────────────
w1, c1 = mem_world()
w2, c2 = mem_world()
refresh_memory_importance(c1, w1)
refresh_memory_importance(c2, w2)
for _ in range(600):                    # one refreshed every 5 minutes for 50 hours ...
    w1["sim_time"] += 300
    refresh_memory_importance(c1, w1)
w2["sim_time"] += 600 * 300             # ... the other once, at the end
refresh_memory_importance(c2, w2)
a1 = next(m for m in c1["memories"] if m["id"] == "a")["importance"]
a2 = next(m for m in c2["memories"] if m["id"] == "a")["importance"]
check("memory fade does not depend on how often it is refreshed", abs(a1 - a2) < 1e-9, (a1, a2))
expect = 0.8 * 0.5 ** (50 * H / MEMORY_HALF_LIFE_SECONDS)
check("... and follows the half-life", abs(a1 - expect) < 1e-9, (a1, expect))
check("a memory under the threshold is forgotten", [m["id"] for m in c1["memories"]] == ["a"], [m["id"] for m in c1["memories"]])

w, c = mem_world()
refresh_memory_importance(c, w)
w["sim_time"] += MEMORY_HALF_LIFE_SECONDS
refresh_memory_importance(c, w)
m = c["memories"][0]
check("after one half-life: half", abs(m["importance"] - 0.4) < 1e-9, m["importance"])
rewrite_memory_salience(c, m, +0.2)                       # reflection makes it matter more, now
refresh_memory_importance(c, w)
check("a rewritten importance holds at the moment it was set", abs(m["importance"] - 0.6) < 1e-9, m["importance"])
w["sim_time"] += MEMORY_HALF_LIFE_SECONDS
refresh_memory_importance(c, w)
check("... and fades from there", abs(m["importance"] - 0.3) < 1e-9, m["importance"])

w = {"sim_time": 0.0}
c = {"id": "x", "memories": [{"id": "z", "text": "z", "importance": 1.0}]}
for t in range(0, 3 * 3600, 1):           # a tick per second for three hours: the old code forgot it in ~20 minutes
    w["sim_time"] = float(t)
    if t % 60 == 0:
        refresh_memory_importance(c, w)
check("an important memory is still there three hours later", c["memories"] and c["memories"][0]["importance"] > 0.9,
      c["memories"])

# ── habits ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def habit_world():
    return {"sim_time": 0.0, "calendar": {"hour": 7}}, {"id": "h"}


w1, c1 = habit_world()
w2, c2 = habit_world()
for _ in range(10):
    record_habit(c1, "jog", w1)
    record_habit(c2, "jog", w2)
for _ in range(24 * 6):                   # refreshed every 10 minutes for a day ...
    w1["sim_time"] += 600
    refresh_habits(c1, w1)
w2["sim_time"] += 24 * 6 * 600            # ... or once
refresh_habits(c2, w2)
s1, s2 = c1["habits"]["jog@7"], c2["habits"]["jog@7"]
check("habit fade does not depend on how often it is refreshed", abs(s1 - s2) < 1e-9, (s1, s2))
check("... and follows the half-life", abs(s1 - 10 * 0.5 ** (86400 / HABIT_HALF_LIFE_SECONDS)) < 1e-9, s1)
check("a habit at 7am is still there at 7am the next day", s1 > 5, s1)
record_habit(c1, "jog", w1)
check("doing it again adds to the faded strength", abs(c1["habits"]["jog@7"] - (s1 + 1)) < 1e-9)
w1["sim_time"] += 60 * 86400
refresh_habits(c1, w1)
check("a habit given up for two months is gone", "jog@7" not in c1["habits"], c1["habits"])

# ── persistent desires ───────────────────────────────────────────────────────────────────────────────────────────────
from systems.persistent_desires import refresh_desires, FRUSTRATION_PER_SECOND, IMPORTANCE_PER_SECOND


def desire_world():
    return {"sim_time": 0.0}, {"id": "d", "persistent_desires": [{"type": "x", "frustration": 0.4, "importance": 0.3}]}


w1, c1 = desire_world()
w2, c2 = desire_world()
refresh_desires(c1, w1)
refresh_desires(c2, w2)
for _ in range(100):
    w1["sim_time"] += 60
    refresh_desires(c1, w1)
w2["sim_time"] += 6000
refresh_desires(c2, w2)
d1, d2 = c1["persistent_desires"][0], c2["persistent_desires"][0]
check("desire frustration does not depend on how often it is refreshed",
      abs(d1["frustration"] - d2["frustration"]) < 1e-9 and abs(d1["importance"] - d2["importance"]) < 1e-9, (d1, d2))
above = 6000 - (0.5 - 0.4) / FRUSTRATION_PER_SECOND
check("... importance grows only for the time spent above 0.5",
      abs(d2["importance"] - (0.3 + IMPORTANCE_PER_SECOND * above)) < 1e-9, d2)

# ── mood ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
from brain.emotion import update_emotion

w = {"sim_time": 100.0, "tick": 1, "definitions": {}}
c = {"id": "e", "emotional_temperature": 20, "mood": {"id": "gloomy", "expires_ts": 160.0}}
update_emotion(c, w)
check("a mood holds until its expiry time", c.get("mood"))
w["sim_time"] = 160.0
update_emotion(c, w)
check("... and ends then, however few updates happened in between", c.get("mood") is None)
c = {"id": "e", "emotional_temperature": 20, "mood": {"id": "old", "remaining_ticks": 10}}
update_emotion(c, w)
check("a mood from an older save gets an expiry from its remaining ticks", c["mood"]["expires_ts"] == 169.0, c["mood"])

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
