"""
CPL phase 1, step 5 (docs/cpl_implementation_plan.md section 6; the existing decision prompt plus a few lines,
decided): in a live CPL conversation (CPL_MODE=on) a character's decision prompt shows what is still open, as labels,
and the reply lines ANSWERS / ACT / NEXT carry what their words do -- a request opened, an answer settling it, a
commitment made, the conversation winding down.

Run inside the backend container:   python tests/test_cpl_turns.py
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


from brain import llm_brain as LB
from core import event_bus
from cpl import config, shadow, store, turns

# ── the reply: the extra lines are kept and travel with the speech ───────────────────────────────────────────────────
raw = """ACTION: speak | Theo
SAY: You can take it, but have it back before midnight.
ANSWERS: R1 conditional
CONDITION: back before midnight
NEXT: continue
THEN: get ready for work"""
env = LB._parse_compact_envelope(raw)
check("the reply's CPL lines are kept (ACTION is not mistaken for ACT)",
      env["cpl_lines"] == "SAY: x".replace("SAY: x", "ANSWERS: R1 conditional\nCONDITION: back before midnight\nNEXT: continue"),
      env.get("cpl_lines"))
dec = LB._to_legacy_decision(env)
check("... and travel with the speech", (dec.get("speech") or {}).get("cpl", "").startswith("ANSWERS: R1"), dec.get("speech"))
env2 = LB._parse_compact_envelope("ACTION: speak | Theo\nSAY: Hi.")
check("a reply without them has none", env2["cpl_lines"] == "" and "cpl" not in (LB._to_legacy_decision(env2).get("speech") or {}))
check("the prompt asks for them only in a CPL conversation",
      "ANSWERS:" in LB.build_system_prompt({}, {"open": []}) and "ANSWERS:" not in LB.build_system_prompt({}))

# ── a conversation through the line hook, CPL_MODE=on ────────────────────────────────────────────────────────────────
config.CPL_MODE = "on"
made = []
event_bus.subscribe("cpl.commitment_created", lambda data, world=None: made.append(data))
w = {"tick": 0, "sim_time": 1000.0, "timers": [], "conversations": {},
     "characters": {"theo": {"id": "theo", "name": "Theo"}, "ana": {"id": "ana", "name": "Ana"}}}
legacy = {"id": "L1", "participants": ["theo", "ana"], "medium": "in_person", "active": True, "topic": "the car"}


def say(who, text, lines=None, act="declare"):
    if lines:
        w["characters"][who]["_cpl_turn"] = lines
    shadow.on_line(w, legacy, who, text, act)
    w["characters"][who].pop("_cpl_turn", None)
    w["sim_time"] += 5


say("theo", "Could I borrow your car tonight?", "ACT: request\nNEXT: continue")
conv = store.get(w, w["cpl_legacy_map"]["L1"])
rid = conv["open_items"]["requests"][0] if conv["open_items"]["requests"] else None
check("Theo's opening request is tracked from the start (R1)", rid and w["cpl_requests"][rid]["status"] == "open"
      and w["cpl_requests"][rid]["recipient_id"] == "ana", conv["open_items"])
blk = turns.context_block(w, w["characters"]["ana"])
check("Ana's prompt shows it as R1, needing her answer -- a label, no id",
      blk and blk["open"] == ["R1 Theo asked for: Could I borrow your car tonight? (needs your answer)"]
      and "req_" not in turns.prompt_section(blk), blk)
say("ana", "Sure, take it.", "ANSWERS: R1 accept\nNEXT: continue")
event_bus.flush(w)
check("Ana accepts: the request is accepted and a commitment is made (-> social contracts)",
      w["cpl_requests"][rid]["status"] == "accepted" and made and made[0]["commitment_id"] == "commit_" + rid, made)
check("... everything asked is answered: the conversation winds down", conv["state"] == "resolving", conv["state"])
say("theo", "Thanks, you're the best!", "ACT: statement\nNEXT: wrap_up")
check("Theo's closing line ends it: RESOLVED (request fulfilled)", conv["state"] == "resolved"
      and conv["reason"] == "request_fulfilled", (conv["state"], conv["reason"]))

legacy2 = {"id": "L2", "participants": ["theo", "ana"], "medium": "in_person", "active": True}
legacy = legacy2
say("ana", "Where were you last night?", "ACT: question")
conv2 = store.get(w, w["cpl_legacy_map"]["L2"])
say("theo", "None of your business.", "ANSWERS: Q9 answer\nNEXT: leave:angry")
check("an answer to an item that isn't open answers nothing (no invented answer)",
      conv2["open_items"]["questions"] and conv2.get("turn_errors"), conv2.get("turn_errors"))
check("NEXT leave:angry -> RESOLVED (angry withdrawal)", conv2["state"] == "resolved" and conv2["reason"] == "angry_withdrawal",
      (conv2["state"], conv2["reason"]))

config.CPL_MODE = "shadow"
w["characters"]["ana"]["_cpl_turn"] = "ACT: request"
check("in shadow mode the lines are not applied (CPL only follows)", shadow._turn_lines(w, "ana") is None)
config.CPL_MODE = "off"
check("CPL off: no block on the prompt", turns.context_block(w, w["characters"]["ana"]) is None)

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
