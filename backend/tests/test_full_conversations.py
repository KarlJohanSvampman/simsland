"""
Conversations that ended after the first reply (live 2026-11-23: a third of answered conversations were 2-3 lines --
"when someone replies we expect a real conversation, or an explanation"):

A. An answer that asks something back, or explains at length, doesn't settle the conversation ("resolved").
B. A short yes / no / later still does.
C. The limits leave room: CPL's defaults, the backstops, the idle sweep.
D. A young conversation's prompt asks for a real answer, not a one-liner.

Run inside the backend container:   python tests/test_full_conversations.py
"""
import os, sys
os.environ["CPL_MODE"] = "off"            # the older ending rules (systems/conversation_outcome.py) are what's checked in A/B
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

from house_world import make_world
from brain import intentions as intents
from brain.conversations import get_or_create_conversation, add_message
from systems import conversation_outcome as co


def setup():
    w = make_world()
    w["tick"] = 20000
    w["calendar"] = {"year": 2026, "month": 11, "day": 1, "hour": 15, "minute": 0, "second": 0,
                     "minute_of_day": 900, "weekday": "Sunday"}
    w["conversations"] = {}
    intents.set_current_tick(w["tick"])
    k, s = w["characters"]["kathleen"], w["characters"]["susan"]
    for c in (k, s):
        c.update(memories=[], active_intentions=[])
    s.update(x=k["x"] + 1, y=k["y"], building_id=k.get("building_id"))
    conv = get_or_create_conversation(w, ["kathleen", "susan"], topic="general", medium="in_person")
    conv["started_at"] = w["tick"]
    return w, conv


def say(w, conv, who, line, act="declare", dt=5):
    w["tick"] += dt
    add_message(w, conv, who, line, act, "general", w["tick"])


w, conv = setup()
say(w, conv, "kathleen", "Daniel, can we talk about what happened at dinner?", "ask")
say(w, conv, "susan", "Sorry, but I think you're trying to change the subject. What's going on with Rachel?")
check("A: 'Sorry, ... ?' asks back -> not settled", not conv.get("outcome") and conv.get("active"))

w, conv = setup()
say(w, conv, "kathleen", "Are you coming to the party tonight?", "ask")
say(w, conv, "susan", "Okay, so the thing is I promised my mum I'd help her move the old sofa out of the garage first, "
                      "and that always takes ages")
check("A: a long explanation -> not settled", not conv.get("outcome"))

w, conv = setup()
say(w, conv, "kathleen", "Are you coming to the party tonight?", "ask")
say(w, conv, "susan", "Sorry, I can't.", "decline")
check("B: a short no still settles it", (conv.get("outcome") or {}).get("verdict") == "no", conv.get("outcome"))

from cpl import policies
from brain import conversations as convs
check("C: CPL's default gives a talk room", policies.DEFAULT["max_lines"] >= 12 and policies.DEFAULT["max_seconds"] >= 600
      and policies.DEFAULT["reply_s"] >= 120 and policies.DEFAULT["idle_s"] >= 300)
check("C: the backstops are backstops", co.MAX_LINES >= 20 and co.NO_REPLY_TICKS >= 180 and convs.IDLE_TIMEOUT_SECONDS >= 300)

from cpl.turns import prompt_section, YOUNG_LINES
young = prompt_section({"with": ["Anthony"], "open": [], "lines": 2})
check("D: a young conversation asks for a real answer", "not a one-liner" in young, young)
check("D: ...not once it has got going", "not a one-liner" not in prompt_section({"with": ["A"], "open": [], "lines": YOUNG_LINES}))
check("D: ...nor while winding down", "not a one-liner" not in prompt_section({"with": ["A"], "open": [], "lines": 1,
                                                                             "winding_down": True}))

print("\n" + ("all passed" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
