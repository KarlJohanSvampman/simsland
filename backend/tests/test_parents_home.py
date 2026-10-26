"""
Parents stay home for the school run and are not away leaving small children alone (systems/offgrid.py::school_run_pending,
systems/temporary_separation.py).

Run inside the backend container:   python tests/test_parents_home.py
"""

import os
import sys
from unittest import mock

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
import brain.agent_loop  # noqa: F401
from systems import offgrid as og
from systems import temporary_separation as ts

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid, age, **extra):
    d = {"id": cid, "name": cid.title(), "age": age, "household_id": "hh", "relationships": {}, "memories": [], "alive": True,
         "traits": [], "body": {"fatigue": 10, "energy": 90}}
    d.update(extra)
    return d


def family(kid_age=8, parents=2, **kidextra):
    people = [person(f"p{i}", 38) for i in range(parents)] + [person("kid", kid_age, current_school="riverside_primary",
              schedule={"week": {d: [{"start": "08:00", "end": "15:00", "activity": "school"}] for d in
                                 ("monday", "tuesday", "wednesday", "thursday", "friday")}}, **kidextra)]
    w = {"tick": 100000, "characters": {c["id"]: c for c in people}, "households": {"hh": {"id": "hh", "members": [c["id"] for c in people]}},
         "calendar": {"weekday": "Monday", "hour": 7, "minute": 30, "minute_of_day": 450, "year": 2026, "month": 11, "day": 2},
         "offmap": [], "definitions": {}}
    return w, people


# ---- not leaving a child alone ----------------------------------------------------------------------------------------------------
w, (p0, p1, kid) = family()
check("with a second parent at home, a parent may go", not ts.would_leave_children_alone(p0, w))
p1["off_grid"] = True
check("the only one at home with a young child may not", ts.would_leave_children_alone(p0, w))
p1["off_grid"] = False
p1["temporary_residence"] = {"host_id": "x"}
check("a parent who is staying elsewhere does not count as home", ts.would_leave_children_alone(p0, w))
w, (p0, p1, teen) = family(kid_age=16)
p1["off_grid"] = True
check("a teenager is old enough to be left", not ts.would_leave_children_alone(p0, w))
w, (lone, kid1) = family(parents=1)[0], family(parents=1)[1]
check("a lone parent with a young child may not leave", ts.would_leave_children_alone(w["characters"]["p0"], w))

w, (p0, p1, kid) = family()
with mock.patch.object(ts, "_find_separation_host", return_value=None), mock.patch("systems.offgrid.send_offgrid", return_value=True) as sent:
    first = ts.begin_temporary_separation(p0, w)
    p0["off_grid"] = True                                       # the first one is now away
    second = ts.begin_temporary_separation(p1, w)
check("one parent can go, the other must stay with the child", first and not second and sent.call_count == 1, f"{first} {second} {sent.call_count}")
with mock.patch.object(ts, "_find_separation_host", return_value=None), mock.patch("systems.offgrid.send_offgrid", return_value=True) as sent:
    check("a child never goes", not ts.begin_temporary_separation(kid, w) and not sent.called)

# ---- the school run ----------------------------------------------------------------------------------------------------------------------
w, (p0, p1, kid) = family()
check("an hour before the bell, the school run is pending for both parents", og.school_run_pending(p0, w) and og.school_run_pending(p1, w))
check("not for the child", not og.school_run_pending(kid, w))
w["calendar"].update(hour=5, minute=30, minute_of_day=330)
check("not in the middle of the night", not og.school_run_pending(p0, w))
w["calendar"].update(hour=8, minute=30, minute_of_day=510)
check("still pending half an hour after the bell, if the child has not gone", og.school_run_pending(p0, w))
w["calendar"].update(hour=9, minute=10, minute_of_day=550)
check("over an hour after the bell it is no longer pending", not og.school_run_pending(p0, w))
w["calendar"].update(hour=7, minute=30, minute_of_day=450)
kid["_school_day"] = (2026, 11, 2)
check("not once the child has gone", not og.school_run_pending(p0, w))
kid["_school_day"] = None
w["calendar"]["weekday"] = "Saturday"
check("not on a Saturday (no school block)", not og.school_run_pending(p0, w))
w["calendar"]["weekday"] = "Monday"
p0["household_id"] = None
check("not for someone with no household", not og.school_run_pending(p0, w))
p0["household_id"] = "hh"

# the errand roll
trips = []
with mock.patch.object(og, "_send_errand", lambda c, world, reason, minutes: trips.append(reason)), \
        mock.patch.object(og, "_errand_hours_ok", lambda *a: True), mock.patch.object(og.random, "random", return_value=0.0), \
        mock.patch.object(og, "_leisure_fatigue_multiplier", lambda c: 1.0), mock.patch("systems.mental_health_effects.home_leaving_multiplier", lambda c: 1.0):
    og.maybe_go_offgrid(p0, w)
    blocked = list(trips)
    kid["_school_day"] = (2026, 11, 2)
    og.maybe_go_offgrid(p0, w)
check("a parent does not leave for an errand or outing before the kids have gone", not blocked, str(blocked))
check("and does once they have", trips == ["shopping"], str(trips))

# ---- who got them to school ------------------------------------------------------------------------------------------------------------------
w, (p0, p1, kid) = family()
w["calendar"].update(hour=8, minute=2, minute_of_day=482)
p1["off_grid"] = True
done = []
with mock.patch("systems.expectations.satisfy_expectation", lambda c, eid, world: done.append(c["id"])):
    og.send_to_school(kid, w)
check("only the parent who was home is credited with the school run", done == ["p0"], str(done))

# ---- saying why and where -------------------------------------------------------------------------------------------------------------------
w, (p0, p1, kid) = family(kid_age=16)
w["characters"]["p1"]["name"] = "Karim Haddad"
p0["name"] = "Lena Haddad"
exp = ts.explain(w, p0, {"with_ids": ["p1"], "outcome": "storm_off"})
check("the explanation names the fight and who it was with", exp["why"] == "a fight with Karim Haddad that ended with somebody storming off", str(exp))
check("and where, when nobody in particular took them in", exp["where"] == "with family or friends somewhere else")
host = {"name": "Jane Ross"}
check("or with whom, when somebody did", ts.explain(w, p0, None, host, True)["where"] == "with Jane Ross (family)" and ts.explain(w, p0, None, host, False)["where"] == "with Jane Ross (a close friend)")
check("with no known cause, an argument at home", ts.explain(w, p0, None)["why"] == "an argument at home")
with mock.patch.object(ts, "_find_separation_host", return_value=None), mock.patch("systems.offgrid.send_offgrid", return_value=True):
    ts.begin_temporary_separation(p0, w, "conflict", cause={"with_ids": ["p1"], "outcome": "cold_shoulder"})
check("the stay carries its explanation while it lasts", p0["off_grid_detail"]["why"] == "a fight with Karim Haddad that ended in a cold silence" and p0["off_grid_detail"]["with_ids"] == ["p1"], str(p0.get("off_grid_detail")))
check("and the memory says what happened", any("a fight with Karim Haddad" in m["text"] for m in p0["memories"]), str([m["text"] for m in p0["memories"]]))
story = og._separation_story(p0, w, 3 * 86400)
check("the summary of the stay tells it", story["summary"] == "Lena Haddad stayed away from home for 3 days, with family or friends somewhere else, after a fight with Karim Haddad that ended in a cold silence.", story["summary"])

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
