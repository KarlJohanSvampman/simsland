"""
Conversations with a slow model. Found by running the real tick (house_world, a scripted model answering 3-40 ticks
late, as Ollama does live): before these fixes every conversation ended "ignored" or "lapsed" after a line or two.

A. A decision is "thinking" until it is APPLIED (brain/cognition_actor.py): the worker used to clear it before emitting
   decision_ready, and the floor's tick (before the event flush) saw a listener who had stopped thinking without
   answering -- "ignored", while the reply sat in the queue (and then opened a new conversation).
B. A wake that arrives while a decision is with the model is kept (brain/cognition_scheduler.py::note_think): "Susan just
   said to you: ..." during a slow idle think was wiped when that think landed, so the line was never answered.
   ... unless that decision itself said something to the speaker (cognition_actor._drop_answered_wake).
C. Spoken to mid-decision, the notice window starts when that decision lands (systems/conversation_floor.py).
D. An answer is not dropped as a repeat (systems/action_router.py::apply_speech): "Okay!" twice in half an hour from the
   person holding the floor is ordinary talk; dropping it ended the conversation as "ignored".
E. The asker's line after the answer ends the conversation only if it is a closing line; a new question becomes its
   purpose (systems/conversation_outcome.py).
F. A proposal's wake line says what is asked, not its slug (systems/proposals.py).

Run inside the backend container:   python tests/test_conversation_latency.py
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
import brain.cognition_actor as ca
import brain.agent_loop as al
from brain.cognition_scheduler import wake_character, note_think, wake_line
from brain.conversations import get_or_create_conversation, add_message
from systems import conversation_floor as cf
from systems.action_router import apply_speech

queued = []


class _Later:
    def submit(self, fn, *a, **k):
        queued.append((fn, a, k))


ca._pool = _Later()


def setup():
    w = make_world()
    w["tick"] = 20000
    w["calendar"] = {"year": 2026, "month": 11, "day": 1, "hour": 15, "minute": 0, "second": 0,
                     "minute_of_day": 900, "weekday": "Sunday"}
    w["conversations"] = {}
    k, s = w["characters"]["kathleen"], w["characters"]["susan"]
    for c in (k, s):
        c.update(memories=[], active_intentions=[], age_group="child", speech_log=[],
                 cognition={"next_think_tick": 0})
    k.update(x=84, y=5, building_id="starter_house_3")
    for a, b in ((k, s), (s, k)):
        a["perception"] = {"visible_people": [{"id": b["id"], "visibility": 1.0}]}
    cf._gen.clear()
    cf._llm.update(fail_wall=0.0, ok_wall=0.0)
    return w, k, s


def say(w, conv, who, line, act="declare"):
    add_message(w, conv, who, line, act, "general", w["tick"])


def run_floor(w, ticks):
    for _ in range(ticks):
        w["tick"] += 1
        cf.tick(w)


# ---- A: thinking until applied -------------------------------------------------------------------------------------
import core.event_bus as bus
emitted = []
_emit = bus.emit
ca.emit = lambda name, data: emitted.append((name, data))
w, k, s = setup()
conv = get_or_create_conversation(w, ["kathleen", "susan"], topic="general", medium="in_person")
say(w, conv, "kathleen", "Susan, wanna play a game?", "ask")
w["tick"] += 1
ca.request_decision(s, w, {"available_actions": {}}, "heard_speech", 0)
check("asking marks Susan as thinking", cf._is_thinking("susan"))
ca.think_stub = None
import brain.llm_brain as lb
lb.think = lambda context, char_id=None, session=None, priority=None: {
    "thought": "", "action": {"type": "speak", "target": "kathleen"},
    "speech": {"target": "kathleen", "utterance": "Sure!", "speech_act": "accept"}}
fn, a, kw = queued.pop()
fn(*a, **kw)                                   # the model answers (worker thread) ...
check("the answer back from the model: still thinking until it is applied", cf._is_thinking("susan"))
cf.tick(w)                                     # ... the floor ticks before the flush
check("... so the floor doesn't call it ignored", conv.get("active") and conv["floor"]["state"] != "closed",
      str(conv.get("end_reason")))
ca.on_decision_ready(emitted[-1][1], w)        # the flush
check("applied: no longer thinking", not cf._is_thinking("susan"))
check("... and Susan's answer is in the conversation", conv["history"][-1]["utterance"] == "Sure!")
ca.emit = _emit

# ---- B: a wake during a pending decision is kept -------------------------------------------------------------------
w, k, s = setup()
s["cognition"]["wake_seq"] = 3
s["cognition"]["pending"] = {"id": "r1", "tick": w["tick"], "wall": 0, "wake_reason": "idle", "wake_seq": 3}
wake_character(s, w, "heard_speech", {"speaker_id": "kathleen", "speaker_name": "Kathleen Okafor",
                                      "utterance": "Susan, wanna play?"})
note_think(s, w, {"action": {"type": "wait"}}, wake_reason="idle", asked_at_seq=3)
check("a line heard while an idle think was out is still waiting to be answered",
      s["cognition"]["wake_reason"] == "heard_speech" and s["cognition"]["next_think_tick"] <= w["tick"])
check("... and the prompt says so", (wake_line(s) or "").startswith("Kathleen Okafor just said to you"))
note_think(s, w, {"action": {"type": "wait"}}, wake_reason="heard_speech", asked_at_seq=s["cognition"]["wake_seq"])
check("the think that saw it clears it", s["cognition"]["wake_reason"] is None)

w, k, s = setup()
s["cognition"].update(wake_seq=1, pending={"id": "r2", "tick": w["tick"], "wall": 0, "wake_reason": "idle",
                                           "wake_seq": 1})
wake_character(s, w, "heard_speech", {"speaker_id": "kathleen", "speaker_name": "Kathleen Okafor", "utterance": "Hi!"})
al.build_context = lambda *a, **k: {"stub": True}
ca.on_decision_ready({"character_id": "susan", "request_id": "r2", "tick": w["tick"], "wake_reason": "idle",
                      "decision": {"thought": "", "action": None,
                                   "speech": {"target": "kathleen", "utterance": "Hi Kathleen!", "speech_act": "greet"}}},
                     w)
check("the out-of-date decision answered Kathleen anyway: no second think about her line",
      s["cognition"].get("wake_reason") is None and s["cognition"]["next_think_tick"] > w["tick"],
      str(s["cognition"].get("wake_reason")))

# ---- C: spoken to mid-decision -------------------------------------------------------------------------------------
w, k, s = setup()
cf.mark_thinking("susan", w["tick"] - 2)          # an idle think from before the line
conv = get_or_create_conversation(w, ["kathleen", "susan"], topic="general", medium="in_person")
say(w, conv, "kathleen", "Did you see the weather today?", "ask")
run_floor(w, 30)
check("while that decision is out, Kathleen isn't left 'unnoticed' or ignored",
      conv.get("active") and conv["floor"]["state"] == "waiting", conv["floor"]["state"])
cf.clear_thinking("susan", w["tick"] - 32)
run_floor(w, 1)
cf.mark_thinking("susan", w["tick"])              # she thinks again (B), now about the line
run_floor(w, 3)
check("once it lands and she thinks again, she is thinking about the answer", conv["floor"]["state"] == "thinking",
      conv["floor"]["state"])
w, k, s = setup()
conv = get_or_create_conversation(w, ["kathleen", "susan"], topic="general", medium="in_person")
say(w, conv, "kathleen", "Did you see the weather today?", "ask")
run_floor(w, 30)
check("not thinking at all: still 'ignored' as before", not conv.get("active") and conv["end_reason"] == "ignored")

# ---- D: an answer is never a repeat -------------------------------------------------------------------------------
w, k, s = setup()
conv = get_or_create_conversation(w, ["kathleen", "susan"], topic="general", medium="in_person")
s["speech_log"] = [{"tick": w["tick"] - 200, "utterance": "Okay!", "target": "kathleen"}]
apply_speech(k, w, {"target": "susan", "utterance": "Wanna play tag?", "speech_act": "ask"})
conv = get_or_create_conversation(w, ["kathleen", "susan"], topic="general", medium="in_person")
w["tick"] += 3
apply_speech(s, w, {"target": "kathleen", "utterance": "Okay!", "speech_act": "accept"})
check("Susan's 'Okay!' answers Kathleen, though she said it 200 ticks ago",
      conv["history"][-1]["speaker"] == "susan" and conv["history"][-1]["utterance"] == "Okay!")
from systems.conversation_outcome import end
end(w, conv, "resolved")
w["tick"] += 1
n_log = len(s["speech_log"])
apply_speech(s, w, {"target": "kathleen", "utterance": "Okay!", "speech_act": "accept"})
check("outside a conversation, the same line again is still dropped", len(s["speech_log"]) == n_log
      and not any(c.get("active") for c in w["conversations"].values()))

# ---- E: a question after the answer --------------------------------------------------------------------------------
w, k, s = setup()
conv = get_or_create_conversation(w, ["kathleen", "susan"], topic="general", medium="in_person")
say(w, conv, "kathleen", "Wanna play?", "ask")
say(w, conv, "susan", "Sure!", "accept")
check("'Sure!' settles it", (conv.get("outcome") or {}).get("verdict") == "yes")
say(w, conv, "kathleen", "Great! What game?", "ask")
check("'Great! What game?' doesn't end it", conv.get("active"), str(conv.get("end_reason")))
check("... it is the conversation's new purpose", (conv.get("purpose") or {}).get("line") == "Great! What game?"
      and not conv.get("outcome"))
say(w, conv, "susan", "Tag!", "declare")
say(w, conv, "kathleen", "Cool, let's go.", "declare")
check("a plain closing line still ends it", conv.get("active") or conv.get("end_reason") in (None, "resolved"))

# ---- F: proposals say what they ask --------------------------------------------------------------------------------
from systems.proposals import propose_social_ask
w, k, s = setup()
propose_social_ask(k, s, w, "opinion_on_workplace", {"text": "What do you think of the new job?"})
line = wake_line(s) or ""
check("the wake line has the question", "What do you think of the new job?" in line and "opinion_on" not in line,
      line)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
