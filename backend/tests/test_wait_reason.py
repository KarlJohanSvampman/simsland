"""
A wait explains itself, and a stray heading in the model's reply is not a thought (brain/llm_brain.py, systems/debug_log.py).

  - "MOVE:" on a line by itself before the ACTION line was stored as the character's thought.
  - A fallback wait (the model's reply had no usable action, or the model never answered) said only "Action: wait". It now carries why,
    and the log line for any wait says what the character had been doing.

Run inside the backend container:   python tests/test_wait_reason.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from brain import llm_brain as lb
from systems import debug_log

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# ---- the narration -----------------------------------------------------------------------------------------------------------------
env = lb._parse_compact_envelope('MOVE: \n\nACTION: walk | towards the bathroom | nothing extra\n\nSAY: "Tiago, time to go!"')
check("a lone 'MOVE:' heading is not the narration", env["narration"] == "", repr(env["narration"]))
check("... the action and the line are still read", env["action"]["type"] == "walk" and env["say"] == '"Tiago, time to go!"')
check("a heading with a thought after it keeps the thought", lb._parse_compact_envelope("THOUGHT: I am tired.\nACTION: wait")["narration"] == "I am tired.")
check("a real sentence with a colon is left alone", lb._clean_narration("Note: the sink is dirty and I should clean it.") == "Note: the sink is dirty and I should clean it.")
check("... and so is plain narration", lb._parse_compact_envelope("I look around the kitchen.\nACTION: examine | sink")["narration"] == "I look around the kitchen.")
check("several stray headings all go", lb._clean_narration("MOVE:\nTHINK:\nI need water.") == "I need water.")

# ---- the fallback says why ---------------------------------------------------------------------------------------------------------------
fb = lb.fallback_response(lb._why_unusable("I examine the bathroom_sink to assess the state of hygiene.", "The reply had no ACTION line."))
check("a reply with no ACTION line is a wait that says so and shows what the model said",
      fb["action"]["type"] == "wait" and "no ACTION line" in fb["action"]["reason"] and "bathroom_sink" in fb["action"]["reason"], fb["action"]["reason"])
check("a timeout says the model gave no answer", "no usable answer" in lb.fallback_response(lb._why_unusable({"error": "timeout: gave up waiting for the LLM gate"}, "x"))["action"]["reason"])
check("an empty reply says it was empty", "empty" in lb._why_unusable("", "The reply had no ACTION line."))
check("with no reason given the old text stays", lb.fallback_response()["action"]["reason"] == "No valid action.")

# ---- the log line ---------------------------------------------------------------------------------------------------------------------
w = {"tick": 5000, "characters": {}}
c = {"id": "r", "name": "Rui", "memories": [], "x": 1, "y": 1}
w["characters"]["r"] = c
debug_log.log_action(c, w, "move", "to the bathroom")
w["tick"] += 180
debug_log.log_action(c, w, "wait", "", reason="The reply had no ACTION line. It said: \"I examine the sink.\"")
m = [x for x in c["memories"] if x.get("kind") == "debug_event"][-1]
check("a wait's log line says why", "The reply had no ACTION line" in m["text"], m["text"])
check("... and what had been going on before", "before: Action: move (to the bathroom), 3 min ago" in m["text"], m["text"])
check("... both are also fields on the memory", m.get("reason", "").startswith("The reply") and "move" in m.get("before", ""), str(m))

c2 = {"id": "k", "name": "Karim", "memories": [], "x": 1, "y": 1, "activity": {"type": "cook_meal", "target_id": None}}
debug_log.log_action(c2, w, "wait", "")
m2 = c2["memories"][-1]
check("with no reason it still says what they were in the middle of", "before: cook meal" in m2["text"] and not m2.get("reason"), m2["text"])

c3 = {"id": "n", "name": "Noor", "memories": [], "x": 1, "y": 1}
debug_log.log_action(c3, w, "wait", "")
check("a wait with nothing to add stays plain", c3["memories"][-1]["text"] == "Action: wait", c3["memories"][-1]["text"])
debug_log.log_action(c3, w, "examine", "the sink", reason="I want to see if it is clean")
check("other actions are logged as before", c3["memories"][-1]["text"] == "Action: examine (the sink)", c3["memories"][-1]["text"])

print()
print("FAILED: " + ", ".join(failures) if failures else "ALL OK")
sys.exit(1 if failures else 0)
