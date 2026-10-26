"""
An activity carries its own steps and timeline and is remembered once, whole; a chore is not cut short by a late answer from the model;
every activity has a finite length and the watchdog has a ceiling (systems/activity_trace.py, activity_guard.py, activity_watchdog.py,
occupancy.py::interrupt_activity).

Run inside the backend container:   python tests/test_activity_trace.py
"""

import os
import sys
from unittest import mock

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import core.event_handlers  # noqa: F401
from systems import activity_guard, activity_trace, activity_watchdog
from systems.activities import ACTIVITIES, set_activity_phase
from systems.occupancy import interrupt_activity

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def world(tick=1000):
    return {"tick": tick, "calendar": {"hour": 15, "minute": 12}, "props": [], "characters": {}}


def char(activity=None, **extra):
    c = {"id": "k", "name": "Karim", "age": 41, "activity": activity, "active_intentions": [], "posture": "standing"}
    c.update(extra)
    return c


def walking(kind="take_out_trash", duration=300, tick=1000):
    return {"type": kind, "phase": "walking", "phase_started_tick": tick, "duration": duration, "target_id": None, "anchor_name": "anchor_x", "state": {}}


memories = []
with mock.patch("brain.memory.store_memory", lambda c, text, **kw: memories.append((text, kw))):
    # ---- the trace --------------------------------------------------------------------------------------------------------------------------
    w = world()
    c = char(walking())
    activity_trace.begin(c, w)
    act = c["activity"]
    check("a new activity gets its plan and an empty-but-started timeline", [s["name"] for s in act["steps"]] == ["walk", "use", "finish"]
          and act["timeline"][0]["step"] == "started", str(act.get("steps")))
    w["tick"] = 1040
    set_activity_phase(act, "using", w)
    check("arriving ticks the walk off, at the tick it happened", act["steps"][0]["done_tick"] == 1040 and act["steps"][1]["done_tick"] is None)
    w["tick"] = 1340
    set_activity_phase(act, "finishing", w)
    check("finishing ticks the using step off", act["steps"][1]["done_tick"] == 1340)
    activity_trace.close(c, w, "completed")
    check("the whole activity is remembered ONCE", len(memories) == 1 and memories[0][1].get("kind") == "activity", str(memories))
    rec = memories[0][1]["activity_record"]
    check("... with the plan all ticked off, the timeline and how long it took", all(s["done_tick"] for s in rec["steps"]) and rec["actual_ticks"] == 340
          and rec["outcome"] == "completed" and rec["timeline"][-1]["step"] == "completed", str(rec))
    activity_trace.close(c, w, "completed")
    check("closing twice writes nothing more", len(memories) == 1)

    # ---- an interruption says why ------------------------------------------------------------------------------------------------------
    memories.clear()
    w = world(2000)
    c = char(walking("wash_dishes", 300, 2000))
    activity_trace.begin(c, w)
    w["tick"] = 2120
    interrupt_activity(c, w, reason="a hungry child was waiting")
    check("an interrupted activity is closed with the reason, in one memory", len(memories) == 1 and memories[0][1]["activity_record"]["reason"] == "a hungry child was waiting"
          and memories[0][1]["activity_record"]["outcome"] == "interrupted" and "a hungry child" in memories[0][0], str(memories))
    check("... and the character is free", c["activity"] is None)

    memories.clear()
    c = char(walking("wash_dishes", 300, 2000))
    activity_trace.begin(c, w)
    c["_interrupt_reason"] = "they chose to sit and relax"
    interrupt_activity(c, w)
    check("a reason left by the decision is the one recorded", "they chose to sit and relax" in memories[0][0], memories[0][0])

    memories.clear()
    c = char(walking("wash_dishes", 300, 2000))
    activity_trace.begin(c, w)
    interrupt_activity(c, w)
    check("with no reason given, the caller is named (never blank)", "cut off by" in memories[0][0] or "test_activity_trace" in memories[0][0], memories[0][0])

    # a replacement that nothing closed is closed when the next one begins
    memories.clear()
    c = char(walking("wash_dishes", 300, 2000))
    activity_trace.begin(c, w)
    c["activity"] = walking("sit_in_park", 600, 2200)
    activity_trace.begin(c, w)
    check("an activity replaced without ceremony is still recorded", len(memories) == 1 and memories[0][1]["activity_record"]["outcome"] == "replaced", str(memories))

    # the bubble and timeline, but no memory per step
    memories.clear()
    from systems.debug_log import log_activity
    c = char(walking())
    activity_trace.begin(c, w)
    log_activity(c, w, "take_out_trash", "reached target, interaction begun")
    check("a step is a timeline entry, not a memory", not memories and c["activity"]["timeline"][-1]["step"] == "reached target, interaction begun")

# ---- through the real event, with the real ordering, a timeline has its plan, its start and each entry once ---------------------------------------------
from core.event_handlers import _on_activity_started
from systems.activities import finish_activity
memories.clear()
with mock.patch("brain.memory.store_memory", lambda c, text, **kw: memories.append((text, kw))):
    w = world(7000)
    c = char(walking("take_out_trash", 300, 7000))
    w["characters"]["k"] = c
    _on_activity_started({"character_id": "k", "activity_type": "take_out_trash", "target_id": None}, w)
    check("the started event leaves the plan and the real start tick", [s["name"] for s in c["activity"]["steps"]] == ["walk", "use", "finish"]
          and c["activity"]["started_tick"] == 7000 and len(c["activity"]["timeline"]) == 1)
    w["tick"] = 7030
    set_activity_phase(c["activity"], "using", w)
    w["tick"] = 7330
    set_activity_phase(c["activity"], "finishing", w)
    finish_activity(c, w)
    rec = memories[0][1]["activity_record"] if memories else {}
    check("a finished activity records its true length (330 ticks, not the last phase)", rec.get("actual_ticks") == 330, str(rec.get("actual_ticks")))
    check("... with one 'started' and one closing entry", [t["step"] for t in rec.get("timeline", [])].count("started") == 1
          and [t["step"] for t in rec.get("timeline", [])][-1] == "completed", str(rec.get("timeline")))

# ---- a chore is not cut short by a late answer ---------------------------------------------------------------------------------------------
w = world(5000)
chore = {"type": "take_out_trash", "phase": "using", "phase_started_tick": 4900, "duration": 300, "target_id": "p", "state": {}}
check("a chore with time left is committed", activity_guard.committed_remaining(char(chore), w) is not None)
reason = activity_guard.defer_reason(char(chore), w, {"type": "interact", "target": "chair"})
check("a late decision to do something else is deferred, and says what they kept doing", reason and "take out trash" in reason, str(reason))
check("... but speaking, or the phone, still goes through", not activity_guard.defer_reason(char(chore), w, {"type": "speak"})
      and not activity_guard.defer_reason(char(chore), w, {"type": "phone_call"}))
check("an urgent need (an intention that interrupts) goes through", not activity_guard.defer_reason(
    char(chore, active_intentions=[{"type": "eat_food", "interrupts": True, "strength": 1}]), w, {"type": "eat"}))
relax = {"type": "sit_and_relax", "phase": "using", "phase_started_tick": 4900, "duration": 1800, "target_id": "p", "state": {}}
check("leisure is never committed", activity_guard.defer_reason(char(relax), w, {"type": "interact"}) is None)
done = dict(chore, phase_started_tick=4000)
check("a chore past its time is not held on to", activity_guard.defer_reason(char(done), w, {"type": "interact"}) is None)

# ---- everything has a finite length ---------------------------------------------------------------------------------------------------------
bad = [k for k, v in ACTIVITIES.items() if not isinstance(v.get("base_duration_minutes"), (int, float)) or not 0 < v["base_duration_minutes"] <= 480]
check("every activity has a duration between 1 minute and 8 hours", not bad, str(bad))
from systems.action_router import _INTERACTION_DURATIONS
badi = [k for k, v in _INTERACTION_DURATIONS.items() if not isinstance(v, (int, float)) or not 0 < v <= 8 * 3600]
check("every routed interaction has one too", not badi, str(badi))
check("an activity with no duration at all is still cut off (an hour)", activity_watchdog._limit({"phase": "using"}) == activity_watchdog.NO_DURATION_LIMIT_TICKS)
check("a long one is never allowed more than two hours over", activity_watchdog._limit({"phase": "using", "duration": 28800}) == 28800 + activity_watchdog.MAX_OVERRUN_TICKS)
check("a short chore gets ten minutes of slack at most", activity_watchdog._limit({"phase": "using", "duration": 300}) == 900)

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
