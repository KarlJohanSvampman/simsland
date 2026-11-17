"""
cpl/store.py -- where CPL keeps its state: on the conversation itself (docs/cpl_implementation_plan.md C1, decided;
the legacy store is gone -- there is one record per conversation).

    world["conversations"][id]           THE conversation: the fields the rest of the simulation reads (participants as
                                         a list, history, floor, topic, ...) and CPL's own on the same record -- its
                                         state, members (who is in it and how), cpl_floor, open items, messages (the
                                         last MESSAGE_CAP; the archive keeps them all), cpl_outcome, cpl_purpose ...
                                         (CPL's names never collide with the older ones)
    world["cpl_requests"][request_id]    a request or proposal being negotiated -- it can outlive its conversation
                                         while open / deferred (spec invariant 9)
    world["cpl_seq"]                     the counter ids are made from (deterministic: no uuids)
    world["cpl_dedupe"]                  recently applied message ids (a result delivered twice is dropped)

Both are entity collections (core/world_view.py, core/entity_store.py): each conversation and request is its own
record, persisted and locked one by one. Finished conversations also go to the append-only archive tables
(cpl/archive.py) for history and metrics; those are never read back as live state.

Everything here runs on the simulation core under the world lock (or the entity locks of a unit): sequence numbers
are assigned here.
"""

from cpl.model.enums import ConvState, FINAL

MESSAGE_CAP = 50
DEDUPE_CAP = 500


def _coll(world, name):
    coll = world.get(name)
    if coll is None:
        world[name] = {}
        coll = world[name]
    return coll


def _migrate(world):
    """A save from before the stores were merged: CPL kept its own copy (cpl_conversations, mapped by cpl_legacy_map).
    Live CPL state is transient -- it is dropped, and conversations still under way pick CPL up on their next line."""
    if "cpl_conversations" in world:
        world.pop("cpl_conversations", None)
    if "cpl_legacy_map" in world:
        world.pop("cpl_legacy_map", None)


def conversations(world):
    _migrate(world)
    return _coll(world, "conversations")


def is_cpl(conv):
    return isinstance(conv, dict) and "state" in conv and "members" in conv


def requests(world):
    return _coll(world, "cpl_requests")


def next_id(world, prefix):
    n = int(world.get("cpl_seq") or 0) + 1
    world["cpl_seq"] = n
    return f"{prefix}_{n:06d}"


def get(world, conversation_id):
    conv = (world.get("conversations") or {}).get(conversation_id)
    return conv if is_cpl(conv) else None


def create(world, *, initiator_id, recipient_ids, channel, purpose, topic, policy_key, now, urgent=False,
           legacy_id=None):
    """CPL takes up a conversation: its fields go on the conversation's record (`legacy_id`: the record the rest of
    the simulation made, brain/conversations.py), or -- for one that never got going in the rest of the simulation (a
    declined invitation, an unreachable call) -- on a new record, inactive, with the fields every reader expects."""
    coll = conversations(world)
    conv = coll.get(legacy_id) if legacy_id else None
    if conv is not None and is_cpl(conv):
        # the rest of the simulation reopened this conversation (a talk resuming within a minute): a new round for
        # CPL on the same record; the round that ended is archived (cpl/archive.py) and summed up here
        conv.setdefault("cpl_rounds", []).append({"state": conv.get("state"), "reason": conv.get("reason"),
                                                  "lines": conv.get("lines", 0), "resolved_at": conv.get("resolved_at")})
        conv["cpl_rounds"] = conv["cpl_rounds"][-10:]
    if conv is None:
        cid = legacy_id or next_id(world, "cv")
        conv = {"id": cid, "participants": [initiator_id] + [r for r in recipient_ids if r != initiator_id],
                "topic": topic or "general", "medium": channel, "history": [], "active": False, "status": "pending",
                "_archived": True, "_cpl_only": True}
        coll[cid] = conv
    parts = {initiator_id: _participant("initiator", "active", now)}
    for r in recipient_ids:
        if r != initiator_id:
            parts[r] = _participant("participant", "invited", None)
    conv.update({
        "channel": channel, "initiator_id": initiator_id,
        "state": ConvState.CREATED.value, "state_version": 0, "reason": None,
        "cpl_purpose": purpose, "secondary_purposes": [], "active_topics": [topic] if topic else [],
        "members": parts,
        "cpl_floor": {"holder": None, "waiting_on": None, "attempts": 0},
        "interruption": None,
        "context": {"summary": "", "agreements": [], "disagreements": [], "emotions": {}},
        "open_items": {"questions": [], "requests": [], "proposals": []},
        "cpl_outcome": None, "outcome_hint": None, "closed_by": [], "questions": {}, "claims": {},
        "created_at": now, "cpl_started_at": None, "last_activity_at": now, "resolved_at": None,
        "policy_key": policy_key, "urgent": bool(urgent),
        "seq": 0, "lines": 0, "messages": [], "timers": {}, "structured_lines": 0, "turn_errors": [],
        "legacy_id": conv["id"],
    })
    conv.setdefault("topic", topic)
    return conv


def _participant(role, status, now):
    return {"role": role, "status": status, "joined_at": now, "left_at": None, "left_reason": None,
            "last_seen_seq": 0, "joined_at_seq": 0}


def live(world, character_id=None):
    """The live conversations (of one character)."""
    out = []
    for conv in (world.get("conversations") or {}).values():
        if not is_cpl(conv) or conv.get("state") in {s.value for s in FINAL}:
            continue
        if character_id is None or character_id in (conv.get("members") or {}):
            out.append(conv)
    return out


def seen(world, message_id):
    return message_id in (world.get("cpl_dedupe") or [])


def append_message(world, conv, envelope):
    """Store a message (a plain dict from Envelope.stored()): the next sequence number, the message id remembered.
    Returns the stored message, or None if that message id was already applied (a duplicate delivery)."""
    mid = envelope.get("message_id")
    if mid and (seen(world, mid) or any(m.get("message_id") == mid for m in conv.get("messages") or [])):
        return None
    conv["seq"] = conv.get("seq", 0) + 1
    msg = dict(envelope, sequence_number=conv["seq"], message_id=mid or f"msg_{conv['id']}_{conv['seq']}")
    conv.setdefault("messages", []).append(msg)
    if len(conv["messages"]) > MESSAGE_CAP:
        conv["messages"] = conv["messages"][-MESSAGE_CAP:]
    if msg.get("message_type") != "control" and msg.get("content"):
        conv["lines"] = conv.get("lines", 0) + 1
    conv["last_activity_at"] = msg.get("world_ts", conv.get("last_activity_at"))
    dd = world.get("cpl_dedupe")
    if dd is None:
        world["cpl_dedupe"] = dd = []
    dd.append(msg["message_id"])
    if len(dd) > DEDUPE_CAP:
        del dd[:len(dd) - DEDUPE_CAP]
    return msg


def add_request(world, conv, *, kind, requester_id, recipient_id, action, source_message_id, now, deadline=None,
                conditions=None):
    """A request (kind "request") or proposal ("proposal") opened in a conversation."""
    rid = next_id(world, "req" if kind == "request" else "prop")
    req = {"id": rid, "kind": kind, "conversation_id": conv["id"], "source_message_id": source_message_id,
           "requester_id": requester_id, "recipient_id": recipient_id, "action": action, "deadline": deadline,
           "conditions": list(conditions or []), "status": "open", "history": [{"status": "open", "at": now}]}
    requests(world)[rid] = req
    conv["open_items"]["requests" if kind == "request" else "proposals"].append(rid)
    return req


def set_request_status(world, rid, status, now, **detail):
    req = (world.get("cpl_requests") or {}).get(rid)
    if req is None or req.get("status") == status:
        return req
    req["status"] = status
    req["history"].append(dict({"status": status, "at": now}, **detail))
    if status not in ("open", "negotiating"):
        conv = get(world, req["conversation_id"])
        if conv is not None:
            for k in ("requests", "proposals"):
                if rid in conv["open_items"][k]:
                    conv["open_items"][k].remove(rid)
    return req


def open_requests(world, character_id):
    """Requests still open, deferred or negotiating that involve this character (any conversation, ended or not)."""
    return [r for r in (world.get("cpl_requests") or {}).values()
            if r.get("status") in ("open", "deferred", "negotiating", "conditional")
            and character_id in (r.get("requester_id"), r.get("recipient_id"))]


def add_question(world, conv, *, asker_id, to_id, text, source_message_id, now):
    """A question asked in a conversation: open until answered (or the conversation ends)."""
    qid = next_id(world, "q")
    conv.setdefault("questions", {})[qid] = {"id": qid, "asker_id": asker_id, "to_id": to_id, "text": text,
                                             "source_message_id": source_message_id, "status": "open", "asked_at": now}
    conv["open_items"]["questions"].append(qid)
    return conv["questions"][qid]


def answer_question(conv, qid, by, response_type, now):
    q = (conv.get("questions") or {}).get(qid)
    if q is None or q.get("status") != "open":
        return None
    q.update(status="answered" if response_type not in ("cant_answer", "ignore", "clarify") else response_type,
             answered_by=by, answered_at=now, response_type=response_type)
    if qid in conv["open_items"]["questions"]:
        conv["open_items"]["questions"].remove(qid)
    return q
