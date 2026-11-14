"""
CPL phase 1 (docs/cpl_implementation_plan.md section 6.1, C3): the model's compact turn and initiate lines become
structured decisions; open items are labels, never ids; an invalid turn is caught, and the fallback never invents an
accept or a reject (spec invariant 16).

Run inside the backend container:   python tests/test_cpl_codec.py
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


from cpl.protocol import codec

conv = {"open_items": {"questions": ["q_000003"], "requests": ["req_000001", "req_000004"], "proposals": []}}
L = codec.labels({}, conv)
check("open items are labelled Q1, R1, R2 in order", L == {"Q1": "q_000003", "R1": "req_000001", "R2": "req_000004"}, L)

d, e = codec.parse_turn("""ANSWERS: R1 conditional
ACT: statement
STANCE: reluctant
FEELING: tired 0.3
SAY: You can take it, but have it back before midnight.
CONDITION: back before midnight
NEXT: continue""", L)
check("a full turn parses", not e and d["answers"] == {"label": "R1", "item_id": "req_000001",
                                                        "response_type": "conditional",
                                                        "condition": "back before midnight"}
      and d["emotion"] == {"primary": "tired", "intensity": 0.3} and d["stance"] == "reluctant"
      and d["next"] == {"action": "continue"}, (d, e))
ev = codec.to_event(d, "ana", "theo")
check("... and becomes a turn event (a statement: nothing asked back)", ev["type"] == "turn" and ev["by"] == "ana"
      and not ev["requires_response"] and "control" not in ev, ev)

d, e = codec.parse_turn("ACT: question\nSAY: Where are you going?\nNEXT: continue", L)
check("a question wants an answer", not e and codec.to_event(d, "a")["requires_response"])
d, e = codec.parse_turn("SAY: Whatever.\nNEXT: leave:angry", L)
ev = codec.to_event(d, "a")
check("NEXT leave:angry -> a request to leave, angrily", not e and ev["control"] == "leave" and ev["leave_reason"] == "angry")
d, e = codec.parse_turn("SAY: Talk later.\nNEXT: wrap_up", L)
check("NEXT wrap_up", not e and codec.to_event(d, "a")["wrap_up"])
d, e = codec.parse_turn("SAY: One second.\nNEXT: pause", L)
check("NEXT pause", codec.to_event(d, "a")["control"] == "pause")
d, e = codec.parse_turn("ANSWERS: Q1 answer\nSAY: The kitchen.", L)
check("an answer to a question; ACT defaults to statement", not e and d["answers"]["item_id"] == "q_000003" and d["act"] == "statement")
d, e = codec.parse_turn('SAY: "Fine," she said.\nSAY: Really.', L)
check("outer quotes stripped, a second SAY line continues the first", d["say"] == 'Fine," she said. Really.', d["say"])

# ── errors ───────────────────────────────────────────────────────────────────────────────────────────────────────────
d, e = codec.parse_turn("ANSWERS: R9 accept\nSAY: Sure.", L)
check("an answer to an item that isn't open is an error", e and d["answers"] is None, e)
d, e = codec.parse_turn("ANSWERS: R1 maybe\nSAY: Hm.", L)
check("an answer that isn't one of the answers is an error", e and d["answers"] is None, e)
d, e = codec.parse_turn("ANSWERS: R1 conditional\nSAY: OK if...", L)
check("conditional without a CONDITION is an error", any("CONDITION" in x for x in e), e)
d, e = codec.parse_turn("ACT: request\nNEXT: continue", L)
check("a request with nothing said is an error", any("needs a SAY" in x for x in e), e)
d, e = codec.parse_turn("SAY: Hi.\nNEXT: fly away", L)
check("an unknown NEXT is an error", any("NEXT" in x for x in e), e)
d, e = codec.parse_turn("ACT: shout\nSAY: Hey!", L)
check("an unknown ACT is an error (and read as a statement)", e and d["act"] == "statement", e)
d, e = codec.parse_turn("", L)
check("nothing at all is an error", e)

bad, e = codec.parse_turn("ANSWERS: R9 accept\nSAY: Sure, take it.", L)
fb = codec.fallback(bad)
check("the fallback keeps the line as a plain statement and answers nothing (no invented accept)",
      fb["answers"] is None and fb["say"] == "Sure, take it." and fb["act"] == "statement" and fb["next"] == {"action": "continue"})
check("... and its event settles nothing", not codec.to_event(fb, "a").get("control"))

# ── initiate ─────────────────────────────────────────────────────────────────────────────────────────────────────────
d, e = codec.parse_initiate("""TALK_TO: Ana
PURPOSE: request
ABOUT: borrow the car tonight
APPROACH: friendly
FEELING: anxious 0.4
SAY: Hey, got a minute? Could I borrow your car tonight?""")
check("an initiate parses (face to face by default)", not e and d["talk_to"] == "Ana" and d["purpose"] == "request"
      and d["channel"] == "in_person" and d["emotion"]["intensity"] == 0.4 and d["say"].startswith("Hey"), (d, e))
d, e = codec.parse_initiate("TALK_TO: Theo\nPURPOSE: coordination\nABOUT: dinner\nAPPROACH: urgent\nCHANNEL: call")
check("a call, urgent", not e and d["channel"] == "call" and d["urgent"] and d["say"] is None)
d, e = codec.parse_initiate("PURPOSE: chitchat")
check("no one to talk to, an unknown purpose: errors", len(e) == 2, e)

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
