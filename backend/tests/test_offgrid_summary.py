"""
Off-grid stays: nothing happens while away; one summary object (description + key events with start/stop) is written when the
stay ends, and carried by the return announcement (systems/offgrid_summary.py, systems/offgrid.py::process_return); and an
angry character cannot assault someone who is not within reach (systems/impulse.py).

Run inside the backend container:   python tests/test_offgrid_summary.py
"""

import os
import random
import sys
from unittest import mock

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
import brain.agent_loop  # noqa: F401
from systems import offgrid as og
from systems import offgrid_summary as osum
from systems import impulse

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def world(hour=9, minute=19, weekday="Monday", tick=100000):
    return {"tick": tick, "calendar": {"weekday": weekday, "hour": hour, "minute": minute, "minute_of_day": hour * 60 + minute,
                                       "year": 2026, "month": 10, "day": 26},
            "characters": {}, "households": {}, "events": [], "offmap": [], "definitions": {}, "environment": {}}


def person(cid="erik", age=38, **extra):
    d = {"id": cid, "name": cid.title(), "age": age, "traits": [], "memories": [], "relationships": {}, "alive": True,
         "body": {"fatigue": 10, "energy": 80}, "household_id": "hh"}
    d.update(extra)
    return d


def inside(summary):
    return all(summary["start_tick"] <= e["start_tick"] < e["stop_tick"] <= summary["end_tick"] for e in summary["key_events"].values())


def contiguous(summary):
    ev = list(summary["key_events"].values())
    return all(a["stop_tick"] == b["start_tick"] for a, b in zip(ev, ev[1:])) and ev[0]["start_tick"] == summary["start_tick"] and ev[-1]["stop_tick"] == summary["end_tick"]


# ---- the builder -----------------------------------------------------------------------------------------------------------------
w = world()
c = person()
s = osum.build_summary(c, w, "gym", "Erik had a routine gym trip.", w["tick"] - 31 * 60, w["tick"])
check("a gym trip has a description and key events", s["description"] == "Erik had a routine gym trip." and 2 <= len(s["key_events"]) <= 3, str(list(s["key_events"])))
check("the key events lie within the stay, in order, covering it", inside(s) and contiguous(s))
check("each has a start and a stop time, as clock times and ticks", all(e["start"] and e["stop"] and "start_tick" in e for e in s["key_events"].values()))
check("clock times are right: 31 minutes before 09:19", s["start_clock"] == "Mon 08:48" and s["end_clock"] == "Mon 09:19", f"{s['start_clock']} {s['end_clock']}")
check("the first event starts at the departure time", list(s["key_events"].values())[0]["start"] == "08:48")
check("duration", s["duration_minutes"] == 31 and s["reason"] == "gym" and s["label"] == "Gym")
short = osum.build_summary(c, w, "gym", "Quick.", w["tick"] - 8 * 60, w["tick"])
check("a very short trip is not cut into slivers", 1 <= len(short["key_events"]) <= 2 and inside(short) and contiguous(short), str(list(short["key_events"])))
unknown = osum.build_summary(c, w, "mystery_errand", "Did a thing.", w["tick"] - 40 * 60, w["tick"])
check("any other reason gets a generic course", len(unknown["key_events"]) == 3 and inside(unknown) and contiguous(unknown))

beats = [{"text": f"Hour {i}: handled the invoices.", "notable": i == 4, "mentions_names": ["Dana"] if i == 1 else []} for i in range(8)]
beats[4]["text"] = "Presented the quarterly report to the team. It went well."
work = osum.build_summary(person(job={"title": "Branch Manager"}), world(17, 0), "work", "Worked an 8-hour shift.", 100000 - 8 * 3600, 100000, beats=beats)
check("a work shift is summarised in blocks of at most three hours", len(work["key_events"]) == 3 and all((e["stop_tick"] - e["start_tick"]) <= 3 * 3600 + 1 for e in work["key_events"].values()), str(list(work["key_events"])))
check("the notable beat names its block", "Presented the quarterly report to the team" in list(work["key_events"])[1], str(list(work["key_events"])))
check("the shift's events lie within it", inside(work) and contiguous(work))
school = osum.build_summary(person(age=9, current_school="riverside_primary"), world(15, 0), "school", "A day at school.", 100000 - 7 * 3600, 100000)
check("a school day is lessons, lunch, lessons", list(school["key_events"])[:3] == ["Morning lessons", "Lunch break", "Afternoon lessons"], str(list(school["key_events"])))
check("... all within the day", inside(school) and contiguous(school))
days = osum.build_summary(c, world(10, 0), "temporary_separation", "Stayed away.", 100000 - 3 * 86400, 100000)
check("a stay of days has an entry per day", list(days["key_events"]) == ["Day 1", "Day 2", "Day 3"] and inside(days) and contiguous(days), str(list(days["key_events"])))
check("and a start clock three days earlier", days["start_clock"].startswith("Fri"), days["start_clock"])
dup = {}
osum._add(dup, "Workout", {}); osum._add(dup, "Workout", {})
check("two events with the same name are kept apart", list(dup) == ["Workout", "Workout (2)"])

# ---- the return ------------------------------------------------------------------------------------------------------------------------
def returning(reason, minutes):
    w = world()
    c = person(off_grid=True, off_grid_reason=reason, return_tick=w["tick"] - 1, _offgrid_departure_tick=w["tick"] - minutes * 60,
               _offgrid_trip_id="trip_x", job={"title": "Branch Manager"}, employed=True, hourly_wage=20)
    w["characters"] = {c["id"]: c}
    w["households"] = {"hh": {"id": "hh", "members": ["erik"], "wealth": 100}}
    return w, c


linked = mock.Mock()
with mock.patch.object(og, "request_offgrid_summary", lambda c, world, cat, details, normalcy, enforced_cover_story=None: {
        "id": "story_1", "summary": "Erik had a routine gym trip.", "emotion": "calm", "impact": {"stress": 0, "temp": 0}, "tags": ["gym"]}), \
        mock.patch.object(og, "_private_story", lambda *a, **k: []), mock.patch.object(og, "handle_return_transport", lambda *a, **k: None), \
        mock.patch("systems.events.maybe_generate_summary_linked_event", linked), \
        mock.patch("systems.childcare_arrangement.maybe_return_dependents", lambda *a, **k: None):
    w, c = returning("gym", 31)
    og.process_return(c, w)
check("he is back", not c["off_grid"])
check("the return announcement is one world event", [e["type"] for e in w["events"]] == ["offgrid_story"])
ev = w["events"][0]
so = ev["story"].get("summary_object")
check("it carries the summary object, with description and key events", so and so["description"] == "Erik had a routine gym trip." and 2 <= len(so["key_events"]) <= 3, str(so))
check("the same object is listed on the character", c["offgrid_summaries"] == [so])
mem = [m for m in c["memories"] if m.get("kind") == "offgrid_story"]
check("the memory of the return holds the text only, not the key events", len(mem) == 1 and "summary_object" not in (mem[0].get("story") or {}), str(mem))
check("the key events are saved nowhere else on the character", "Warm-up" not in str([m for m in c["memories"]]) and "Warm-up" not in str(c.get("off_grid_story_arc")))
check("no exchange with anyone was rolled for the trip", not linked.called)

beats = [{"text": f"Hour {i} at the desk.", "notable": False, "mentions_names": [], "sentiment": "neutral"} for i in range(8)]
with mock.patch("llm.work_shift_narration.generate_hourly_work_beats", lambda *a, **k: beats), \
        mock.patch("systems.workplace_npc.get_or_create_workplace_contact", lambda *a, **k: None), \
        mock.patch.object(og, "_private_story", lambda *a, **k: []), mock.patch.object(og, "handle_return_transport", lambda *a, **k: None), \
        mock.patch("systems.events.maybe_generate_summary_linked_event", linked), \
        mock.patch("systems.childcare_arrangement.maybe_return_dependents", lambda *a, **k: None), \
        mock.patch("systems.career_ladder.advance_career_progress", lambda *a, **k: None), mock.patch("systems.career_ladder.choose_career_path", lambda *a, **k: None), \
        mock.patch("systems.crime.resolve_criminal_shift", lambda *a, **k: None), mock.patch("systems.clothing.restore_pre_work_outfit", lambda *a, **k: None), \
        mock.patch("systems.expectations.satisfy_expectation", lambda *a, **k: None):
    w, c = returning("work", 480)
    c["job_template_id"] = None
    og.process_return(c, w)
so = c["offgrid_summaries"][-1]
check("a shift has its summary too, from the hourly beats", so["reason"] == "work" and len(so["key_events"]) == 3, str(so["key_events"].keys()))
check("no memory is written per hour of the shift", not [m for m in c["memories"] if m.get("kind") in ("work_beat", "musing")], str([m.get("kind") for m in c["memories"]]))
check("the beats are not left on the stored story", all("_beats" not in e["story"] for e in w["events"]) and all("_beats" not in x for x in (c.get("off_grid_story_arc") or [])),
      str([k for k in (c.get("off_grid_story_arc") or [{}])[-1]]) + " / " + str([list(e["story"]) for e in w["events"]]))

# ---- an outburst has to reach someone ----------------------------------------------------------------------------------------------
def scene(distance=60, victim_off=False, actor_off=False):
    w = world()
    a = person("a", 38, traits=["hot_tempered"], building_id="b1", room_id="b1:dining", x=10, y=8, impulse_state={"anger_pressure": 0.99, "self_control": 0.1, "last_outburst_tick": 0},
               off_grid=actor_off)
    b = person("b", 36, building_id="b2", room_id="b2:dining", x=10 + distance, y=8, off_grid=victim_off)
    a["relationships"]["b"] = {"resentment": 90, "hostility": 80}
    w["characters"] = {"a": a, "b": b}
    w["incidents"] = []
    return w, a, b


consequences = []
with mock.patch.object(impulse, "_apply_outburst_consequences", lambda actor, target, act, world: consequences.append((actor["id"], target["id"], act))), \
        mock.patch("systems.grievances.get_grievance_score", lambda c, oid: 50):
    random.seed(1)
    w, a, b = scene(distance=60)
    impulse.tick_impulse(w)
    check("someone across town is not assaulted from a distance", not consequences, str(consequences))
    check("the anger is spent on the surroundings instead (an outburst with no target)", a["impulse_state"]["last_outburst_tick"] == w["tick"] or a["impulse_state"]["anger_pressure"] < 0.99)
    consequences.clear()
    w, a, b = scene(distance=60, actor_off=True)
    impulse.tick_impulse(w)
    check("nothing at all happens to someone who is off the grid", not consequences and a["impulse_state"]["anger_pressure"] > 0.9)
    w, a, b = scene(distance=3)
    b["building_id"] = a["building_id"] = "b1"
    b["room_id"] = a["room_id"] = "b1:dining"
    impulse.tick_impulse(w)
    check("but someone standing next to them can be", [(x[0], x[1]) for x in consequences] == [("a", "b")], str(consequences))
    consequences.clear()
    w, a, b = scene(distance=3, victim_off=True)
    b["building_id"] = a["building_id"] = "b1"
    impulse.tick_impulse(w)
    check("not someone who is away", not consequences)
reach_world = world()
check("reach: same room counts, a few tiles in the same building counts, a different building does not",
      impulse.within_reach({"room_id": "r", "x": 0, "y": 0}, {"room_id": "r", "x": 30, "y": 0}, reach_world)
      and impulse.within_reach({"building_id": "b", "x": 0, "y": 0}, {"building_id": "b", "x": 4, "y": 2}, reach_world)
      and not impulse.within_reach({"building_id": "b", "x": 0, "y": 0}, {"building_id": "c", "x": 0, "y": 1}, reach_world))

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
