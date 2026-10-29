"""
When the 1x clock resync jumps the clock hours ahead, characters mid-sleep whose schedule says awake are woken (main.py).

Run inside the backend container:   python tests/test_clock_jump_wakes.py
"""

import os
import sys
import time
from datetime import datetime

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
import main

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def sleeper(cid, activity="relax"):
    week = {d: [{"start": "00:00", "end": "23:59", "activity": activity}]
            for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")}
    return {"id": cid, "name": cid, "activity": {"type": "sleep", "phase": "using", "state": {}}, "schedule": {"week": week}, "posture": "lying"}


def world_with(sim_time, scale=1):
    return {"sim_time": sim_time, "time_scale": scale, "tick": 1000, "characters": {"day": sleeper("day"), "night": sleeper("night", "sleep")}}


def resync(w):
    main._resynced_clock_this_process = False
    main._maybe_resync_clock_to_real_time(w)


# a restart that moves the clock 10 hours ahead wakes whoever the schedule says should be up
w = world_with(time.time() - 10 * 3600)
resync(w)
check("a sleeper whose schedule says awake is woken", w["characters"]["day"]["activity"] is None, str(w["characters"]["day"]["activity"]))
check("... one whose schedule says sleep keeps sleeping", (w["characters"]["night"]["activity"] or {}).get("type") == "sleep")

# a small catch-up leaves everyone alone
w = world_with(time.time() - 600)
resync(w)
check("a ten minute catch-up wakes no one", w["characters"]["day"]["activity"] is not None)

# a sped-up sim is not resynced and nobody is touched
w = world_with(time.time() - 10 * 3600, scale=4)
resync(w)
check("a sped-up sim keeps its own clock and its sleepers", w["characters"]["day"]["activity"] is not None and w["sim_time"] < time.time() - 9 * 3600)

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
