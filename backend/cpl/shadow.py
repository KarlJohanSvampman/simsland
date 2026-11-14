"""
cpl/shadow.py -- CPL follows the legacy conversation path (docs/cpl_implementation_plan.md section 11).

CPL_MODE=shadow: it changes nothing outside its own entities. CPL_MODE=on: the same following, and CPL decides when
a conversation ends by time or length (its policies) -- the legacy path's own such endings are held back
(legacy_end_allowed), and when CPL ends one the legacy conversation ends with it (on_cpl_end).

The legacy path still decides everything. CPL is told what happened, synchronously, at the points where it happens:

    on_line(world, legacy_conv, speaker_id, utterance, speech_act)     brain/conversations.py::add_message
    on_declined(world, speaker, listener, medium, topic, excuse)       apply_speech: the listener said no
    on_unreachable(world, speaker, listener, medium, topic, utterance) apply_speech: voicemail
    on_legacy_end(world, legacy_conv, reason)                          systems/conversation_floor.py::_end

and keeps its own conversation for each legacy one (cpl entities, its own timers). When the legacy one ends, how
CPL's copy stands then is recorded -- did CPL end it first, and why; was it still live -- and CPL's copy is closed
with the legacy reason. world["cpl_shadow"] holds the tallies; compare() reads them. This is how each piece moved
into CPL is shown to agree before CPL_MODE=on lets it decide.
"""

from cpl import config, store
from cpl import conversations as CV
from cpl.model.enums import LEGACY_SPEECH_ACT, MessageType, FINAL

_FINAL = {s.value for s in FINAL}

# legacy end reason -> the CPL resolution reason it corresponds to
LEGACY_REASON = {
    "ignored": "abandoned", "lapsed": "timeout", "idle": "timeout", "participant_gone": "unavailable",
    "resolved": "question_answered", "answered": "question_answered", "declined": "request_rejected",
    "timed_out": "timeout", "left": "participant_left", "no_response": "abandoned",
}

# CPL's reason -> the legacy reason readers of a legacy ending know (archive, memories of being ignored, ...)
LEGACY_FOR = {"abandoned": "ignored", "timeout": "timed_out", "unavailable": "participant_gone",
              "participant_left": "left", "angry_withdrawal": "left", "question_answered": "resolved",
              "request_rejected": "resolved", "request_fulfilled": "resolved", "mutual_agreement": "resolved",
              "topic_exhausted": "resolved", "declined": "declined"}

_PURPOSE_BY_ACT = {
    "question": "question", "ask": "question", "micro_request": "request", "request": "request",
    "flirt": "romantic", "compliment": "social", "smalltalk": "social", "joke": "social", "brag": "social",
    "comfort": "support", "supportive": "support", "vulnerable": "emotional", "confession": "emotional",
    "apology": "emotional", "insult": "conflict", "challenge": "conflict", "defensive": "conflict",
    "dismissive": "conflict", "argue": "persuasion", "gossip": "gossip", "urgent_report": "informative",
}


def active(world):
    """CPL follows the legacy path: in shadow mode only to compare, in "on" mode to decide."""
    return config.mode(world) in ("shadow", "on")


def deciding(world):
    return config.mode(world) == "on"


# CPL_MODE=on: endings by time and length are CPL's (its policies and timers, cpl/policies.py) -- the legacy path's
# own ones are held back. A legacy ending for something that happened (settled, someone left or gone) still ends it.
CPL_OWNED_ENDINGS = {"timed_out", "no_response", "idle", "lapsed", "ignored"}


def legacy_end_allowed(world, legacy, reason):
    """systems/conversation_floor.py::_end asks first: in "on" mode a time/length ending is CPL's to make."""
    if not deciding(world) or legacy.get("_cpl_ending") or reason not in CPL_OWNED_ENDINGS:
        return True
    conv = _cpl_for(world, legacy.get("id"))
    if conv is None or conv.get("state") in _FINAL:
        return True                          # CPL has no live copy of it: nothing to defer to
    if not legacy.get("_cpl_held"):
        legacy["_cpl_held"] = True
        st = _stats(world)
        st["held_back"] = st.get("held_back", 0) + 1
    return False


def on_cpl_end(world, conv, event):
    """CPL ended a conversation by itself (its timer, a turn): in "on" mode the legacy one ends with it."""
    if not deciding(world) or event.get("type") == "force_resolve" or not conv.get("legacy_id"):
        return
    legacy = (world.get("conversations") or {}).get(conv["legacy_id"])
    if not legacy or not legacy.get("active"):
        return
    from systems.conversation_floor import _end
    legacy["_cpl_ending"] = True
    try:
        _end(world, legacy, LEGACY_FOR.get(conv.get("reason"), f"cpl_{conv.get('reason')}"))
    finally:
        legacy.pop("_cpl_ending", None)
    st = _stats(world)
    st["cpl_ended"] = st.get("cpl_ended", 0) + 1


def _stats(world):
    st = world.get("cpl_shadow")
    if st is None:
        world["cpl_shadow"] = st = {"opened": 0, "lines": 0, "rejected_turns": 0, "declined": 0, "unreachable": 0,
                                    "legacy_ended": 0, "agree": 0, "cpl_ended_first": 0, "cpl_still_live": 0,
                                    "pairs": {}, "rejections": {}}
    return st


def _purpose(speech_act, conversation_type=None):
    if conversation_type == "argument":
        return "conflict"
    if conversation_type in ("negotiation", "persuasion"):
        return conversation_type
    return _PURPOSE_BY_ACT.get((speech_act or "").lower(), "social")


def _map(world):
    m = world.get("cpl_legacy_map")
    if m is None:
        world["cpl_legacy_map"] = m = {}
    return m


def _cpl_for(world, legacy_id):
    cid = (world.get("cpl_legacy_map") or {}).get(legacy_id)
    return store.get(world, cid) if cid else None


def _envelope(conv, speaker_id, recipients, utterance, speech_act, ts, requires):
    mtype = LEGACY_SPEECH_ACT.get((speech_act or "").lower(), MessageType.STATEMENT).value
    if mtype in ("question", "request", "proposal", "response"):
        mtype = "statement" if mtype in ("proposal", "response") else mtype
    payload = {"text": utterance} if mtype == "question" else ({"action": utterance} if mtype == "request" else {})
    return {"protocol_version": "1.0", "message_id": None, "conversation_id": conv["id"], "sender_id": speaker_id,
            "recipient_ids": recipients, "message_type": mtype, "control": None, "world_ts": ts, "payload": payload,
            "content": utterance, "audience": {"addressed": recipients, "overheard_by": [], "private": False},
            "metadata": {"requires_response": bool(requires), "legacy_speech_act": speech_act}}


def on_line(world, legacy, speaker_id, utterance, speech_act):
    if not active(world) or not legacy or not legacy.get("id"):
        return
    try:
        _on_line(world, legacy, speaker_id, utterance, speech_act)
    except Exception as exc:                       # the shadow must never break the real path
        print(f"[cpl.shadow] on_line failed: {exc!r}")


def _on_line(world, legacy, speaker_id, utterance, speech_act):
    from core.clock import now_ts
    from systems.conversation_floor import classify, expects_reply
    st = _stats(world)
    st["lines"] += 1
    others = [p for p in legacy.get("participants") or [] if p != speaker_id]
    kind, _words = classify(utterance, speech_act)
    requires = expects_reply(utterance, speech_act, kind)
    conv = _cpl_for(world, legacy["id"])
    if conv is not None and conv.get("state") in _FINAL:
        st["reopened"] = st.get("reopened", 0) + 1         # CPL had ended it; the legacy one carries on
        key = f"(carried on) -> {conv.get('reason')}"
        st["pairs"][key] = st["pairs"].get(key, 0) + 1
    if conv is None or conv.get("state") in _FINAL:
        conv = CV.open_conversation(world, speaker_id, others, channel=legacy.get("medium", "in_person"),
                                    purpose=_purpose(speech_act, legacy.get("conversation_type")),
                                    topic=legacy.get("topic") or "", legacy_id=legacy["id"])
        _map(world)[legacy["id"]] = conv["id"]
        st["opened"] += 1
        lines = _turn_lines(world, speaker_id)
        if lines:                                   # the opening line can ask something: tracked from the start
            from cpl.turns import apply_turn
            apply_turn(world, conv, (world.get("characters") or {})[speaker_id], lines, utterance, others,
                       now_ts(world))
        store.append_message(world, conv, _envelope(conv, speaker_id, others, utterance, speech_act, now_ts(world),
                                                    requires))
        return
    event = {"type": "turn", "by": speaker_id, "requires_response": requires,
             "addressed": others[0] if others else None,
             "raises_item": requires and conv.get("state") == "resolving"}
    lines = _turn_lines(world, speaker_id)
    if lines:                                       # CPL_MODE=on: the speaker's ANSWERS / ACT / NEXT (cpl/turns.py)
        from cpl.turns import apply_turn
        ev = apply_turn(world, conv, (world.get("characters") or {})[speaker_id], lines, utterance, others,
                        now_ts(world))
        ev["requires_response"] = ev["requires_response"] or requires
        ev["raises_item"] = ev["raises_item"] and conv.get("state") == "resolving"
        if not conv["open_items"]["questions"] and not conv["open_items"]["requests"] and conv.get("outcome_hint"):
            ev["settles_all"] = True                # everything asked is answered: wind down
        event = ev
        st["structured_turns"] = st.get("structured_turns", 0) + 1
    res = CV.submit(world, conv, event)
    if res.changed and conv.get("interruption"):
        conv["interruption"] = None                 # someone spoke: the interruption has been dealt with
    if not res.changed:
        st["rejected_turns"] += 1
        st["rejections"][res.rejected] = st["rejections"].get(res.rejected, 0) + 1
    store.append_message(world, conv, _envelope(conv, speaker_id, others, utterance, speech_act, now_ts(world),
                                                requires))
    from cpl.lifecycle import summarize
    conv["context"]["summary"] = summarize(conv, world)


def _turn_lines(world, speaker_id):
    """The speaker's parsed CPL lines for the line being added (systems/action_router.py sets them), in "on" mode."""
    if not deciding(world):
        return None
    return ((world.get("characters") or {}).get(speaker_id) or {}).get("_cpl_turn")


def on_declined(world, speaker, listener, medium, topic, excuse=None):
    if not active(world):
        return
    try:
        conv = CV.open_conversation(world, speaker["id"], [listener["id"]], channel=medium, purpose="social",
                                    topic=topic or "")
        CV.submit(world, conv, {"type": "turn", "by": listener["id"], "control": "decline", "excuse": excuse})
        _stats(world)["declined"] += 1
    except Exception as exc:
        print(f"[cpl.shadow] on_declined failed: {exc!r}")


def on_unreachable(world, speaker, listener, medium, topic, utterance=None):
    if not active(world):
        return
    try:
        CV.open_conversation(world, speaker["id"], [listener["id"]], channel=medium, purpose="social",
                             topic=topic or "", reachable=False)
        _stats(world)["unreachable"] += 1
    except Exception as exc:
        print(f"[cpl.shadow] on_unreachable failed: {exc!r}")


def on_legacy_end(world, legacy, reason):
    if not active(world) or not legacy or legacy.get("_cpl_ending"):
        if legacy is not None and legacy.get("_cpl_ending"):
            (world.get("cpl_legacy_map") or {}).pop(legacy.get("id"), None)
        return
    try:
        st = _stats(world)
        st["legacy_ended"] += 1
        conv = _cpl_for(world, legacy.get("id"))
        if conv is None:
            return
        want = LEGACY_REASON.get(reason, reason)
        if conv.get("state") in _FINAL:
            st["cpl_ended_first"] += 1
            got = conv.get("reason")
        else:
            st["cpl_still_live"] += 1
            got = f"live:{conv.get('state')}"
            CV.submit(world, conv, {"type": "force_resolve", "reason": want})
        if got == want:
            st["agree"] += 1
        key = f"{reason} -> {got}"
        st["pairs"][key] = st["pairs"].get(key, 0) + 1
        (world.get("cpl_legacy_map") or {}).pop(legacy.get("id"), None)
    except Exception as exc:
        print(f"[cpl.shadow] on_legacy_end failed: {exc!r}")


def compare(world):
    """The shadow's tallies: how often CPL's lifecycle agreed with the legacy one, and where it didn't."""
    st = dict(_stats(world))
    n = st["legacy_ended"] or 1
    st["agree_rate"] = round(st["agree"] / n, 3)
    st["live"] = len(store.live(world))
    return st
