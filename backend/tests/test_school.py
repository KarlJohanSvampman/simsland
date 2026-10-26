"""
Children go to school: school blocks in the schedule, the bell, the trip, the return (systems/age_rules.py, systems/scheduling.py,
systems/offgrid.py, brain/agent_loop.py).

Run inside the backend container:   python tests/test_school.py
(the last section runs the seeded simulation, see tests/determinism.py)
"""

import os
import sys
from unittest import mock

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
import brain.agent_loop  # noqa: F401
from db import load_definitions
from systems import age_rules as ar
from systems import offgrid as og
from systems import bedtime as bt
from systems.character_gen import generate_character
from systems.scheduling import generate_week_schedule, WORK_DAYS, WEEKDAYS

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


defs = load_definitions("default")


def world(day="monday", hour=7, minute=55, tick=100000):
    return {"tick": tick, "definitions": defs, "characters": {}, "households": {}, "offmap": [], "environment": {},
            "calendar": {"weekday": day.capitalize(), "hour": hour, "minute": minute, "minute_of_day": hour * 60 + minute,
                         "year": 2026, "month": 11, "day": 2}}


# ---- the hours -----------------------------------------------------------------------------------------------------------------
check("school hours by level", [ar.school_hours(a) for a in (4, 8, 12, 15, 30)] == [(9, 12), (8, 15), (8, 15), (8, 16), None])

# ---- the schedule --------------------------------------------------------------------------------------------------------------------
kid = generate_character(defs, {"age": 9})
kid["schedule"] = generate_week_schedule(kid, world())
days = {d: [b for b in blocks if b["activity"] == "school"] for d, blocks in kid["schedule"]["week"].items()}
check("a school child has a school block Monday to Friday", all(len(days[d]) == 1 for d in WORK_DAYS), str(days))
check("... and none at the weekend", all(not days[d] for d in ("saturday", "sunday")))
check("with the hours of their school level", days["monday"][0]["start"] == "08:00" and days["monday"][0]["end"] == "15:00")
teen = generate_character(defs, {"age": 15})
teen["schedule"] = generate_week_schedule(teen, world())
check("a high-schooler's day is 08:00-16:00", [(b["start"], b["end"]) for b in teen["schedule"]["week"]["tuesday"] if b["activity"] == "school"] == [("08:00", "16:00")])
tot = generate_character(defs, {"age": 4})
tot["schedule"] = generate_week_schedule(tot, world())
check("a preschooler goes mornings", [(b["start"], b["end"]) for b in tot["schedule"]["week"]["wednesday"] if b["activity"] == "school"] == [("09:00", "12:00")])
adult = generate_character(defs, {"age": 35})
adult["schedule"] = generate_week_schedule(adult, world())
check("an adult has no school block", not any(b["activity"] == "school" for d in adult["schedule"]["week"].values() for b in d))
check("a school block counts as the daytime obligation for bedtime", bt.has_daytime_obligation(kid, "monday") and not bt.has_daytime_obligation(kid, "saturday"))
sleepblocks = [b for b in kid["schedule"]["week"]["monday"] if b["activity"] == "sleep"]
check("the sleep block and school block do not overlap", sleepblocks and sleepblocks[0]["end"] <= "08:00")

# ---- the bell ----------------------------------------------------------------------------------------------------------------------------
check("not before the bell", not og.school_starting_now(kid, world(hour=7, minute=30)))
check("at the bell", og.school_starting_now(kid, world(hour=8, minute=0)))
check("up to an hour late", og.school_starting_now(kid, world(hour=8, minute=55)))
check("after that, school has started without them", not og.school_starting_now(kid, world(hour=9, minute=5)))
check("not on a Saturday", not og.school_starting_now(kid, world(day="saturday", hour=8, minute=5)))
check("not for an adult", not og.school_starting_now(adult, world(hour=8, minute=5)))
kid2 = dict(kid, off_grid=True)
check("not while away already", not og.school_starting_now(kid2, world(hour=8, minute=5)))

# ---- the trip ----------------------------------------------------------------------------------------------------------------------------
w = world(hour=8, minute=5)
parent = generate_character(defs, {"age": 38})
kid["household_id"] = parent["household_id"] = "hh"
w["characters"] = {kid["id"]: kid, parent["id"]: parent}
w["households"] = {"hh": {"id": "hh", "members": [kid["id"], parent["id"]]}}
satisfied = []
with mock.patch("systems.expectations.satisfy_expectation", lambda c, eid, world: satisfied.append((c["id"], eid))):
    og.maybe_go_offgrid(kid, w)
check("at the bell the child leaves for school", kid.get("off_grid") and kid.get("off_grid_reason") == "school", str(kid.get("off_grid_reason")))
check("until the school day ends (15:00 minus 08:05)", kid["return_tick"] - w["tick"] == (15 * 60 - (8 * 60 + 5)) * 60, str(kid.get("return_tick")))
check("their parent's 'get the kids to school' is done", satisfied == [(parent["id"], "get_kids_to_school")], str(satisfied))
check("only once a day", not og.school_starting_now(dict(kid, off_grid=False), w))

# ---- the return ---------------------------------------------------------------------------------------------------------------------------
w["tick"] = kid["return_tick"]
body_before = dict(kid.get("body") or {})
kid.setdefault("body", {}).update(fatigue=30.0, energy=70.0, hunger=90.0, hydration=50.0)
needs = []
with mock.patch("systems.lt_needs.satisfy_lt_need", lambda c, nid, world, **k: needs.append(nid)), \
        mock.patch("systems.events.maybe_generate_summary_linked_event", lambda c, world: None), \
        mock.patch("systems.childcare_arrangement.maybe_return_dependents", lambda c, world: None):
    og.process_return(kid, w)
check("the child is home again", not kid["off_grid"] and kid["off_grid_reason"] is None)
story = kid["off_grid_story_arc"][-1]
check("the day is remembered as a school day, with no private events", "school" in story["tags"] and "private" not in story, str(story))
check("a school day tires them far less than a shift (under 45 of 100)", kid["body"]["fatigue"] - 30.0 < 45, str(kid["body"]["fatigue"]))
check("it satisfies the need to learn", needs == ["learning"], str(needs))
check("they ate during the day: hungry in the morning, not starving by the afternoon", kid["body"].get("hunger", 100) <= 90 - 40, str(kid["body"].get("hunger")))

# ---- in the simulation ----------------------------------------------------------------------------------------------------------------------
from tests import determinism
import systems.scheduling as sched

picked = {}


def setup(w):
    kids = [c for c in w["characters"].values() if (c.get("age") or 99) < 18 and not c.get("is_workplace_npc")]
    for c in kids:
        c["current_school"] = "riverside_primary"
        c["off_grid"] = False
        c["activity"] = {"type": "sleep", "phase": "using", "duration": 40000, "phase_started_tick": w["tick"], "interaction": "sleep"} if c is kids[0] else None
        c["schedule"] = generate_week_schedule(c, w)
        picked[c["id"]] = c["name"]


w2, errs, _ = determinism.run_sim(11 * 60, start="2026-11-02T07:55:00", setup=setup)       # Monday 07:55 -> 08:06
away = {cid: w2["characters"][cid].get("off_grid_reason") for cid in picked if w2["characters"][cid].get("off_grid")}
print(f"   children {list(picked.values())}; away at 08:06: {away}; errors {dict(errs)}")
check("the simulation ran without errors", not errs, str(dict(determinism.ERROR_TRACES)))
check("every child, the sleeping one too, was sent to school at the bell", picked and len(away) == len(picked) and set(away.values()) == {"school"}, str(away))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
