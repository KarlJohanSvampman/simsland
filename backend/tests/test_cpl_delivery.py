"""
CPL phase 1, step 4 (docs/cpl_implementation_plan.md section 7, C12): a line delivered to its listener runs the
per-line side effects as subscribers (cpl/adapters/events.py), in the order apply_speech ran them -- the effects
depend on each other's writes and on the shared random stream -- and is announced as `cpl.message_delivered`.

Run inside the backend container:   python tests/test_cpl_delivery.py
"""

import os
import sys

os.environ.setdefault("COGNITION_MODE", "local")
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


import cpl.adapters.line_effects  # noqa: F401
from cpl.adapters import events
from core import event_bus

names = [f.__name__ for f in events.subscribers()]
check("the per-line effects are subscribers, in apply_speech's order", names == [
    "subject_and_social_line", "pattern_concern", "impact_ledger", "memory_acknowledgement", "dialogue_memory",
    "reaction_and_interaction", "analysis_and_reflections"], names)

src = open("systems/action_router.py").read()
body = src[src.index("def apply_speech("):src.index("WAKE LISTENERS")]
check("apply_speech no longer carries them itself, it delivers", "deliver(world," in body and
      "remember_dialogue(" not in body and "emit_impact(" not in body and "analyze_message(" not in body)

ran, seen = [], []
saved = list(events._subscribers)
events._subscribers[:] = [lambda w, d: ran.append("first"), lambda w, d: ran.append("second")]
event_bus.subscribe("cpl.message_delivered", lambda data, world=None: seen.append(data))
w = {"tick": 1}
events.deliver(w, {"speaker": {"id": "a"}, "listener": {"id": "b"}, "conv": {"id": "conv_1", "history": [1, 2]},
                   "speech_act": "smalltalk", "medium": "in_person"})
event_bus.flush(w)
events._subscribers[:] = saved
check("deliver runs the subscribers synchronously, in order", ran == ["first", "second"], ran)
check("... and announces cpl.message_delivered", seen and seen[0]["recipient_id"] == "b" and seen[0]["line"] == 1, seen)

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
