"""
A slow or failing model is not an insult (systems/conversation_floor.py): while decisions are late or failing, a listener whose
reply hasn't been written yet holds the floor and the conversation lapses quietly, with no "ignored" memory or event. With a
healthy model the same silence still ends as "ignored".

Run inside the backend container:   python tests/test_floor_slow_model.py
"""

import os
import sys
import time

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from core import event_bus
from systems import conversation_floor as cf

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def make_world():
    w = {"tick": 100, "characters": {}, "conversations": {}, "conversation_archive": []}
    for cid, name in (("a", "Anna"), ("r", "Rui")):
        w["characters"][cid] = {"id": cid, "name": name, "alive": True, "memories": [], "x": 1, "y": 1}
    conv = {"id": "c1", "active": True, "medium": "in_person", "participants": ["a", "r"], "turn_owner": "r", "history": []}
    w["conversations"]["c1"] = conv
    cf.on_message(w, conv, "a", "We need to talk about this.", "ask", w["tick"])
    return w, conv


def run(w, ticks):
    for _ in range(ticks):
        w["tick"] += 1
        cf.tick(w)
        event_bus.flush(w)


def ignored(w):
    return any("ignored" in (m.get("tags") or []) for m in w["characters"]["a"]["memories"])


# healthy model, nobody answers: the old behaviour -- the speaker is ignored
cf._gen.clear()
cf._llm.update(fail_wall=0.0, ok_wall=time.time())
w, conv = make_world()
check("a healthy model is not reported slow", not cf.llm_degraded())
run(w, 40)
check("... and silence still ends as ignored", conv["end_reason"] == "ignored" and ignored(w), str(conv.get("end_reason")))

# the model has failed: the same silence is not held against the listener
cf._llm.update(fail_wall=time.time(), ok_wall=time.time() - 10)
w, conv = make_world()
check("a failed decision marks the model slow", cf.llm_degraded())
run(w, 40)
check("... the conversation lapses without anyone being ignored", conv["end_reason"] == "lapsed" and not ignored(w), str(conv.get("end_reason")))

# a listener still generating is waited on beyond the usual cap
cf._llm.update(fail_wall=0.0, ok_wall=time.time())
cf._gen.clear()
w, conv = make_world()
w["tick"] += 2
cf.mark_thinking("r", w["tick"])
cf._gen["r"]["wall"] = time.time() - 120          # asked two minutes ago, still no answer
check("a decision outstanding for minutes marks the model slow", cf.llm_degraded())
run(w, cf.THINK_CAP + 30)
check("... a long think is waited for, not written off", conv["active"] and conv["floor"]["state"] != "closed" and not ignored(w), str(conv.get("end_reason")))
cf.clear_thinking("r", w["tick"])
cf.note_llm_result(False)                           # the decision failed (cognition_actor reports it)
run(w, 5)
check("... and if it comes to nothing the conversation lapses quietly", not conv["active"] and conv["end_reason"] == "lapsed" and not ignored(w), str(conv.get("end_reason")))

# one fast answer clears the flag
cf._gen.clear()
cf.note_llm_result(False)
check("a failure sets the flag", cf.llm_degraded())
cf.note_llm_result(True, 2.0, now=time.time() + 1)
check("a quick answer clears it", not cf.llm_degraded())
cf.note_llm_result(True, 95.0, now=time.time() + 2)
check("an answer that took minutes does not", cf.llm_degraded())

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
