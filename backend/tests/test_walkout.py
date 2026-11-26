"""
Nobody walks off in the middle of a conversation without it meaning something (live 2026-11-25: Anthony and Alexander
argued for five lines, Anthony asked "What's going on?" and Alexander had gone -- no word, no thought, no follow-up).

A. Walking off without a closing line: a walk-out is recorded and the leaver is asked why (walked_out).
B. A closing line ("I've got to go") from either side: no walk-out.
C. Who left: the one asleep / gone, else the one who moved, else the one who didn't speak last.
D. The leaver's answer: the thought is kept; a text to the other settles it.
E. No word from the leaver: after FOLLOW_UP_TICKS the one left behind is asked to text or call; their message settles it.
F. A deliberate leave_conversation counts as leaving; "text" with a recipient and a message sends a text.
G. In a conversation, the prompt says to say so before leaving.

Run inside the backend container:   python tests/test_walkout.py
"""
import os, sys
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")

failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

import brain.cognition_scheduler as cs
woken = []
cs.wake_character = lambda c, world, reason, payload=None, delay=0: woken.append((c["id"], reason, (payload or {}).get("line", "")))
from systems import walkout as W

def make_world():
    return {"tick": 1000, "characters": {
        "ant": {"id": "ant", "name": "Anthony Carter", "x": 5, "y": 5, "_in_building": "h1", "activity": {"type": "interact"}},
        "alex": {"id": "alex", "name": "Alexander Carter", "x": 30, "y": 5, "_in_building": "h1", "activity": {"type": "drink_water"}}},
        "conversations": {}}

def conv(lines, **kw):
    c = {"id": "cv", "participants": ["ant", "alex"], "end_reason": "left", "active": False,
         "history": [{"speaker": s, "utterance": u, "tick": i} for i, (s, u) in enumerate(lines)],
         "_start_pos": {"ant": [5, 5, "h1"], "alex": [6, 5, "h1"]}}
    c.update(kw)
    return c

ARGUMENT = [("ant", "What's got into you, Alex?"), ("alex", "You came in without knocking!"),
            ("ant", "Come on, stop getting defensive."), ("alex", "Why are you yelling at me?"),
            ("ant", "What's going on?")]

# A
w = make_world(); woken.clear()
rec = W.note(w, conv(ARGUMENT))
check("A: a walk-out is recorded, Alexander left Anthony", rec and rec["leaver"] == "alex" and rec["left"] == "ant", rec)
check("A: the leaver is asked why (walked_out), told to text or think it",
      woken and woken[0][:2] == ("alex", "walked_out") and "text" in woken[0][2] and "going in circles" in woken[0][2], woken)
check("A: the stats count it", w["walkout_stats"]["walked_out"] == 1)

# B
w = make_world(); woken.clear()
check("B: the leaver said they had to go -> no walk-out",
      W.note(w, conv(ARGUMENT[:4] + [("alex", "I've got to go, we'll talk later.")])) is None and not woken)
check("B: the other said bye -> no walk-out",
      W.note(w, conv(ARGUMENT[:4] + [("ant", "Fine, see you later.")])) is None and w["walkout_stats"]["closed_properly"] == 2)
check("B: settled conversations, single unanswered calls, other end reasons: not walk-outs",
      W.note(w, conv(ARGUMENT, outcome={"verdict": "yes"})) is None
      and W.note(w, conv([("ant", "Rachel, food's ready!"), ("ant", "Rachel?")])) is None
      and W.note(w, conv(ARGUMENT, end_reason="timed_out")) is None)
check("B: a closing line is recognised", W.closes("Sorry, I need some space.") and W.closes("Bye!") and not W.closes("I'll do it later."))

# C
w = make_world()
w["characters"]["ant"]["activity"] = {"type": "sleep"}
check("C: the one who fell asleep left", W.leaver_of(w, conv(ARGUMENT)) == "ant")
w = make_world()
check("C: else the one who moved away", W.leaver_of(w, conv(ARGUMENT)) == "alex")
w = make_world()
check("C: else the one who didn't speak last", W.leaver_of(w, conv(ARGUMENT, _start_pos={})) == "alex")
check("C: what the ending recorded wins", W.leaver_of(w, conv(ARGUMENT, left_by="ant")) == "ant")

# D
w = make_world(); woken.clear()
rec = W.note(w, conv(ARGUMENT))
W.after_decision(w["characters"]["alex"], w, {"thought": "This conversation was just going in circles.", "action": {"type": "drink_water"}})
check("D: the thought is kept, still open", rec["thought"].startswith("This conversation") and rec["status"] == "open", rec)
W.after_decision(w["characters"]["alex"], w, {"thought": "I'll tell him.",
                 "action": {"type": "phone_send_text", "target_id": "ant", "message": "Sorry, I needed air."}})
check("D: texting the other settles it (told)", rec["status"] == "done" and rec["outcome"] == "told" and w["walkout_stats"]["told"] == 1, rec)

# E
w = make_world(); woken.clear()
rec = W.note(w, conv(ARGUMENT)); woken.clear()
w["tick"] += 60; W.sweep(w)
check("E: no follow-up before FOLLOW_UP_TICKS", not woken and rec["follow_up_tick"] is None)
w["tick"] = rec["tick"] + W.FOLLOW_UP_TICKS; W.sweep(w)
check("E: then the one left behind is asked to text or call",
      woken and woken[-1][:2] == ("ant", "walkout_follow_up") and "phone_send_text" in woken[-1][2] and "Alexander" in woken[-1][2], woken)
woken.clear(); w["tick"] += 60; W.sweep(w)
check("E: asked once", not woken)
w["characters"]["ant"]["speech_log"] = [{"tick": w["tick"], "target": "alex", "utterance": "Hey, what happened back there?"}]
w["tick"] += 60; W.sweep(w)
check("E: their message settles it (followed_up)", rec["outcome"] == "followed_up", rec)
w = make_world(); rec = W.note(w, conv(ARGUMENT))
w["characters"]["alex"]["speech_log"] = [{"tick": w["tick"] + 5, "target": "ant", "utterance": "Sorry about that."}]
w["tick"] += 60; W.sweep(w)
check("E: the leaver speaking to them on their own settles it too (told)", rec["outcome"] == "told", rec)
w = make_world(); w["characters"]["ant"]["activity"] = {"type": "sleep"}
w["characters"]["ant"]["x"] = 5
rec = W.note(w, conv(ARGUMENT, left_by="alex")); woken.clear()
w["tick"] = rec["tick"] + W.FOLLOW_UP_TICKS; W.sweep(w)
check("E: not while the one left behind sleeps", not any(r == "walkout_follow_up" for _, r, _ in woken))
w["tick"] = rec["tick"] + W.EXPIRE_TICKS; W.sweep(w)
check("E: let go after EXPIRE_TICKS", rec["status"] == "done")

# F
from systems import action_router as ar
import brain.conversations as BC
c2 = conv(ARGUMENT, end_reason=None, active=True); c2.pop("end_reason")
BC.find_active_conversation_for = lambda world, cid: c2
archived = []
BC._archive_conversation = lambda world, cv: archived.append(dict(cv))
w = make_world()
ar._route_leave_conversation(w["characters"]["alex"], w, {"type": "leave_conversation"})
check("F: leave_conversation records who left and why it ended", archived and archived[0].get("left_by") == "alex"
      and archived[0].get("end_reason") == "left", archived)
sent = []
ar._route_phone_send_text = lambda c, world, action: sent.append(("text", action.get("message")))
ar._route_phone_check = lambda c, world, action: sent.append(("check", None))
ar._route_phone_call = lambda c, world, action: sent.append(("call", None))
src = open(ar.__file__).read()
check("F: 'text' with a recipient and message routes to a text, 'call' with a recipient to a call",
      'action_type == "text" and (action.get("target_id")' in src and 'action_type == "call" and (action.get("target_id")' in src)

# G
w = make_world()
w["conversations"] = {"cv": {"active": True, "participants": ["ant", "alex"], "history": ARGUMENT[:2]}}
line = W.prompt_line(w, w["characters"]["alex"])
check("G: in a conversation: say so before leaving", line and "before you leave" in line, line)
w = make_world(); W.note(w, conv(ARGUMENT))
check("G: the leaver is reminded they owe an explanation", "without saying why" in (W.prompt_line(w, w["characters"]["alex"]) or ""))
check("G: the summary lists it", W.summary(w)["recent"][0]["leaver"] == "Alexander Carter")

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
