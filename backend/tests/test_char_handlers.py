"""
Step 5a: per-character work that used to be a sweep over every character on a cadence is the character's own (run in
its update, with a wake for when it next has something to do), and world-level schedules wake their duty on time.

Run inside the backend container:   python tests/test_char_handlers.py
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


def W(tick):
    return {"sim_time": float(tick), "tick": tick, "calendar": {"hour": 12, "minute": 0}, "characters": {}, "timers": []}


# ── reading / watching: the next pick is a wake on the old 5-second grid ────────────────────────────────────────────
from brain.agent_loop import _arm_media_picks

w = W(1003)
c = {"id": "r", "active_process": {"type": "reading_news", "last_pick_tick": 1001}}
_arm_media_picks(c, w, 300, 300)
check("someone reading wakes for the next pick, on the 5-second grid", c["_wake"]["at"] == 1305.0, c.get("_wake"))
c = {"id": "q"}
_arm_media_picks(c, w, 300, 300)
check("someone not reading or watching gets no wake", "_wake" not in c)

# ── kickoff: a fixture's timer wakes the duty, which runs while someone has yet to set off ──────────────────────────
import systems.sports as S
from core import flow, scheduler
import systems.duties  # noqa: F401
flow.install()

w = W(100)
w["sports_leagues"] = {"football": {"pro": {"schedule": [
    {"id": "fx1", "scheduled_tick": 500, "attendees": {"a": {"mode": "on_grid"}}, "result": None}]}}}
check("before kickoff nothing is pending", not S.kickoff_pending(w))
from systems.duties import on_world_loaded
on_world_loaded(w)
check("a loaded world times each upcoming fixture", [(t["owner"], t["due"]) for t in w["timers"] if t["owner"] == "kickoff"] == [("kickoff", 500.0)],
      w["timers"])
w["tick"] = w["sim_time"] = 500
check("at kickoff it is pending", S.kickoff_pending(w))
S._on_kickoff_timer(w, {})
check("... and the timer arms the sports_watching duty", scheduler.pending(w, "duty:sports_watching"))
w["sports_leagues"]["football"]["pro"]["schedule"][0]["attendees"]["a"]["started"] = True
check("once everyone has set off, nothing is pending", not S.kickoff_pending(w))

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
