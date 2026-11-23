"""
Characters who never got to think (live 2026-11-23): between two activities the intentions loop in update_agent
started the next errand and returned before the cognition gate. 44 model requests in 3,485 ticks for 11 characters;
Anthony not once in 18,000 ticks, cooking for a child who was at school. Now:

A. A character due to think -- woken by something, or ten sim-minutes on autopilot -- thinks before the next errand.
B. Not for an urgent body need, and not while a request is already out.
C. While the decision is out, the autopilot holds off for a short while (DECISION_HOLD_TICKS), not for ever.

Run inside the backend container:   python tests/test_think_starvation.py
"""
import os, sys, time
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

from brain import agent_loop as al

def char(**cog):
    base = {"next_think_tick": 0, "last_think_tick": 0, "wake_reason": None, "pending": None}
    base.update(cog)
    return {"id": "a", "name": "Anthony", "body": {}, "cognition": base}

w = {"tick": 1000, "characters": {}}

check("A: woken by something that happened -> thinks first",
      al._think_overdue(char(wake_reason="heard_speech", last_think_tick=990), w))
check("A: routine wake, thought recently -> autopilot carries on",
      not al._think_overdue(char(wake_reason="activity_finished", last_think_tick=900), w))
check("A: routine wake, ten minutes on autopilot -> thinks",
      al._think_overdue(char(wake_reason="activity_finished", last_think_tick=1000 - al.THINK_STARVED_TICKS), w))
check("A: not due yet -> no", not al._think_overdue(char(wake_reason="heard_speech", next_think_tick=1500), w))

hungry = char(wake_reason="house_guest", last_think_tick=990); hungry["body"] = {"hunger": 95}
check("B: an urgent need is left to the autopilot", not al._think_overdue(hungry, w))
starving = char(wake_reason="activity_finished", last_think_tick=1000 - al.THINK_STARVED_TICKS); starving["body"] = {"hunger": 100}
check("B: ...unless ten minutes went by without them thinking", al._think_overdue(starving, w))
out = char(wake_reason="house_guest", pending={"id": "r1", "tick": 995, "wall": time.time()})
check("B: a request already out -> not asked again", not al._think_overdue(out, w))

check("C: holds while the request is fresh", al._holding_for_decision(out, w))
old = char(pending={"id": "r2", "tick": 1000 - al.DECISION_HOLD_TICKS - 1, "wall": time.time()})
check("C: ...but not for ever", not al._holding_for_decision(old, w))
check("C: nothing out -> no hold", not al._holding_for_decision(char(), w))

# D. A plan's next step doesn't start straight from the activity_finished event while they're overdue to think.
from brain.actionplans import runner
ran = []
runner._run = lambda c, world, iid, att, intention, came_out=None, at=None: ran.append(iid)
runner.store.get = lambda data, kind, iid: {"id": iid}
def planner(**cog):
    c = char(**cog); c["activity"] = None
    c["plan_attempts"] = {"feed_kids": {"waiting_activity": {"id": "n1"}, "activity_type": "cook_recipe"}}
    w["characters"] = {"a": c}
    return c
p = planner(wake_reason="activity_finished", last_think_tick=1000 - al.THINK_STARVED_TICKS)
runner.on_activity_end({"character_id": "a", "activity_type": "cook_recipe"}, w, "done")
check("D: overdue -> the next step waits for them to think", not ran and p["plan_attempts"]["feed_kids"].get("resume"))
p = planner(wake_reason="activity_finished", last_think_tick=990)
runner.on_activity_end({"character_id": "a", "activity_type": "cook_recipe"}, w, "done")
check("D: thought recently -> the plan carries straight on", ran == ["feed_kids"], ran)

print("\n" + ("all passed" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
