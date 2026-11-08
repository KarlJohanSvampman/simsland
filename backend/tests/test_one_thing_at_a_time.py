"""
One activity at a time (systems/occupancy.py::occupy), and envy only when the other person is brought to mind
(systems/life_comparison.py::on_reminded).

A. Starting an activity while another is still running -- not finished, interrupted or paused -- is a clash: a clear
   error naming where it came from, the running one ends ("clash"), the new one is dropped, and the character loses a few
   minutes standing there flustered, and thinks so. A decision to do something else (`switching`) ends the running one
   properly first; the next task a completion starts is not a clash; re-assigning the same activity is not a clash.
B. Live (2026-11-06): "envy over how the other one lives" was logged against the same person every 10-30 minutes, day and
   night. Now a comparison happens only when the other is seen, mentioned or visited, at most once per pair per
   REMINDER_COOLDOWN_SECONDS, and what brought it up is on the record (and on the issue's evidence).

Run inside the backend container:   python tests/test_one_thing_at_a_time.py
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
from systems.occupancy import occupy, switching, CLASH_WASTE_SECONDS
from core import scheduler


def act(kind, w, phase="using"):
    return {"type": kind, "phase": phase, "phase_started_tick": w["tick"], "duration": 600, "state": {}}


def setup():
    w = make_world()
    w["tick"] = 20000
    w["calendar"] = {"year": 2026, "month": 11, "day": 1, "hour": 15, "minute": 0, "second": 0, "minute_of_day": 900,
                     "weekday": "Sunday"}
    k = w["characters"]["kathleen"]
    k.update(memories=[], activity=None)
    return w, k


# ---- A: one activity at a time ------------------------------------------------------------------------------------
w, k = setup()
k["activity"] = occupy(k, w, act("watch_tv", w))
check("nothing running: the activity starts", k["activity"]["type"] == "watch_tv")
same = k["activity"]
k["activity"] = occupy(k, w, same)
check("the same activity again is not a clash", k["activity"] is same and not w.get("activity_clashes"))

k["activity"] = occupy(k, w, act("take_shower", w))
clash = (w.get("activity_clashes") or [{}])[-1]
check("starting a shower while watching TV is a clash, on the record",
      clash.get("running") == "watch_tv" and clash.get("started") == "take_shower" and clash.get("from"), str(clash))
check("... both are dropped: they stand there flustered instead",
      k["activity"]["type"] == "wait" and k["activity"]["state"]["reason"] == "flustered")
check("... and they think so", "can't do two things at once" in (k.get("last_thought") or "")
      and any("clash" in (m.get("tags") or []) for m in k["memories"]))
check("... for a few minutes (a timer ends it)",
      [round(t["due"] - w["tick"]) for t in scheduler.pending(w, f"fluster:{k['id']}")] == [CLASH_WASTE_SECONDS],
      str(scheduler.pending(w, f"fluster:{k['id']}")))
w["tick"] += CLASH_WASTE_SECONDS
scheduler.fire_due(w)
check("after those minutes they are free again", k["activity"] is None)

w, k = setup()
k["activity"] = occupy(k, w, act("watch_tv", w))
with switching(k, "they chose to take a shower"):
    k["activity"] = occupy(k, w, act("take_shower", w))
check("a decision to do something else ends the running one first: no clash",
      k["activity"]["type"] == "take_shower" and not w.get("activity_clashes"))

w, k = setup()
k["activity"] = occupy(k, w, act("use_toilet", w))
k["activity"]["_completed"] = True          # complete_activity ran: only the finishing animation is left
k["activity"] = occupy(k, w, act("sleep", w))
check("what a completion starts next (back to bed) is not a clash", k["activity"]["type"] == "sleep"
      and not w.get("activity_clashes"))

w, k = setup()
k["activity"] = occupy(k, w, act("eat_meal", w, phase="finishing"))
k["activity"] = occupy(k, w, act("wash_dishes", w))
check("nor is starting something during the one-tick finishing animation", k["activity"]["type"] == "wash_dishes")

# ---- B: envy only when brought to mind -----------------------------------------------------------------------------
from systems import life_comparison as lc
w, k = setup()
r = w["characters"]["robert"]
for c in (k, r):
    c.update(age=40, age_group="adult")
k.setdefault("relationships", {})["robert"] = {"familiarity": 0.6}
compared = []
lc._apply_comparison = lambda c, other, world, trigger=None: compared.append((c["id"], other["id"], trigger))

lc.on_reminded_event(w, "person_entered_view", {"observer_id": "kathleen", "subject_id": "robert"})
check("seeing him brings his life to mind, and says so", compared and compared[-1][2]["kind"] == "saw"
      and compared[-1][2]["detail"].startswith("saw Robert"), str(compared))
lc.on_reminded_event(w, "person_entered_view", {"observer_id": "kathleen", "subject_id": "robert"})
check("... but not again minutes later", len(compared) == 1)
w["tick"] += lc.REMINDER_COOLDOWN_SECONDS
lc.on_reminded_event(w, "speech_spoken", {"character_id": "susan", "target_id": "kathleen",
                                           "utterance": "Robert got a new car, did you hear?"})
check("hearing him mentioned (after the cooldown) does, with the line on the record",
      len(compared) == 2 and compared[-1][2]["kind"] == "mentioned" and "new car" in compared[-1][2]["detail"],
      str(compared[-1:]))
w["tick"] += lc.REMINDER_COOLDOWN_SECONDS
lc.on_reminded_event(w, "guest.visit_started", {"guest_id": "kathleen", "host_ids": ["robert"]})
check("visiting his home does", compared[-1][2]["kind"] == "visiting")
w["tick"] += lc.REMINDER_COOLDOWN_SECONDS
lc.on_reminded_event(w, "person_entered_view", {"observer_id": "kathleen", "subject_id": "joseph"})
check("a stranger's life is not compared", len(compared) == 3)

import core.flow as flow
check("no clock runs the comparison any more", flow.job("life_comparison")["kind"] == "event"
      and set(flow.job("life_comparison")["on"]) == {"person_entered_view", "speech_spoken", "guest.visit_started"})

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
