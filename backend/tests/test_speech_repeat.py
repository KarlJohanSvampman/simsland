"""
A character says a line to a person once: the same line to the same listener again within
REPEAT_WINDOW_TICKS is dropped -- no new bubble, no new speech_log entry (systems/speech_repeat.py).

Run inside the backend container:   python tests/test_speech_repeat.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

from systems.speech_repeat import is_repeat, REPEAT_WINDOW_TICKS
from systems.incidental_speech import fire_incidental

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def person(cid):
    return {"id": cid, "name": cid, "activity": {"type": "work"}, "speech_log": []}


# ---- is_repeat ---------------------------------------------------------------------------------------------------
world = {"tick": 1000}
c = person("brenda")
c["speech_log"] = [{"tick": 990, "utterance": "I need to get the kids to school, where's the school schedule?",
                    "target": "joseph"}]
check("the same line to the same person is a repeat",
      is_repeat(c, world, "I need to get the kids to school, where's the school schedule?", "joseph"))
check("case, spacing and trailing punctuation don't make it new",
      is_repeat(c, world, "  i need to get the kids to school,  where's the school schedule ", "joseph"))
check("the same line to someone else is not a repeat",
      not is_repeat(c, world, "I need to get the kids to school, where's the school schedule?", "carol"))
check("a different line to the same person is not a repeat",
      not is_repeat(c, world, "Have you seen the school schedule?", "joseph"))
check("a line to nobody in particular only matches lines to nobody in particular",
      not is_repeat(c, world, "I need to get the kids to school, where's the school schedule?", None))
check("after the window the line can be said again",
      not is_repeat(c, {"tick": 990 + REPEAT_WINDOW_TICKS + 1},
                    "I need to get the kids to school, where's the school schedule?", "joseph"))
check("an empty line is never a repeat", not is_repeat(c, world, "   ", "joseph"))
check("no speech_log at all is fine", not is_repeat({"id": "x"}, world, "hello", "joseph"))

# ---- the live loop: a busy listener's stock excuse, once ---------------------------------------------------------
excuse = "Sorry, I'm right in the middle of work -- can we talk later?"
joseph = person("joseph")
world = {"tick": 12653}
fire_incidental(joseph, "decline", excuse, world, target_id="brenda")
first = joseph.get("current_speech")
check("the excuse is said the first time", first is not None and first["utterance"] == excuse)
for t in range(12654, 12670):
    world["tick"] = t
    fire_incidental(joseph, "decline", excuse, world, target_id="brenda")
check("asked again and again, the excuse is logged once",
      sum(1 for e in joseph["speech_log"] if e["utterance"] == excuse) == 1, str(joseph["speech_log"]))
check("the bubble keeps its original expiry instead of being renewed every tick",
      joseph["current_speech"] is first and first["expires_at_tick"] == 12653 + 6)

world["tick"] = 12670
fire_incidental(joseph, "decline", excuse, world, target_id="carol")
check("the same excuse to someone else is still said", joseph["current_speech"]["target"] == "carol")

world["tick"] = 12653 + REPEAT_WINDOW_TICKS + 1
fire_incidental(joseph, "decline", excuse, world, target_id="brenda")
check("once the window has passed it can be said to them again",
      joseph["current_speech"]["target"] == "brenda" and joseph["current_speech"]["expires_at_tick"] == world["tick"] + 6)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
