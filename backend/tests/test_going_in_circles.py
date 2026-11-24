"""
Conversations going round in circles (live 2026-11-23: Alexander and Margaret, four conversations in a quarter of an
hour about one remark, Margaret apologising four times in near-identical words).

A. A line nearly the same as one the speaker just said to the same listener is dropped, and they're told.
B. Short lines and genuinely different ones are not.
C. Three or more conversations with the same person in half an hour: the prompt says so.

Run inside the backend container:   python tests/test_going_in_circles.py
"""
import os, sys
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")

failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

from systems.speech_repeat import near_repeat
w = {"tick": 1000, "characters": {"a": {"id": "a", "name": "Alexander"}}}
m = {"id": "m", "name": "Margaret", "speech_log": [
    {"tick": 990, "target": "a", "utterance": "Alexander, I think I was feeling a bit overwhelmed and didn't think about "
                                              "how my words might affect you. I was trying to be honest about my own state."}]}
again = ("I was feeling overwhelmed and didn't think about how my words might affect you, I was trying to be honest "
         "about my own state but I shouldn't have made that comment")
check("A: nearly the same apology again -> a near repeat", near_repeat(m, w, again, "a"))
check("B: to someone else -> not", not near_repeat(m, w, again, "x"))
check("B: something different -> not", not near_repeat(m, w, "Would you like to help me water the garden later today?", "a"))
check("B: a short line -> not", not near_repeat(m, w, "I'm sorry, Alexander.", "a"))

import cpl.participants as parts
import brain.cognition_scheduler as cs
told = []
cs.wake_character = lambda c, world, reason, payload=None, delay=0: told.append((c["id"], reason))
check("A: repeat_dropped drops it", parts.repeat_dropped(m, w, again, "a"))
check("A: ...and the speaker is told", told == [("m", "cant_talk")], told)

from brain.context_builder import _sec_going_in_circles
c = {"id": "m", "conversation_log": [{"started_tick": t, "participants": ["m", "a"]} for t in (100, 400, 700)]}
w2 = {"tick": 900, "characters": {"a": {"name": "Alexander"}}}
line = _sec_going_in_circles(c, w2)
check("C: three talks in half an hour -> the prompt says so", "Alexander" in line and "3 times" in line, line)
c["conversation_log"][0]["started_tick"] = -5000
check("C: two -> nothing", not _sec_going_in_circles(c, w2))

print("\n" + ("all passed" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
