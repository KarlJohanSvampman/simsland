"""
systems/conversation_archive.py

Every conversation, kept as its own record -- and what it was about, read by the AI.

A conversation is one sitting: one talk in person or one call, start to end. It is never resumed later -- the next
talk between the same people is a new conversation (brain/conversations.py used to fold every talk between the same
people into one running thread, which read like one endless conversation). It ends when it is settled, when it has
gone on long enough (systems/conversation_outcome.py), when someone leaves, or when someone stops answering.

Each finished conversation becomes:

    world["conversation_archive"][conv id] = {
        "id", "participants", "names", "initiator", "medium", "started_tick", "ended_tick", "end_reason",
        "lines": [{tick, speaker, utterance, speech_act}],
        "tags": None | the AI's reading (llm/conversation_tags.py),
        "subject", "topic_tags", "interaction_tags", "tone", "issue_ids", "confrontation_id", "contract_ids",
    }

and an entry of the same shape in each participant's c["conversation_log"] (what the Inspector's Conversations tab
lists, filterable by person).

The tags come from the AI (llm/conversation_tags.py, on a bg_llm worker), and what they add up to is applied by
social/discourse.py: the subject, topic and interaction tags and tone; the issues it raised or carried on, with each
person's position (social/issues.py); how a confrontation in it ended (social/confrontations.py); an agreement made,
renegotiated or broken (social/contracts.py); how the opener's approach was received (social/initiative.py); what each
now makes of the other (social/standing.py); and what was said about people who weren't there (social/rumours.py).
No programmatic fallback: an untagged conversation is tried again (up to TAG_TRIES times).
"""

from core import scheduler

ARCHIVE_CAP = 3000
LOG_CAP = 60
TAG_TRIES = 3
SERVICE_EVERY = 5
EARLIER_SHOWN = 5



# =========================================================
# ARCHIVING
# =========================================================

def archive(world, conv):
    """A conversation has ended: keep it, give each participant their copy, and queue it for tagging."""
    chars = world.get("characters") or {}
    lines = [{"tick": h.get("tick"), "speaker": h.get("speaker"), "utterance": h.get("utterance"),
              "speech_act": h.get("speech_act")} for h in conv.get("history") or [] if h.get("utterance")]
    participants = [p for p in conv.get("participants") or [] if p in chars]
    if not lines or len(participants) < 2:
        return None
    entry = {
        "id": conv["id"], "participants": participants,
        "names": {p: chars[p].get("name") for p in participants},
        "initiator": lines[0].get("speaker"),
        "medium": conv.get("medium", "in_person"),
        "started_tick": conv.get("started_at"), "ended_tick": conv.get("last_update"),
        "end_reason": conv.get("end_reason"),
        "topic": conv.get("topic"), "subject": conv.get("subject"),
        "lines": lines, "tags": None, "tag_tries": 0,
        "target_id": conv.get("target_id"), "location_id": conv.get("location_id"),
        "interaction_tags": list(conv.get("interaction_tags") or []),
        "issue_ids": list(conv.get("related_issue_ids") or []),
        "confrontation_id": conv.get("related_confrontation_id"), "contract_ids": [],
        "status": "completed",
    }
    store = world.setdefault("conversation_archive", {})
    store[entry["id"]] = entry
    if len(store) > ARCHIVE_CAP:
        for old in sorted(store, key=lambda k: store[k].get("ended_tick") or 0)[:len(store) - ARCHIVE_CAP]:
            store.pop(old, None)
    for pid in participants:
        _to_log(chars[pid], entry)
    world.setdefault("_conv_tag_queue", []).append(entry["id"])
    return entry


def unarchive(world, conv_id):
    """A conversation that turned out not to be over (it was picked up again within the minute)."""
    store = world.get("conversation_archive") or {}
    entry = store.pop(conv_id, None)
    if not entry:
        return
    for pid in entry.get("participants") or []:
        c = (world.get("characters") or {}).get(pid)
        if c:
            c["conversation_log"] = [e for e in c.get("conversation_log") or [] if e.get("id", e.get("conv_id")) != conv_id]
    world["_conv_tag_queue"] = [x for x in world.get("_conv_tag_queue") or [] if x != conv_id]


def _log_copy(entry, me):
    return {k: entry.get(k) for k in ("id", "participants", "names", "initiator", "medium", "started_tick",
                                       "ended_tick", "end_reason", "topic", "subject", "lines", "tags", "status",
                                       "issue_ids", "confrontation_id", "contract_ids", "interaction_tags", "tone",
                                       "target_id", "location_id")} | {
        "conv_id": entry["id"],
        "with": [{"id": p, "name": entry["names"].get(p)} for p in entry["participants"] if p != me]}


def _to_log(c, entry):
    log = [e for e in c.get("conversation_log") or [] if not e.get("conv_ids") or len(e.get("conv_ids")) <= 1]
    log = [e for e in log if e.get("id", e.get("conv_id")) != entry["id"]]
    log.append(_log_copy(entry, c["id"]))
    log.sort(key=lambda e: e.get("ended_tick") or 0)
    c["conversation_log"] = log[-LOG_CAP:]


def _refresh_logs(world, entry):
    chars = world.get("characters") or {}
    for pid in entry["participants"]:
        c = chars.get(pid)
        if not c:
            continue
        for i, e in enumerate(c.get("conversation_log") or []):
            if e.get("id", e.get("conv_id")) == entry["id"]:
                c["conversation_log"][i] = _log_copy(entry, pid)


def earlier_between(world, entry, limit=EARLIER_SHOWN):
    pair = set(entry["participants"])
    store = world.get("conversation_archive") or {}
    found = [e for e in store.values() if e["id"] != entry["id"] and set(e["participants"]) == pair
             and (e.get("ended_tick") or 0) <= (entry.get("started_tick") or 0)]
    found.sort(key=lambda e: -(e.get("ended_tick") or 0))
    return found[:limit]


# =========================================================
# TAGGING (the AI reads it)
# =========================================================

def _transcript(entry):
    return "\n".join(f"{entry['names'].get(l['speaker'], l['speaker'])}: {l['utterance']}" for l in entry["lines"])


def _service(world, timer=None):
    from systems import bg_llm
    from llm.conversation_tags import tag
    queue = world.get("_conv_tag_queue") or []
    store = world.get("conversation_archive") or {}
    keep = []
    for cid in queue:
        entry = store.get(cid)
        if not entry or entry.get("tags"):
            continue
        key = f"convtag:{cid}"
        ready, result = bg_llm.take(key)
        if ready:
            if result:
                apply_tags(world, entry, result)
                continue
            entry["tag_tries"] = entry.get("tag_tries", 0) + 1
            if entry["tag_tries"] >= TAG_TRIES:
                continue                              # the model couldn't read it; left untagged
        if not bg_llm.is_pending(key):
            earlier = [{"id": e["id"], "subject": (e.get("tags") or {}).get("subject"),
                        "when": e.get("ended_tick")} for e in earlier_between(world, entry)]
            from social.discourse import context_for_reader
            bg_llm.submit(key, tag, _transcript(entry), list(entry["names"].values()), earlier,
                          context_for_reader(world, entry))
        keep.append(cid)
    world["_conv_tag_queue"] = keep[-200:]


def apply_tags(world, entry, tags):
    """The AI's reading of the conversation: kept on the record, and what it adds up to applied
    (social/discourse.py: issues and positions, the confrontation's outcome, agreements, initiative, standing,
    rumours)."""
    entry["tags"] = tags
    from social.discourse import after
    after(world, entry, tags)
    _rewrite_memories(world, entry, tags)
    _refresh_logs(world, entry)


def _rewrite_memories(world, entry, tags):
    """The one memory each person wrote of this talk (brain/conversations.py) said only who it was with and their
    first line; now that the AI has read the whole thing, say what it was about."""
    subject = (tags.get("subject") or "").strip()
    if not subject:
        return
    chars = world.get("characters") or {}
    opening = (tags.get("opening") or "").replace("_", " ")
    for pid in entry.get("participants") or []:
        c = chars.get(pid)
        if not c:
            continue
        names = " and ".join(entry["names"].get(o) or "someone" for o in entry["participants"] if o != pid)
        medium = " on the phone" if entry.get("medium") == "phone" else ""
        if entry.get("initiator") == pid:
            how = f", I opened with {opening}" if opening and opening != "small talk" else ""
        else:
            how = f", they opened with {opening}" if opening and opening != "small talk" else ""
        text = f"Talked with {names}{medium} about {subject}{how}."
        for m in c.get("memories") or []:
            if m.get("conv_id") == entry["id"] and str(m.get("text", "")).startswith("Talked with"):
                m["text"] = text
                m.setdefault("tags", []).append(subject)


# (scheduled from core/flow.py)
