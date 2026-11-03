"""
A timed-out step: set the intention behind it back, lift the next one, roam somewhere else nearby, then try again
(systems/roam.py, systems/step_timeouts.py) -- and the movement log that shows it (systems/movement_log.py).

Run inside the backend container:   python tests/test_roam_retry.py
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
from brain.intentions import final_priority, set_current_tick
from systems import step_timeouts, roam, movement_log
from systems.idle_quirks import advance_idle_quirk
from systems.movement import update_character_movement
from systems.room_assignment import refresh_character_room

EAT = {"type": "eat_food", "reason": "hungry", "category": "survival", "priority": 80}
PEE = {"type": "use_toilet", "reason": "bladder", "category": "survival", "priority": 60}


def setup():
    w = make_world()
    w["tick"] = 80000
    w["props"] = [{"id": "counter", "template": "kitchen_counter", "x": 57, "y": 4, "state": {}, "rotation": 0}]
    k = w["characters"]["kathleen"]
    k.update(x=57, y=5, building_id="starter_house_2", age=30, activity=None, route=[], is_moving=False,
             cognition={}, memories=[], posture="standing", active_intentions=[dict(EAT), dict(PEE)],
             current_intention=dict(EAT))
    refresh_character_room(k, w)
    return w, k


def run(w, c, ticks, move=True):
    for _ in range(ticks):
        w["tick"] += 1
        set_current_tick(w["tick"])
        scheduler.install(w)
        scheduler.fire_due(w)
        refresh_character_room(c, w)
        step_timeouts.note_step(c, w)
        if move and c.get("is_moving"):
            update_character_movement(c, w)
        advance_idle_quirk(c, w)


# ---- stuck walking to the counter to eat ------------------------------------------------------------------------------
w, k = setup()
k["activity"] = {"type": "interact", "interaction": "prepare_food", "target_id": "counter", "phase": "walking",
                 "phase_started_tick": w["tick"], "duration": 600, "state": {}}
step_timeouts.note_step(k, w)
run(w, k, step_timeouts.STALL_TICKS + 2, move=False)
act = k.get("activity") or {}
check("stuck walking to the counter: after the timeout he roams instead of standing there",
      act.get("type") == "roam" and k.get("is_moving"), str(act))
check("... with what he was doing kept, to try again", (act.get("retry") or {}).get("interaction") == "prepare_food",
      str(act.get("retry")))
set_current_tick(w["tick"])
check("... the intention behind it (eat) is set back below the next one (toilet)",
      final_priority(k["active_intentions"][0], k) < final_priority(k["active_intentions"][1], k))
check("... and he notes why", any("put \"eat food\" aside" in m["text"] for m in k["memories"]), str([m["text"] for m in k["memories"]][-3:]))
check("he wonders out loud where he was going", "where was I going" in ((k.get("current_speech") or {}).get("utterance") or ""),
      str(k.get("current_speech")))
check("... and pieces it back together: what, where, why and how long ago",
      any("on my way to prepare food at the kitchen counter (why: hungry). I started 3 minutes ago" in m["text"]
          for m in k["memories"]), str([m["text"] for m in k["memories"]][-4:]))
check("... the roam goes to another room", str(act.get("target_room")) != str(k.get("room_id")).split(":")[-1])

def until_roam_over(w, k, limit=600):
    for _ in range(limit):
        run(w, k, 1)
        if (k.get("activity") or {}).get("type") != "roam":
            return


until_roam_over(w, k)
act = k.get("activity") or {}
check("once roamed: he tries the counter again", act.get("type") == "interact" and act.get("target_id") == "counter",
      str(act))

# ---- stuck a second time: no more retries -----------------------------------------------------------------------------
k["is_moving"], k["route"] = False, []
k["activity"].update(phase="walking", phase_started_tick=w["tick"])
step_timeouts.note_step(k, w)
run(w, k, step_timeouts.STALL_TICKS + 2, move=False)
check("stuck again: roams again", (k.get("activity") or {}).get("type") == "roam")
until_roam_over(w, k)
check("... but after that it's let go, not retried a third time",
      (k.get("activity") or {}).get("type") != "interact"
      and any("let it go" in m["text"] for m in k["memories"]), str(k.get("activity")))

# ---- outdoors: a random spot a few tiles away --------------------------------------------------------------------------
w, k = setup()
k.update(x=60, y=14, building_id=None)
refresh_character_room(k, w)
check("outdoors, a roam goes a few tiles off", roam.start_roam(k, w, retry={"type": "move"})
      and "," in str(k["activity"]["target_room"]))

# ---- the movement log ---------------------------------------------------------------------------------------------------
w, k = setup()
k["activity"] = {"type": "interact", "interaction": "prepare_food", "target_id": "counter", "phase": "walking",
                 "phase_started_tick": w["tick"], "duration": 600, "state": {}}
run(w, k, 120, move=False)
log = k.get("move_log") or {}
check("the movement log samples every 15 s while she's meant to be walking",
      len(log.get("samples", [])) >= 6 and all(s[1] == 0 for s in log["samples"]), str(log.get("samples")))
check("... and counts those as stuck", log.get("stuck_samples", 0) >= 5, str(log.get("stuck_samples")))
run(w, k, step_timeouts.STALL_TICKS, move=True)
kinds = [e[1] for e in k["move_log"]["events"]]
check("... the timeout and the roam's start are on the time axis", "timeout" in kinds and "start" in kinds, str(kinds))
run(w, k, 120)
moved = [s for s in k["move_log"]["samples"] if s[2] and s[1] > 0.5]
check("... and the roam's walking shows as distance covered", moved, str(k["move_log"]["samples"][-6:]))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
