"""
DUTY jobs (core/flow.py): continuous only while there is work. A duty has no timer while idle, is armed by whatever
starts its work (wake_duty), runs on its old cadence (multiples of its interval) while its check is true, and drops its
timer when the work is done. A loaded world arms the active ones; the hourly safety check arms (and reports) one that
has work but no timer. Parcels in transit are timed for their arrival.

Run inside the backend container:   python tests/test_duties.py
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


from core import flow, scheduler
import systems.duties  # noqa: F401

runs = []
flow.JOBS.append(flow.DUTY("test_duty", "tests.test_duties:_run", 10, "test", "tests.test_duties:_active"))


def _run(world, entry):
    runs.append(world["sim_time"])
    if world["work"]:
        world["work"] -= 1


def _active(world):
    return world["work"] > 0


sys.modules.setdefault("tests.test_duties", sys.modules[__name__])   # the job table names "tests.test_duties:..."
flow.install()

w = {"sim_time": 1003.0, "tick": 1003, "timers": [], "work": 0}


def advance_to(t):
    while w["sim_time"] < t:
        w["sim_time"] += 1
        w["tick"] += 1
        scheduler.fire_due(w)


check("idle: no timer at all", not scheduler.pending(w, "duty:test_duty"))
w["work"] = 3
flow.wake_duty(w, "test_duty")
check("woken: due at the next multiple of its interval", [t["due"] for t in scheduler.pending(w, "duty:test_duty")] == [1010.0],
      scheduler.pending(w, "duty:test_duty"))
flow.wake_duty(w, "test_duty")
check("... waking again does not add a second timer", len(scheduler.pending(w, "duty:test_duty")) == 1)
advance_to(1100)
check("runs on its cadence while there is work, then stops", runs == [1010.0, 1020.0, 1030.0], runs)
check("... and has no timer once idle", not scheduler.pending(w, "duty:test_duty"))

w["work"] = 1                                    # work appeared without wake_duty (a missed start site)
flow.check_duties(w)
check("the safety check arms a duty that has work but no timer", scheduler.pending(w, "duty:test_duty"))

# parcels
from systems.duties import arm_delivery
w2 = {"sim_time": 0.0, "tick": 0, "timers": []}
arm_delivery(w2, {"id": "d1", "status": "in_transit", "arrival_tick": 5000})
check("a parcel in transit is timed for its arrival", [(t["owner"], t["key"], t["due"]) for t in w2["timers"]] == [("delivery", "d1", 5000.0)],
      w2["timers"])

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
