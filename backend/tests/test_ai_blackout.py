"""
When the AI can't answer for a character (systems/ai_blackout.py): no stand-in decision -- they can't think straight.
After 10 minutes of it, an episode that snowballs; a kind word calms it; at the top, a crisis, the ambulance, a night in
hospital.

Run:   python tests/test_ai_blackout.py
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
import core.event_handlers  # noqa: F401
from core import event_bus, scheduler
from systems import ai_blackout as A
from brain.agent_loop import process_decision

w = make_world()
w["tick"] = 50000
r = w["characters"]["robert"]
k = w["characters"]["kathleen"]
r.update(memories=[], activity=None)
FAIL = {"action": {"type": "wait", "fallback": True, "reason": "Timed out waiting for the model."}}

process_decision(r, w, dict(FAIL, action=dict(FAIL["action"])))
check("the AI fails: no stand-in plan, a short lost line instead", (r.get("current_speech") or {}).get("utterance")
      in A._LOST + [x[2] for x in A._THOUGHTS if x[2]] and r.get("last_thought") in [x[1] for x in A._THOUGHTS],
      str((r.get("current_speech"), r.get("last_thought"))))
check("... no episode yet", not A.in_episode(r))

for _ in range(12):
    w["tick"] += 60
    process_decision(r, w, dict(FAIL, action=dict(FAIL["action"])))
check("still failing after 10 minutes: an episode", A.in_episode(r) and r["psychosis_state"]["trigger"] == "ai_blackout")
i0 = r["psychosis_state"]["intensity"]
for _ in range(10):
    w["tick"] += 60
    scheduler.fire_due(w)
    process_decision(r, w, dict(FAIL, action=dict(FAIL["action"])))
check("... it snowballs while the AI still isn't answering", r["psychosis_state"]["intensity"] > i0 + 0.15,
      str(r["psychosis_state"]))

before = r["psychosis_state"]["intensity"]
A.on_line({"speaker_id": "kathleen", "target_id": "robert", "speech_act": "comfort", "social": {"intent": "comfort"}}, w)
check("someone comforts him: it eases", r["psychosis_state"]["intensity"] < before)
A.on_line({"speaker_id": "kathleen", "target_id": "robert", "speech_act": "insult", "social": {"intent": "provoke"}}, w)
check("... a jibe doesn't", r["psychosis_state"]["intensity"] == round(before - A.CALM_PER_LINE, 3))

process_decision(r, w, {"action": {"type": "wait", "reason": "fine"}, "thought": "ok"})
check("the AI answers again: the streak is over, but the episode doesn't just stop", A.in_episode(r)
      and "_ai_blackout" not in r)

r["psychosis_state"]["intensity"] = A.CRISIS_INTENSITY + 0.01
r["_ai_blackout"] = {"since": w["tick"], "failures": 1, "last": w["tick"]}
A._grow(r, w)
inc = next((i for i in w.get("incidents", []) if i["id"] == r["psychosis_state"].get("incident_id")), None)
check("at the top: a mental-health crisis incident anyone around can call in", inc and inc["type"] == "mental_health_crisis")

w.setdefault("responders", []).append({"id": "amb_1", "type": "medical", "status": "en_route", "arrival_tick": w["tick"],
                                       "location": {"x": r["x"], "y": r["y"]}, "incident_id": inc["id"]})
from systems.emergency import resolve
resolve(w)
check("the ambulance takes him to spend the night in hospital", r.get("off_grid") and r.get("off_grid_reason") == "hospital",
      str((r.get("off_grid"), r.get("off_grid_reason"))))
A.on_hospital_return(r, w)
check("... and when he's back, it's over", not A.in_episode(r))

for _ in range(3):
    A.calm(k, w, "robert")
check("calming someone who isn't in an episode does nothing", not A.in_episode(k))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
