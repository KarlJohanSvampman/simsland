"""
Trips do not repeat themselves straight away, practice driving has a cooldown and a cap, and every stay away says when it began and
when it ends (systems/offgrid.py::repeat_blocked / trip_detail / backfill_detail, systems/driver_license.py).

Run inside the backend container:   python tests/test_offgrid_repeats.py
"""

import os
import sys
from unittest import mock

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
import brain.agent_loop  # noqa: F401
from systems import driver_license as dl
from systems import offgrid as og
from systems import temporary_separation as ts

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def world(tick=100000, hour=9, minute=30):
    return {"tick": tick, "calendar": {"weekday": "Monday", "hour": hour, "minute": minute, "minute_of_day": hour * 60 + minute, "year": 2026, "month": 10, "day": 26},
            "characters": {}, "households": {}, "events": [], "offmap": [], "definitions": {}, "environment": {}}


def person(cid="a", **extra):
    d = {"id": cid, "name": cid.title(), "age": 38, "traits": [], "memories": [], "relationships": {}, "alive": True, "household_id": "hh",
         "body": {"fatigue": 10, "energy": 80}}
    d.update(extra)
    return d


# ---- a trip does not start again at once ----------------------------------------------------------------------------------------------
w = world()
c = person()
w["characters"] = {"a": c}
with mock.patch("systems.childcare_arrangement.maybe_arrange_childcare_before_departure", lambda *a, **k: None), mock.patch("sim_loop._mark_dirty", lambda *a, **k: None):
    first = og.send_offgrid(c, w, "gym", 30)
    check("a first trip goes", first and c["off_grid"] and c["off_grid_reason"] == "gym")
    c["off_grid"], c["off_grid_reason"] = False, None
    c["_offgrid_last"] = {"gym": w["tick"] - 60}
    check("the same trip a minute after it ended does not", og.send_offgrid(c, w, "gym", 30) is False and not c["off_grid"])
    check("a different kind of trip may", og.send_offgrid(c, w, "cafe", 30) is True)
    c["off_grid"], c["off_grid_reason"] = False, None
    c["_offgrid_last"] = {"gym": w["tick"] - og.DEFAULT_REPEAT_GAP_SECONDS - 1}
    check("after the gap the same trip may go again", og.send_offgrid(c, w, "gym", 30) is True)
    c["off_grid"], c["off_grid_reason"] = False, None
    c["_offgrid_last"] = {"practice_driving": w["tick"] - 3 * 3600}
    check("practice driving has a much longer gap", og.send_offgrid(c, w, "practice_driving", 30) is False and og.REPEAT_GAP_SECONDS["practice_driving"] >= 20 * 3600)
    c["_offgrid_last"] = {r: w["tick"] - 1 for r in ("work", "school", "doctor", "temporary_separation", "driving_test")}
    ok = []
    for r in ("work", "school", "doctor", "temporary_separation", "driving_test"):
        ok.append(og.send_offgrid(c, w, r, 30))
        c["off_grid"], c["off_grid_reason"] = False, None
    check("appointments and obligations are not held back by it", all(ok), str(ok))
    check("nor are events", not og.repeat_blocked({"_offgrid_last": {"event:x": w["tick"]}}, w, "event:x"))

# ---- when they left, when they are back ---------------------------------------------------------------------------------------------------
w = world(tick=100000, hour=9, minute=30)
c = person()
with mock.patch("systems.childcare_arrangement.maybe_arrange_childcare_before_departure", lambda *a, **k: None), mock.patch("sim_loop._mark_dirty", lambda *a, **k: None):
    og.send_offgrid(c, w, "gym", 45)
d = c["off_grid_detail"]
check("every trip notes when it began and when it is due back", d["started_clock"] == "Mon 09:30" and d["returns_clock"] == "Mon 10:15" and d["started_tick"] == 100000, str(d))
with mock.patch("systems.childcare_arrangement.maybe_arrange_childcare_before_departure", lambda *a, **k: None), mock.patch("sim_loop._mark_dirty", lambda *a, **k: None):
    c2 = person("b")
    og.send_offgrid(c2, w, "temporary_separation", 3 * 24 * 60)
check("a stay of days says which day it ends", c2["off_grid_detail"]["returns_clock"] == "Thu 09:30", str(c2["off_grid_detail"]))

# the separation keeps those and adds its own
w["characters"] = {"b": c2, "k": person("k", name="Karim Haddad")}
c2.pop("off_grid_detail", None)
with mock.patch.object(ts, "_find_separation_host", return_value=None), mock.patch("systems.childcare_arrangement.maybe_arrange_childcare_before_departure", lambda *a, **k: None), \
        mock.patch("sim_loop._mark_dirty", lambda *a, **k: None):
    c2["off_grid"], c2["off_grid_reason"] = False, None
    c2["_offgrid_last"] = {}
    ts.begin_temporary_separation(c2, w, "conflict", cause={"with_ids": ["k"], "outcome": "storm_off"})
d = c2["off_grid_detail"]
check("a separation says when, why and where all at once", d["started_clock"] == "Mon 09:30" and "a fight with Karim Haddad" in d["why"] and d["where"], str(d))

# someone who was already away when this was added
w = world(tick=200000, hour=11, minute=0)
lena = person("l", name="Lena Haddad", off_grid=True, off_grid_reason="temporary_separation", _offgrid_departure_tick=200000 - 3600, return_tick=200000 + 2 * 86400,
              memories=[{"text": "Had a real fight that ended in cold_shoulder.", "people": ["k"], "tick": 190000}])
w["characters"] = {"l": lena, "k": person("k", name="Karim Haddad")}
check("backfill: a stay under way gets its clocks", og.backfill_detail(lena, w) and lena["off_grid_detail"]["started_clock"] == "Mon 10:00" and lena["off_grid_detail"]["returns_clock"] == "Wed 11:00", str(lena["off_grid_detail"]))
check("... and the fight, from their own memory of it", "a fight with Karim Haddad" in lena["off_grid_detail"]["why"] and "cold silence" in lena["off_grid_detail"]["why"], str(lena["off_grid_detail"]))
check("it does nothing twice", og.backfill_detail(lena, w) is False)
check("nor for someone who is home", og.backfill_detail(person("h"), w) is False)

# the return notes the trip and clears the detail
w = world(tick=300000)
c = person(off_grid=True, off_grid_reason="gym", return_tick=299999, _offgrid_departure_tick=300000 - 1800, off_grid_detail={"started_clock": "Mon 09:00"})
w["characters"] = {"a": c}
with mock.patch.object(og, "request_offgrid_summary", lambda *a, **k: {"id": "s", "summary": "Went to the gym.", "emotion": "calm", "impact": {"stress": 0, "temp": 0}, "tags": ["gym"]}), \
        mock.patch.object(og, "_private_story", lambda *a, **k: []), mock.patch.object(og, "handle_return_transport", lambda *a, **k: None), \
        mock.patch("systems.childcare_arrangement.maybe_return_dependents", lambda *a, **k: None):
    og.process_return(c, w)
check("when they are back the trip is on record and the detail is gone", c["_offgrid_last"]["gym"] == 300000 and "off_grid_detail" not in c)

# ---- practice driving ---------------------------------------------------------------------------------------------------------------------------
w = world()
learner = person("l", driver_license_pursuit={"lessons_taken": 2, "lessons_target": 5, "practice_sessions": 0, "test_attempts": 0, "next_action_tick": 0,
                                               "pending_action": None, "awaiting_travel_return": True})
dl.on_driver_license_return(learner, w, "practice_driving")
st = learner["driver_license_pursuit"]
check("a finished session sets a cooldown of a day or more before the next", st["practice_sessions"] == 1 and st["next_practice_tick"] - w["tick"] >= 86400, str(st))
sent = []
w["characters"] = {"l": learner, "c": person("c")}
with mock.patch.object(dl, "_find_practice_companion", return_value=w["characters"]["c"]), mock.patch.object(dl, "_send_practice_session", lambda *a: sent.append(1)), \
        mock.patch.object(dl.random, "random", return_value=0.0):
    dl.maybe_practice_with_companion(learner, w)
    check("no new session while it is on", not sent)
    st["next_practice_tick"] = 0
    dl.maybe_practice_with_companion(learner, w)
    check("after it, one may follow (two lessons allow up to three sessions)", sent == [1])
    st["practice_sessions"] = 3
    dl.maybe_practice_with_companion(learner, w)
    check("but only as many as the lessons so far can use", sent == [1])
    st["lessons_taken"] = 4
    dl.maybe_practice_with_companion(learner, w)
    check("more lessons, more practice", sent == [1, 1])

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
