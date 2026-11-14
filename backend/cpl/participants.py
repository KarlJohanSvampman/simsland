"""
cpl/participants.py -- who a line is for, and whether it can reach them (docs/cpl_implementation_plan.md section 3,
Participant Manager; C12: moved out of systems/action_router.py::apply_speech one check at a time, each unchanged,
so the legacy path and CPL decide reachability the same way).

    addressee(c, target_id)                           whom a line goes to: the named target, else the person most
                                                      clearly in view (a line said to someone standing right there
                                                      reaches them without a name)
    answering(c, world, target_id)                    c holds the floor of a live conversation with target_id: what
                                                      they say is an answer
    repeat_dropped(c, world, utterance, target_id)    the same line to the same person again, and not an answer
    floor_blocks(world, speaker_id, target_id, medium)  the other holds the floor and is within their time to answer:
                                                      don't talk over them
    earshot(world, speaker, listener, volume)         (heard, reach): too far or through walls -> not heard
    channel_open(world, listener, medium)             a call needs a usable phone and someone not in a meeting
                                                      (otherwise it goes to voicemail); text and email always "send"
"""


def addressee(c, target_id):
    if target_id:
        return target_id
    visible = (c.get("perception") or {}).get("visible_people", [])
    if visible:
        return max(visible, key=lambda p: p.get("visibility", 0)).get("id")
    return None


def answering(c, world, target_id):
    if not target_id:
        return False
    from brain.conversations import find_conversation
    conv = find_conversation(world, [c["id"], target_id])
    f = (conv or {}).get("floor") or {}
    return bool(conv and conv.get("active") and f.get("state") != "closed" and f.get("holder") == c["id"]
                and f.get("from") == target_id)


def repeat_dropped(c, world, utterance, target_id):
    """Said once: the same line to the same person again is dropped (systems/speech_repeat.py) -- unless it is an
    answer. Someone holding the floor of a live conversation with this person is being waited on: "Okay!" said twice
    in half an hour is ordinary talk, and dropping it made the other person's wait run out."""
    from systems.speech_repeat import is_repeat
    return is_repeat(c, world, utterance, target_id) and not answering(c, world, target_id)


def floor_blocks(world, speaker_id, target_id, medium="in_person"):
    """Ball discipline (systems/conversation_floor.py): while the other person holds the floor and is still within
    their time to respond, a line from the speaker is dropped rather than talking over them. With CPL_MODE=on, the
    same for an invitation not yet answered: its initiator waits (cpl/state_machine.py rejects the line anyway)."""
    if not target_id or medium not in ("in_person", "call"):
        return False
    if pending_invitation(world, speaker_id, target_id):
        return True
    from brain.conversations import find_conversation
    from systems.conversation_floor import blocks
    existing = find_conversation(world, [speaker_id, target_id])
    return bool(existing and blocks(world, existing, speaker_id))


def earshot(world, speaker, listener, volume):
    """Face to face: (heard, reach). Too far away or through walls (the test perception uses) -> not heard."""
    from systems.conversation_reach import check_pair
    reach = check_pair(world, speaker, listener, volume)
    return not any(i.startswith("too far") for i in reach["issues"]), reach


def channel_open(world, listener, medium):
    """A call needs someone to answer: a usable phone, and not in a meeting (the answering-machine gate). A text or an
    email always sends and just sits unread; face to face is earshot's question."""
    if medium != "call":
        return True
    from systems.personal_items import phone_is_usable
    in_meeting = world.get("tick", 0) < listener.get("_work_busy_until_tick", 0)
    return phone_is_usable(listener) and not in_meeting


def pending_invitation(world, speaker_id, target_id):
    """CPL_MODE=on: speaker_id opened a conversation with target_id that target_id has not answered yet."""
    from cpl import config, store
    if config.mode(world) != "on":
        return False
    for conv in store.live(world, speaker_id):
        if conv.get("state") == "pending" and conv.get("initiator_id") == speaker_id \
                and target_id in (conv.get("participants") or {}):
            return True
    return False


def join(world, conv, char_id, by=None):
    """Someone joins a conversation under way (NEXT: let_join, cpl/turns.py). They know what is said from now on, and
    only a summary of what came before (their knowledge boundary: joined_at_seq). The legacy conversation takes them
    in too, with the tick they joined at (brain/context_builder.py shows them only the lines since)."""
    from core.clock import now_ts
    from core.event_bus import emit
    from cpl.lifecycle import summarize
    parts = conv.setdefault("participants", {})
    if char_id in parts and parts[char_id].get("status") == "active":
        return False
    parts[char_id] = {"role": "participant", "status": "active", "joined_at": now_ts(world), "left_at": None,
                      "left_reason": None, "last_seen_seq": conv.get("seq", 0), "joined_at_seq": conv.get("seq", 0),
                      "summary_at_join": summarize(conv, world), "invited_by": by}
    legacy = (world.get("conversations") or {}).get(conv.get("legacy_id")) if conv.get("legacy_id") else None
    if legacy is not None:
        if char_id not in legacy.setdefault("participants", []):
            legacy["participants"].append(char_id)
        legacy.setdefault("joined_ticks", {})[char_id] = world.get("tick", 0)
        legacy.setdefault("joined_summaries", {})[char_id] = parts[char_id]["summary_at_join"]
    emit("cpl.participant_joined", {"conversation_id": conv["id"], "who": char_id, "by": by,
                                    "joined_at_seq": parts[char_id]["joined_at_seq"]})
    return True


def overhearers(world, speaker, participant_ids, radius=6.0):
    """Who hears a line said aloud without being in the conversation: awake, on the map, within earshot of the speaker
    (same building, or close by outdoors) -- read from the positions model (core/positions.py), reaching nobody."""
    from core import positions
    out = []
    for cid, alive, obid in positions.ids_near(world, speaker, radius=radius):
        if cid in participant_ids or not alive or obid != speaker.get("building_id"):
            continue
        o = dict.get(world.get("characters") or {}, cid) or {}
        if o.get("off_grid") or (o.get("activity") or {}).get("type") in ("sleep", "nap"):
            continue
        out.append(cid)
    return out
