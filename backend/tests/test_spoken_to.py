"""
Listeners who never answered (live 2026-11-21: 93 of 99 conversations in a morning were one line nobody answered).
The listener was woken ("heard_speech") but never thought: they were dusting / eating / washing up (only a few
"listening" activities could answer), walking somewhere, or their own errands started first -- and a stronger wake
("provoked") hid being spoken to. Now:

A. Being spoken to is kept apart from wake_reason (cog["spoken_to"]) -- a stronger wake can't hide it.
B. Anyone may answer while busy, except asleep / in the shower or bath / on the toilet.
C. Starting one of those ends the conversation they're in as "unavailable" (cpl/lifecycle.py).

Run inside the backend container:   python tests/test_spoken_to.py
"""
import os, sys
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

from brain.cognition_scheduler import wake_character, spoken_to_due, wake_line, note_think
from brain.agent_loop import _spoken_to_while_busy

def char(cid, name, act=None):
    return {"id": cid, "name": name, "cognition": {"next_think_tick": 999999}, "activity": {"type": act} if act else None}

w = {"tick": 100, "characters": {}}
b = char("b", "Brenda")
wake_character(b, w, "provoked", {"actor_name": "Carol", "verb_phrase": "insulted", "reaction_hint": ""})
wake_character(b, w, "heard_speech", {"speaker_name": "Steven", "utterance": "Can I have something to eat?"})
check("A: a provoked wake still wins wake_reason", b["cognition"]["wake_reason"] == "provoked")
check("A: ...but being spoken to is remembered", spoken_to_due(b, w))
check("A: ...and the prompt still carries the line", "Can I have something to eat?" in (wake_line(b) or ""), wake_line(b))
seq = b["cognition"]["wake_seq"]
note_think(b, w, {"action": {"type": "speak"}}, wake_reason="provoked", asked_at_seq=seq - 1)
check("A: a decision asked before the line leaves it pending", bool(b["cognition"].get("spoken_to")))
note_think(b, w, {"action": {"type": "speak"}}, wake_reason="provoked", asked_at_seq=seq)
check("A: a decision asked after the line clears it", not b["cognition"].get("spoken_to"))

for act, want in (("dust_and_wipe", True), ("eat", True), ("wash_dishes", True), ("socialize", True),
                  ("take_shower", False), ("sleep", False), ("use_toilet", False)):
    c = char("x", "X", act)
    wake_character(c, {"tick": 5, "characters": {}}, "heard_speech", {"speaker_name": "S", "utterance": "hi?"})
    check(f"B: spoken to while '{act}' -> may answer: {want}", _spoken_to_while_busy(c, {"tick": 5}, act) == want)

from cpl import lifecycle
seen = []
lifecycle.notify_unavailable = lambda world, cid, reason: seen.append((cid, reason))
lifecycle._on_activity({"character_id": "x", "activity_type": "take_shower"}, {})
lifecycle._on_activity({"character_id": "y", "activity_type": "dust_and_wipe"}, {})
check("C: stepping into the shower ends their conversation as unavailable", seen == [("x", "in the shower")], seen)

print("all passed" if not failures else f"FAILED: {len(failures)}")
sys.exit(1 if failures else 0)
