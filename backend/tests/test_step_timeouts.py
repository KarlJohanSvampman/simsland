"""
Every step has a timeout event (systems/step_timeouts.py): 3 sim-minutes without anything happening -- or, for a step
with a known length, that length plus 3 minutes -- and the character is reported stuck and taken out of it. Nothing
polls: one timer per character, re-armed only when the step changes, and progress inside a step pushes it back.

Run inside the backend container:   python tests/test_step_timeouts.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from house_world import make_world
from core import scheduler
from systems import step_timeouts as st
from systems.step_timeouts import STALL_TICKS, note_step


def setup():
    w = make_world()
    w["tick"] = 40000
    k = w["characters"]["kathleen"]
    k.update(route=[], is_moving=False, travel_state=None, activity=None, off_grid=False, legal={})
    return w, k


def run(w, c, ticks, each=None):
    for _ in range(ticks):
        w["tick"] += 1
        scheduler.fire_due(w)
        if each:
            each(w, c)
        note_step(c, w)


def stuck_log(c):
    return [m["text"] for m in c.get("memories", []) if "stuck" in (m.get("tags") or [])]


def woken(c):
    return (c.get("cognition") or {}).get("wake_reason") == "activity_aborted"


# ---- a short step with nothing happening: 3 minutes ----------------------------------------------------------------
w, k = setup()
k["activity"] = {"type": "examine", "target_id": "fridge_1", "phase": "walking", "phase_started_tick": w["tick"],
                 "state": {}}
note_step(k, w)
check("starting a step arms exactly one timeout", len(scheduler.pending(w, "stuck:kathleen")) == 1)
check("... due 3 minutes out", scheduler.pending(w, "stuck:kathleen")[0]["at"] == w["tick"] + STALL_TICKS)
run(w, k, STALL_TICKS - 1)
check("walking to the fridge without moving: still on it just before 3 minutes", (k.get("activity") or {}).get("type") == "examine")
run(w, k, 2)
check("... at 3 minutes: taken out of it -- roaming somewhere else, to try again after (systems/roam.py)",
      (k.get("activity") or {}).get("type") == "roam"
      and (k["activity"].get("retry") or {}).get("type") == "examine", str(k.get("activity")))
check("... reported in the memory log", stuck_log(k) and "examine" in stuck_log(k)[-1], str(stuck_log(k)))
check("... and saying so out loud", "where was I going" in ((k.get("current_speech") or {}).get("utterance") or ""))

# ---- a walk that is making progress is left alone --------------------------------------------------------------------
w, k = setup()
k["activity"] = {"type": "examine", "target_id": "fridge_1", "phase": "walking", "phase_started_tick": w["tick"],
                 "state": {}}
k["is_moving"] = True


def creep(w, c):
    c["x"] += 0.01                                   # half a tile every 50 ticks


run(w, k, 600, each=creep)
check("a slow walk that keeps getting further isn't stuck (10 minutes in)", (k.get("activity") or {}).get("type") == "examine")
check("... and progress didn't reschedule every tick: still one timer", len(scheduler.pending(w, "stuck:kathleen")) == 1)
run(w, k, st.WALK_MAX_TICKS - 600 + 2, each=creep)
check("... but no walk goes on past 15 minutes", (k.get("activity") or {}).get("type") == "roam")

# ---- a step with a known length gets it, plus 3 minutes --------------------------------------------------------------
w, k = setup()
k["activity"] = {"type": "take_shower", "target_id": None, "phase": "using", "phase_started_tick": w["tick"],
                 "duration": 600, "state": {}}
run(w, k, 600 + STALL_TICKS - 2)
check("a 10-minute shower isn't cut off at 10 minutes (or 3)", (k.get("activity") or {}).get("type") == "take_shower")
run(w, k, 3)
check("... but is if it's still going 3 minutes after it should have ended",
      (k.get("activity") or {}).get("type") != "take_shower")

# ---- something happening pushes it back: a conversation line --------------------------------------------------------
w, k = setup()
k["activity"] = {"type": "order_food", "target_id": None, "phase": "ordering", "phase_started_tick": w["tick"],
                 "state": {}}
run(w, k, STALL_TICKS - 10)
st.progress(k, w)                                    # what brain/conversations.add_message does for each participant
run(w, k, STALL_TICKS - 10)
check("a line said in the conversation counts as something happening", (k.get("activity") or {}).get("type") == "order_food")
run(w, k, 20)
check("... 3 minutes after the last one, it's over", (k.get("activity") or {}).get("type") != "order_food")

# ---- the step changing re-arms, the step ending disarms --------------------------------------------------------------
w, k = setup()
k["activity"] = {"type": "examine", "target_id": "fridge_1", "phase": "walking", "phase_started_tick": w["tick"], "state": {}}
note_step(k, w)
run(w, k, 100)
k["activity"].update(phase="using", phase_started_tick=w["tick"], duration=30)
note_step(k, w)
check("a new phase re-arms from its own start", scheduler.pending(w, "stuck:kathleen")[0]["at"] == w["tick"] + 30 + STALL_TICKS)
k["activity"] = None
note_step(k, w)
check("no step, no timer", not scheduler.pending(w, "stuck:kathleen") and not k.get("_step"))

# ---- sleep is left alone; the retired "work" goes at once ------------------------------------------------------------
w, k = setup()
k["activity"] = {"type": "sleep", "phase": "using", "phase_started_tick": w["tick"] - 40000, "duration": 28800, "state": {}}
run(w, k, 10)
check("sleep has no step timeout", (k.get("activity") or {}).get("type") == "sleep" and not scheduler.pending(w, "stuck:kathleen"))
k["activity"] = {"type": "work", "interaction": "work", "phase": "using", "phase_started_tick": w["tick"] - 19767,
                 "duration": 28800, "state": {}}
run(w, k, 2)
check("a leftover at-home \"work\" is ended right away", not k.get("activity"))

# ---- trip legs: waiting for a bus that never comes, a drive that never ends ------------------------------------------
w, k = setup()
k.update(x=8, y=11, travel_state="waiting_for_bus", travel_mode="bus",
         _pending_offgrid={"reason": "shopping", "duration": 45})
run(w, k, st._LEG_TICKS["waiting_for_bus"])
check("waiting for the bus: given the 15 minutes the bus can take and more", k.get("travel_state") == "waiting_for_bus")
run(w, k, STALL_TICKS + 2)
check("... after that, the trip happens without the bus (off-grid)", k.get("off_grid") is True and not k.get("travel_state"),
      str((k.get("off_grid"), k.get("travel_state"))))
check("... reported", stuck_log(k) and "waiting for the bus" in stuck_log(k)[-1], str(stuck_log(k)))

w, k = setup()
k.update(x=8, y=11, travel_state="awaiting_bus_arrival", travel_mode="bus")
run(w, k, st._LEG_TICKS["awaiting_bus_arrival"] + STALL_TICKS + 2)
check("waiting for the bus home that never comes: walks home instead", k.get("travel_state") in ("walking_home", None)
      and not k.get("travel_hidden"), str(k.get("travel_state")))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
