"""
Turning people down (systems/conversation_interest.py, systems/rejection.py).

  * no answer from the model is a brief yes, never a random decline (live 2026-11-21: half of every unanswered check
    was a "no" -- 266 declines in a day);
  * a decline comes with the listener's own reason; the prompt says most people stop for someone they know, and tells
    the model when they've already turned this person down today; no session history is carried along;
  * the one turned down remembers it, is told whether this person turned them down last time too, is nudged to ask
    what they're busy with, and a third time in a day is noted as a pattern.

Run inside the backend container:   python tests/test_conversation_interest.py
"""
import os, sys
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

import llm.llm_gate as gate
from systems import conversation_interest as ci
from systems import rejection

listener = {"id": "l", "name": "Lee Park", "activity": {"type": "dust_and_wipe"}, "relationships": {}, "traits": ["shy"]}
asker = {"id": "a", "name": "Anna Bell", "relationships": {}, "memories": []}
w = {"tick": 1000, "sim_time": 100000.0, "characters": {"l": listener, "a": asker}}
prompts = []

def fake(answer):
    def run(coro, *a, **k):
        try:
            prompts.append(coro.cr_frame.f_locals["messages"][-1]["content"])
        except Exception:
            pass
        coro.close()
        return answer
    return run

gate.run_llm_call = fake(None)
check("no answer from the model: they talk, briefly", all(ci.check_conversation_interest(listener, w, "x", "a")
                                                         == (True, "engage_briefly", None) for _ in range(20)))
gate.run_llm_call = fake({"error": "timeout"})
check("... the gate's timeout too", ci.check_conversation_interest(listener, w, "x", "a") == (True, "engage_briefly", None))
gate.run_llm_call = fake("CHOICE: decline_busy\nREASON: I've got my hands full with this dusting, give me ten minutes?")
ok, eng, excuse = ci.check_conversation_interest(listener, w, "the weather", "a")
check("a decline carries the listener's own reason", not ok and eng == "decline_busy" and "ten minutes" in excuse, excuse)
check("the prompt asks for a real reason and says most people stop", "Only turn them down for a real reason" in prompts[-1]
      and "Most people stop" in prompts[-1])
gate.run_llm_call = fake("engage_fully")
check("a bare id (the old format) still works", ci.check_conversation_interest(listener, w, "x", "a")[1] == "engage_fully")

# ── being turned down ───────────────────────────────────────────────────────────────────────────────────────────────
import brain.cognition_scheduler as cs
woken = []
cs.wake_character = lambda c, world, reason, payload=None, delay=0: woken.append((c["id"], reason, payload))
r1 = rejection.on_rejected(w, asker, listener, "I've got my hands full with this dusting", "busy")
check("the first time: remembered, nothing earlier to look back on", r1["previous"] is None and r1["count_today"] == 1
      and any("turned me down" in m["text"] for m in asker["memories"]))
check("... and they're nudged to ask what the other is busy with", woken[-1][1] == "conversation_declined"
      and "ask what they're busy with" in woken[-1][2]["hint"], woken[-1])
w["tick"] += 1800; w["sim_time"] += 1800
r2 = rejection.on_rejected(w, asker, listener, "Not now.", "uninterested")
check("the second time: last time is looked back on, with when", r2["previous"] and "turned you down too" in woken[-1][2]["hint"]
      and "30 minutes ago" in woken[-1][2]["hint"], woken[-1][2])
check("the listener now knows they turned Anna down once already... twice", rejection.declined_recently(listener, "a", w) == 2)
gate.run_llm_call = fake("CHOICE: engage_briefly\nREASON: ok")
ci.check_conversation_interest(listener, w, "x", "a")
check("... and the willingness prompt tells the model so", "already turned Anna down 2 times today" in prompts[-1], prompts[-1][-300:])
w["tick"] += 600; w["sim_time"] += 600
r3 = rejection.on_rejected(w, asker, listener, "Busy.", "busy")
check("the third time in a day: a pattern, remembered once", r3["routine"] and
      sum("keeps turning me down" in m["text"] for m in asker["memories"]) == 1 and "becoming a pattern" in woken[-1][2]["hint"])
check("the same refusal reported twice in one tick counts once", rejection.on_rejected(w, asker, listener, "Busy.") is None)
asker2 = {"id": "b", "name": "Bo", "memories": [{"text": "Lee turned me down.", "tags": ["rejected"], "people": ["l"], "tick": 5}]}
check("looking back finds it in memories too", (rejection.previous_rejection(asker2, "l") or {}).get("from_memory"))

print("all passed" if not failures else f"FAILED: {len(failures)}")
sys.exit(1 if failures else 0)
