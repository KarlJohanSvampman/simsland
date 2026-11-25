"""
Two people talking, not one talking at the other (live 2026-11-25: the person addressed answered once or twice and went
quiet while the other kept talking -- counting lines hid it).

A. Scoring a finished conversation: unanswered / one_sided / lopsided / short / balanced, and who went quiet.
B. A third line in a row with no answer isn't said; the speaker is told.
C. A line that calls the speaker by their own name (the other person's line, written by mistake) isn't said.
D. Spoken to and deciding on something that doesn't answer: asked once more (owe_answer), once per line.
E. Owing an answer is time-limited, and ends when they answer.

Run inside the backend container:   python tests/test_conversation_health.py
"""
import os, sys
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")

failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

from systems import conversation_health as H

def entry(*speakers):
    return {"id": "c", "participants": ["a", "b"], "lines": [{"speaker": s, "utterance": "x", "tick": i} for i, s in enumerate(speakers)]}

check("A: nobody replied -> unanswered", H.score(entry("a", "a"))["kind"] == "unanswered")
s = H.score(entry("a", "b", "a", "a", "a"))
check("A: replied once, then only the opener -> one_sided, b went quiet", s["kind"] == "one_sided" and s["quiet"] == "b", s)
check("A: 7 to 2 after the reply -> lopsided", H.score(entry("a", "b", "a", "a", "b", "a", "a", "a", "a", "b", "a"))["kind"] == "lopsided")
check("A: back and forth -> balanced", H.score(entry("a", "b", "a", "b", "a", "b"))["kind"] == "balanced")
check("A: a reply and nothing more -> short", H.score(entry("a", "b"))["kind"] == "short")
w = {"tick": 0}
H.note(w, entry("a", "b", "a", "a", "a")); H.note(w, entry("a", "b", "a", "b"))
sm = H.summary(w)
check("A: the summary counts and shares", sm["counts"]["one_sided"] == 1 and sm["answered"] == 2 and sm["one_sided_share"] == 0.5, sm)

# B / C: in apply_speech
import brain.conversations as BC
import brain.cognition_scheduler as cs
told = []
cs.wake_character = lambda c, world, reason, payload=None, delay=0: told.append((c["id"], reason, (payload or {}).get("line", "")))
from systems import action_router as ar
conv = {"id": "cv", "active": True, "participants": ["ant", "alex"], "medium": "in_person",
        "history": [{"speaker": "ant", "utterance": "What's going on?", "tick": 1}, {"speaker": "alex", "utterance": "Nothing!", "tick": 2},
                    {"speaker": "ant", "utterance": "Come on, tell me.", "tick": 3}, {"speaker": "ant", "utterance": "Alexander?", "tick": 4}]}
BC.find_conversation = lambda world, ids: conv if set(ids) == {"ant", "alex"} else None
world = {"tick": 10, "characters": {"ant": {"id": "ant", "name": "Anthony Carter"}, "alex": {"id": "alex", "name": "Alexander Carter"}}}
ant = world["characters"]["ant"]
check("B: two unanswered lines in a row -> the third isn't said", ar._talking_into_silence(ant, world, "alex"))
check("B: ...and Anthony is told", told and told[-1][:2] == ("ant", "cant_talk") and "hasn't answered" in told[-1][2], told[-1:])
conv["history"].append({"speaker": "alex", "utterance": "Fine.", "tick": 5})
check("B: once Alexander answers, Anthony may speak", not ar._talking_into_silence(ant, world, "alex"))
check("C: 'It's not just about your entry, Anthony.' from Anthony -> not said",
      ar._speaking_as_other(ant, world, "alex", "It's not just about your entry, Anthony. It's how you treat me."))
check("C: an ordinary line is fine", not ar._speaking_as_other(ant, world, "alex", "Alexander, tell me what's wrong."))
check("C: saying who you are is fine", not ar._speaking_as_other(ant, world, "alex", "I'm Anthony and I live next door."))

# D / E: owing an answer, and the nudge
BC.find_active_conversation_for = lambda world, cid: conv if cid in conv["participants"] else None
conv["history"].append({"speaker": "ant", "utterance": "So what's really going on?", "tick": 9})
alex = world["characters"]["alex"]
check("E: Alexander owes Anthony an answer", H.owes_answer(world, alex) is not None)
check("E: Anthony owes nothing", H.owes_answer(world, ant) is None)
from brain import cognition_actor as ca
told.clear()
ca._nudge_if_unanswered(alex, world, {"action": {"type": "examine"}})
check("D: deciding to examine something instead -> asked to answer", told and told[-1][1] == "owe_answer" and "waiting for your answer" in told[-1][2], told)
ca._nudge_if_unanswered(alex, world, {"action": {"type": "examine"}})
check("D: once per line", len(told) == 1, told)
told.clear()
alex.pop("_nudged_line", None)
ca._nudge_if_unanswered(alex, world, {"action": {"type": "speak"}, "speech": {"utterance": "I'm upset."}})
check("D: answering -> no nudge", not told)
world["tick"] = 9 + H.OWE_TICKS + 1
check("E: after a while it lapses", H.owes_answer(world, alex) is None)

print("\n" + ("all passed" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
