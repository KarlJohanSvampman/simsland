"""
cpl/turns.py -- a character's turn in a CPL conversation (docs/cpl_implementation_plan.md section 6; phase 1: the
existing decision prompt plus a few lines, decided).

    context_block(world, c)        for a character in a live CPL conversation (CPL_MODE=on): who with, what is still
                                   open (as labels Q1 / R1 / P1 -- never ids), whether it is winding down; None
                                   otherwise. Put on the decision context (brain/agent_loop.py).
    prompt_section(block)          the lines the decision prompt shows for it
    FORMAT_LINES                   the extra reply lines (brain/llm_brain.py's envelope), shown only with a block
    apply_turn(world, conv, c, lines, utterance, others)
                                   the parsed lines applied: answers settle open items, a question or request opens one;
                                   returns the extra fields for the turn event (cpl/state_machine.py)
"""

from cpl import config, store
from cpl.protocol import codec

FORMAT_LINES = """ANSWERS: <label> <accept | reject | conditional | counter | defer | answer | cant_answer | acknowledge> -- ONLY when your words answer one of the open items listed under "Still open"
ACT: <statement | question | request | proposal | argument | feeling> -- what your SAY line does
CONDITION: <the condition> -- only with conditional or counter
NEXT: <continue | wrap_up | leave:excuse | leave:angry | pause> -- what you do with this conversation after speaking"""


def _name(world, cid):
    return ((world.get("characters") or {}).get(cid) or {}).get("name") or cid


def context_block(world, c):
    if config.mode(world) != "on":
        return None
    convs = store.live(world, c.get("id"))
    if not convs:
        return None
    conv = max(convs, key=lambda v: v.get("last_activity_at") or 0)
    labels = codec.labels(world, conv)
    open_lines = []
    for label, iid in labels.items():
        if label.startswith("Q"):
            q = (conv.get("questions") or {}).get(iid) or {}
            who, to, what = q.get("asker_id"), q.get("to_id"), q.get("text")
        else:
            r = (world.get("cpl_requests") or {}).get(iid) or {}
            who, to, what = r.get("requester_id"), r.get("recipient_id"), r.get("action")
        mine = to == c.get("id")
        open_lines.append(f"{label} {_name(world, who) if who != c.get('id') else 'You'} "
                          f"{'asked' if label.startswith('Q') else 'asked for'}: {what}"
                          + (" (needs your answer)" if mine else ""))
    others = [p for p in conv["participants"] if p != c.get("id")]
    intr = conv.get("interruption")
    interrupted = None
    if intr and intr.get("who") == c.get("id"):
        interrupted = {"doorbell": "the doorbell rang", "phone": "your phone is ringing",
                       "director_stop": "everything around you has frozen"}.get(intr.get("kind"), "you were interrupted")
    return {"conversation_id": conv["id"], "with": [_name(world, p) for p in others], "labels": labels,
            "open": open_lines, "winding_down": bool(conv.get("winding_down")), "state": conv.get("state"),
            "summary": (conv.get("context") or {}).get("summary") or "", "interrupted": interrupted,
            "paused": conv.get("state") == "paused"}


def prompt_section(block):
    if not block:
        return ""
    lines = [f"Conversation with {', '.join(block['with'])}:"]
    if block.get("summary"):
        lines.append("So far: " + block["summary"])
    lines += ["Still open: " + l for l in block["open"]] or ["Nothing is waiting for an answer."]
    if block.get("interrupted"):
        lines.append(f"Just now {block['interrupted']}: carry on talking, put the conversation on hold (NEXT: pause), "
                     "or excuse yourself (NEXT: leave:excuse).")
    if block.get("paused"):
        lines.append("The conversation is on hold: pick it up again by speaking, or leave it (NEXT: leave:excuse).")
    if block.get("winding_down"):
        lines.append("It is time to wrap this conversation up: say your goodbye (NEXT: wrap_up) unless something new "
                     "really needs saying.")
    return "\n".join(lines)


def apply_turn(world, conv, c, lines, utterance, others, now):
    """Answers settle what they answer; a question or request opens an item. Returns event fields."""
    decision, errors = codec.parse_turn((lines or "") + (f"\nSAY: {utterance}" if utterance else ""),
                                        codec.labels(world, conv))
    if errors:
        conv.setdefault("turn_errors", []).append({"by": c["id"], "errors": errors[:3], "at": now})
        conv["turn_errors"] = conv["turn_errors"][-10:]
        if any("ANSWERS" in e or "CONDITION" in e for e in errors):
            decision = codec.fallback(decision)             # an answer we can't read is no answer (invariant 16)
    ans = decision.get("answers")
    if ans:
        iid, rtype = ans["item_id"], ans["response_type"]
        if iid.startswith("q_"):
            store.answer_question(conv, iid, c["id"], rtype, now)
            if not conv["open_items"]["questions"] and not conv["open_items"]["requests"]:
                conv["outcome_hint"] = "question_answered"
        else:
            status = {"accept": "accepted", "reject": "rejected", "conditional": "conditional", "counter": "negotiating",
                      "defer": "deferred", "partial": "conditional"}.get(rtype)
            if status:
                store.set_request_status(world, iid, status, now, by=c["id"], condition=ans.get("condition"))
                conv["outcome_hint"] = {"accepted": "request_fulfilled", "rejected": "request_rejected"}.get(
                    status, conv.get("outcome_hint"))
                if status == "accepted":
                    from core.event_bus import emit
                    req = world["cpl_requests"][iid]
                    emit("cpl.commitment_created", {"commitment_id": "commit_" + iid, "request": dict(req),
                                                    "conversation_id": conv["id"]})
    to = others[0] if others else None
    if decision["message_type"] == "question" and utterance:
        store.add_question(world, conv, asker_id=c["id"], to_id=to, text=utterance, source_message_id=None, now=now)
    elif decision["message_type"] in ("request", "proposal") and utterance:
        store.add_request(world, conv, kind=decision["message_type"], requester_id=c["id"], recipient_id=to,
                          action=utterance, source_message_id=None, now=now)
    return codec.to_event(decision, c["id"], to)
