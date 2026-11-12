"""
A line said in person to someone who can't hear it (too far / through walls) is said aloud but not delivered: no line
in a conversation, no "X just said to you" for them, the speaker is told they weren't heard (wake "not_heard"). Close
by, the same line is delivered as before. (systems/action_router.py::apply_speech, systems/conversation_reach.py)

Run inside the backend container:   python tests/test_unheard_speech.py
"""
import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from house_world import make_world
from systems.schema_defaults import ensure_world_defaults
from systems.room_assignment import room_at
from brain.perception import walls_between
from core import event_bus

w = make_world()
w["tick"] = 3000
ensure_world_defaults(w)
rob, kath = w["characters"]["robert"], w["characters"]["kathleen"]
rob.update(activity=None)
# Kathleen in another room of the same house, a wall between them, 6-8 tiles off
spot = None
for dx in range(-9, 10):
    for dy in range(-9, 10):
        x, y = rob["x"] + dx, rob["y"] + dy
        r = room_at(w, x, y)
        if r and r != room_at(w, rob["x"], rob["y"]) and walls_between(rob, {"x": x, "y": y}, w) and 6 < abs(dx) + abs(dy) < 9:
            spot = (x, y); break
    if spot: break
check("found a spot in another room (for the test)", spot is not None)
kath.update(x=spot[0], y=spot[1], activity=None)

emitted = []
_orig = event_bus.emit
event_bus.emit = lambda name, data=None, **k: (emitted.append((name, data)), _orig(name, data, **k))[1]
import systems.action_router as ar
import systems.conversation_reach as cr
import systems.conversation_interest as ci
ci.check_conversation_interest = lambda *a, **k: (True, 0.8, None)     # she's always up for a chat (no dice roll in the test)

ar.apply_speech(rob, w, {"target": "kathleen", "speech_act": "ask", "utterance": "Kathleen, have you seen my keys?"})
names = [n for n, _ in emitted]
check("said aloud anyway: the bubble shows", (rob.get("current_speech") or {}).get("utterance", "").startswith("Kathleen, have you"))
check("... but not delivered: no conversation, no 'just said to you' for her",
      not any(c.get("active") for c in (w.get("conversations") or {}).values()) and "heard_speech" not in names, str(names))
check("... the speaker is told they weren't heard", any(n == "speech_unheard" and d["speaker_id"] == "robert" and d["where"] == "in another room" for n, d in emitted), str(emitted[-2:]))
check("... and it's logged as not delivered", (w.get("conversation_reach_log") or [{}])[-1].get("delivered") is False)
from brain.cognition_scheduler import _WAKE_LINE_TEMPLATES
check("the speaker's wake line", _WAKE_LINE_TEMPLATES["not_heard"].format(listener_name="Kathleen", where="in another room")
      == "Kathleen didn't hear you -- they're in another room. Go over to them first, or call out louder.")

w["tick"] += 10
rob.pop("current_speech", None)
ar.apply_speech(rob, w, {"target": "kathleen", "speech_act": "ask", "utterance": "KATHLEEN! Keys?"})
check("trying again a moment later: called out (a raised voice)", (rob.get("current_speech") or {}).get("volume") == "high", str(rob.get("current_speech")))
check("... which carries further: through the wall this time she hears it", any(c.get("active") for c in (w.get("conversations") or {}).values()),
      str((w.get("conversation_reach_log") or [{}])[-1]))
for _c in (w.get("conversations") or {}).values():
    _c["active"] = False                                  # (start the next check fresh)

emitted.clear()
kath.update(x=rob["x"] + 1, y=rob["y"])
rob.pop("_unheard", None)
rob.pop("current_speech", None)
w["tick"] += 30
ar.apply_speech(rob, w, {"target": "kathleen", "speech_act": "ask", "utterance": "Have you seen my keys?"})
check("right beside him: delivered as before (a conversation, and she's woken)",
      any(c.get("active") for c in (w.get("conversations") or {}).values()) and "heard_speech" in [n for n, _ in emitted], str([n for n, _ in emitted]))

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
