"""
A CPS worker leaves when the visit is over (systems/child_welfare.py); before this nothing removed them and each visit left one
standing at the mailbox for good. Also: the character list says which NPCs are workplace NPCs / service workers, for the Outliner.

Run inside the backend container:   python tests/test_cps_worker_cleanup.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from systems import child_welfare as cw
from api.household import _all_characters

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


w = {"tick": 1000, "characters": {"kid": {"id": "kid", "name": "Kid", "household_id": "h", "x": 3, "y": 4}},
     "households": {"h": {"id": "h", "mailbox": {"x": 5, "y": 6}}}}
wid = cw._dispatch_cps_worker(w["characters"]["kid"], w)
check("a dispatched worker is on the map with a time to leave", wid in w["characters"] and w["characters"][wid]["leaves_tick"] == 1000 + cw.CPS_VISIT_TICKS)
w["tick"] += cw.CPS_VISIT_TICKS - 1
cw.retire_cps_workers(w)
check("... and is still there during the visit", wid in w["characters"])
w["tick"] += 1
cw.retire_cps_workers(w)
check("... and gone when it is over", wid not in w["characters"] and "kid" in w["characters"])

# one left behind by the old code gets a visit's worth from the first time it is seen, then goes
w["characters"]["worker_cps_old"] = {"id": "worker_cps_old", "name": "Ms. Reyes", "is_service_worker": True, "service_role": "cps_worker"}
w["characters"]["worker_mail"] = {"id": "worker_mail", "name": "Mailman", "is_service_worker": True, "service_role": "mail"}
cw.retire_cps_workers(w)
check("an old leftover is given a leave time, not dropped at once", "worker_cps_old" in w["characters"] and w["characters"]["worker_cps_old"]["leaves_tick"] > w["tick"])
w["tick"] += cw.CPS_VISIT_TICKS
cw.retire_cps_workers(w)
check("... and leaves after it", "worker_cps_old" not in w["characters"])
check("other service workers are not touched", "worker_mail" in w["characters"])

w["characters"]["npc"] = {"id": "npc", "name": "Frank", "is_workplace_npc": True}
listed = {c["id"]: c for c in _all_characters(w)["characters"]}
check("the list flags workplace NPCs and service workers", listed["npc"]["is_workplace_npc"] and not listed["npc"]["is_service_worker"]
      and listed["worker_mail"]["is_service_worker"] and not listed["kid"]["is_workplace_npc"])

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
