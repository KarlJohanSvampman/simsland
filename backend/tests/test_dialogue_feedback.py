"""
The director's notes on lines of dialogue (systems/dialogue_feedback.py, api/dialogue_feedback.py): like / dislike,
a comment, a suggested line -- one note per line, kept on whoever said it, editable, shown on the line in
/admin/convtrace.

Run inside the backend container:   python tests/test_dialogue_feedback.py
"""
import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from systems.dialogue_feedback import give, find, remove

alex = {"id": "c1", "name": "Alex", "x": 1, "y": 1}
kath = {"id": "k", "name": "Kathleen", "x": 1, "y": 1}
w = {"tick": 500, "characters": {"c1": alex, "k": kath}, "conversations": {}, "buildings": [], "props": []}

n = give(alex, w, "conv1", 450, "Soup it is.", verdict="dislike")
check("a dislike makes a note on the line, kept on who said it", n and n["verdict"] == "dislike" and alex["dialogue_feedback"] == [n])
n2 = give(alex, w, "conv1", 450, "Soup it is.", comment="Too curt for him, he's chatty", suggestion="Soup? Love it, I'll chop the onions.")
check("the same line again edits the same note (verdict kept)", n2 is n and n["verdict"] == "dislike" and n["comment"].startswith("Too curt")
      and n["suggestion"].startswith("Soup?") and len(alex["dialogue_feedback"]) == 1)
give(alex, w, "conv1", 460, "Bye", verdict="like")
check("another line, another note", len(alex["dialogue_feedback"]) == 2)
try:
    give(alex, w, "conv1", 460, "Bye", verdict="meh"); bad = False
except ValueError:
    bad = True
check("only like / dislike / none", bad)
gone = give(alex, w, "conv1", 460, "Bye", verdict=None)
check("clearing everything on a note removes it", gone is None and find(alex, "conv1", 460, "Bye") is None)

import api.dialogue_feedback as af
import contextlib
af.load_world = lambda sim_id="default": w
af.save_world = lambda sim_id, world: None
af.world_lock = contextlib.nullcontext
af._save = lambda sim_id, world, cid: None
out = af.give_note("k", af.NoteIn(conv_id="conv1", tick=440, utterance="Something light, maybe soup.", verdict="like"))
check("POST: a like on Kathleen's line", out["ok"] and out["note"]["verdict"] == "like" and kath["dialogue_feedback"][0]["utterance"].startswith("Something"))
out = af.give_note("k", af.NoteIn(conv_id="conv1", tick=440, utterance="Something light, maybe soup.", comment="very her"))
check("POST without a verdict leaves it as it was", out["note"]["verdict"] == "like" and out["note"]["comment"] == "very her")
lst = af.list_notes("c1")
check("GET: their notes", lst["notes"][0]["comment"].startswith("Too curt"))

from brain.conversations import create_conversation, add_message
conv = create_conversation(w, ["c1", "k"])
add_message(w, conv, "k", "Hello there", "greet", "general", 490)
give(kath, w, conv["id"], 490, "Hello there", verdict="dislike", comment="she'd say hi")
import api.conversation_trace as ct
ct.load_world = lambda sim_id="default": w
rows = ct.convtrace("c1")["conversations"]
ln = rows[0]["lines"][0]
check("the conversation timeline shows the note on the line", ln.get("feedback", {}).get("verdict") == "dislike" and ln["feedback"]["comment"] == "she'd say hi", str(ln))
check("DELETE removes a note", af.delete_note("k", kath["dialogue_feedback"][-1]["id"])["ok"] and len(kath["dialogue_feedback"]) == 1)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
