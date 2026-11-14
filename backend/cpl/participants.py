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
    their time to respond, a line from the speaker is dropped rather than talking over them."""
    if not target_id or medium not in ("in_person", "call"):
        return False
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
