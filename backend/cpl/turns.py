"""
cpl/turns.py -- a character's turn in a CPL conversation (docs/cpl_implementation_plan.md section 6; phase 1: the
existing decision prompt plus a few lines, decided).

    context_block(world, c)        for a character in a live CPL conversation (CPL_MODE=on): who with, what is still
                                   open (as labels Q1 / R1 / P1 -- never ids), whether it is winding down; None
                                   otherwise. Put on the decision context (brain/agent_loop.py).
    prompt_section(block)          the lines the decision prompt shows for it
    FORMAT_LINES                   the extra reply lines (brain/llm_brain.py's envelope), shown only with a block
    apply_turn(world, conv, c, lines, utterance, others)
                                   the parsed lines applied: answers settle open items, a question or request opens one,
                                   a counteroffer opens a proposal back, an accepted request is a commitment (a social
                                   contract: cpl/adapters/contracts.py), a STANCE takes a claim as acknowledged or
                                   disputed; returns the extra fields for the turn event (cpl/state_machine.py)
    add_claim(world, conv, ...)    something told (gossip, an urgent report): asserted -- heard is not believed
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
                       "director_stop": "everything around you has frozen",
                       "child": "your child is calling for you"}.get(intr.get("kind"), "you were interrupted")
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
        _settle(world, conv, c, ans["item_id"], ans["response_type"], ans.get("condition"), now)
    _claims_answered(conv, c, decision.get("stance"), now)
    to = others[0] if others else None
    nxt = decision.get("next") or {}
    if nxt.get("action") == "let_join" and nxt.get("who"):
        _let_join(world, conv, c, nxt["who"])
    if decision["message_type"] == "argument":
        from core.event_bus import emit
        emit("cpl.argument", {"conversation_id": conv["id"], "by": c["id"], "to": to, "claim": utterance,
                              "stance": decision.get("stance")})
    if decision["message_type"] == "question" and utterance:
        store.add_question(world, conv, asker_id=c["id"], to_id=to, text=utterance, source_message_id=None, now=now)
    elif decision["message_type"] in ("request", "proposal") and utterance:
        store.add_request(world, conv, kind=decision["message_type"], requester_id=c["id"], recipient_id=to,
                          action=utterance, source_message_id=None, now=now)
    return codec.to_event(decision, c["id"], to)


_ACKNOWLEDGE = {"agree", "agreeing", "believe", "believing", "convinced", "accepting", "sympathetic", "supportive"}
_DISPUTE = {"doubt", "doubtful", "disagree", "disagreeing", "disbelieve", "skeptical", "sceptical", "unconvinced",
            "opposed", "dismissive"}


def _claims_answered(conv, c, stance, now):
    """What someone told them, taken one way or the other: acknowledged (not the same as confirmed) or disputed."""
    if not stance:
        return
    st = "acknowledged" if stance in _ACKNOWLEDGE else "disputed" if stance in _DISPUTE else None
    if st is None:
        return
    for cl in (conv.get("claims") or {}).values():
        if cl.get("status") == "asserted" and cl.get("by") != c["id"] and c["id"] in cl.get("to", []):
            cl.setdefault("stances", {})[c["id"]] = st
            cl["status"] = st
            cl["answered_at"] = now
            from core.event_bus import emit
            emit("cpl.information_" + ("acknowledged" if st == "acknowledged" else "disputed"),
                 {"conversation_id": conv["id"], "claim_id": cl["id"], "by": c["id"], "claim": cl.get("text")})


def add_claim(world, conv, speaker_id, to, text, now, kind="reported_claim", overheard_by=()):
    """A line telling something (gossip, an urgent report): recorded as asserted -- heard is not believed (C8). Who
    was told and who only overheard it are kept apart: overhearing is knowing less (no one asked them to believe)."""
    cid = store.next_id(world, "claim")
    conv.setdefault("claims", {})[cid] = {"id": cid, "by": speaker_id, "to": list(to), "text": text, "kind": kind,
                                          "status": "asserted", "at": now, "overheard_by": list(overheard_by)}
    from core.event_bus import emit
    emit("cpl.information_shared", {"conversation_id": conv["id"], "claim_id": cid, "source": speaker_id,
                                    "to": list(to), "overheard_by": list(overheard_by), "claim": text,
                                    "epistemic_status": "asserted"})
    return conv["claims"][cid]


_STATUS = {"accept": "accepted", "reject": "rejected", "conditional": "conditional", "counter": "negotiating",
           "defer": "deferred", "partial": "conditional"}


def _settle(world, conv, c, iid, rtype, condition, now):
    """An answer to an open item: a question answered; a request or proposal accepted / rejected / countered ..."""
    if iid.startswith("q_"):
        store.answer_question(conv, iid, c["id"], rtype, now)
        if not conv["open_items"]["questions"] and not conv["open_items"]["requests"]:
            conv["outcome_hint"] = "question_answered"
        return
    status = _STATUS.get(rtype)
    if not status:
        return
    req = (world.get("cpl_requests") or {}).get(iid) or {}
    store.set_request_status(world, iid, status, now, by=c["id"], condition=condition)
    if req.get("kind") == "proposal" and req.get("counter_to"):
        # the answer to a counteroffer settles the original request: accepted on the counter's terms, or not
        orig = req["counter_to"]
        if status in ("accepted", "conditional"):
            store.set_request_status(world, orig, "accepted", now, by=c["id"], condition=req.get("action"))
            _commit(world, conv, orig)
            conv["outcome_hint"] = "mutual_agreement"
        elif status == "rejected":
            store.set_request_status(world, orig, "rejected", now, by=c["id"])
            conv["outcome_hint"] = "request_rejected"
        return
    if status == "negotiating" and condition:
        # a counteroffer: a proposal back to the one who asked, on these terms (P1 on their prompt)
        p = store.add_request(world, conv, kind="proposal", requester_id=c["id"], recipient_id=req.get("requester_id"),
                              action=condition, source_message_id=None, now=now)
        p["counter_to"] = iid
        return
    conv["outcome_hint"] = {"accepted": "request_fulfilled", "rejected": "request_rejected"}.get(
        status, conv.get("outcome_hint"))
    if status in ("accepted", "conditional"):
        _commit(world, conv, iid)


def _commit(world, conv, rid):
    from core.event_bus import emit
    req = world["cpl_requests"][rid]
    emit("cpl.commitment_created", {"commitment_id": "commit_" + rid, "request": dict(req),
                                    "conversation_id": conv["id"]})


def _let_join(world, conv, c, name):
    """NEXT: let_join:<name> -- someone they can see joins the conversation."""
    from cpl.participants import join
    name = (name or "").strip().lower()
    for p in (c.get("perception") or {}).get("visible_people", []):
        pid = p.get("id")
        pc = (world.get("characters") or {}).get(pid) or {}
        if name and (name == (pc.get("name") or "").lower() or name == (pc.get("name") or "").split(" ")[0].lower()):
            return join(world, conv, pid, by=c["id"])
    return False
