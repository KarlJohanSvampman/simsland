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
        "tags": None | {"subject", "opening", "tags", "relates_to", "argument", "about_others"},
        "argument_id": None | the argument it was part of,
    }

and an entry of the same shape in each participant's c["conversation_log"] (what the Inspector's Conversations tab
lists, filterable by person).

The tags come from the AI (llm/conversation_tags.py, on a bg_llm worker): the subject; what the one who started it
opened with (a suggestion, a request, criticism, ...); a few tags; the earlier conversation it refers back to; whether
it was an argument (and of which kind -- the types of the disputes format); and what was said about people who weren't
there. No programmatic fallback: an untagged conversation is tried again (up to TAG_TRIES times).

What the tags lead to:
  - an argument: the conversation is filed under an argument record (world["arguments"], mirrored on each party as
    c["argument_log"]), the same argument when it continues an earlier conversation that was part of one, or one
    already open between them about the same subject; otherwise a new one. Fights between them are filed there too
    (core/event_handlers.py), and an argument is marked resolved when the rift between them closes (systems/rifts.py);
  - things said about someone absent -- gossip, rumours, praise: each listener's view of that person moves (standing
    and agitation, systems/feelings.py), more if they trust whoever said it, less for hearsay; it's in their standing
    history with what was said and by whom.
"""

from core import scheduler

ARCHIVE_CAP = 3000
LOG_CAP = 60
TAG_TRIES = 3
SERVICE_EVERY = 5
EARLIER_SHOWN = 5

ARG_LOG_CAP = 40


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
        "topic": conv.get("topic"),
        "lines": lines, "tags": None, "argument_id": None, "tag_tries": 0,
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


def _log_copy(entry, me):
    return {k: entry.get(k) for k in ("id", "participants", "names", "initiator", "medium", "started_tick",
                                       "ended_tick", "end_reason", "topic", "lines", "tags", "argument_id")} | {
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
            bg_llm.submit(key, tag, _transcript(entry), list(entry["names"].values()), earlier)
        keep.append(cid)
    world["_conv_tag_queue"] = keep[-200:]


def apply_tags(world, entry, tags):
    entry["tags"] = tags
    if tags.get("argument"):
        file_under_argument(world, entry, tags["argument"])
    if tags.get("about_others"):
        _hearsay(world, entry, tags["about_others"])
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


# =========================================================
# ARGUMENTS
# =========================================================

def _pair(ids):
    return sorted(ids)[:2]


def _arg_sync(world, arg):
    chars = world.get("characters") or {}
    for pid in arg["parties"]:
        c = chars.get(pid)
        if not c:
            continue
        log = [a for a in c.get("argument_log") or [] if a["id"] != arg["id"]]
        log.append(dict(arg))
        log.sort(key=lambda a: a.get("opened_tick") or 0)
        c["argument_log"] = log[-ARG_LOG_CAP:]


def open_argument(world, parties, kind, subject, initiator=None, tick=None):
    import uuid
    arg = {"id": f"arg_{uuid.uuid4().hex[:6]}", "parties": _pair(parties), "type": kind or "unspecified",
           "subject": subject or "something", "initiator": initiator, "opened_tick": tick or world.get("tick", 0),
           "status": "open", "resolved_tick": None, "resolution": None,
           "conversation_ids": [], "fight_ids": [], "events": []}
    world.setdefault("arguments", {})[arg["id"]] = arg
    return arg


def open_arguments_between(world, a, b):
    pair = _pair([a, b])
    return [arg for arg in (world.get("arguments") or {}).values()
            if arg["parties"] == pair and arg["status"] == "open"]


def _name_to_id(world, entry, name):
    for pid, n in (entry.get("names") or {}).items():
        if n and name and (n.lower() == name.lower() or n.split(" ")[0].lower() == name.lower()):
            return pid
    return None


def file_under_argument(world, entry, arg_tags):
    if len(entry["participants"]) < 2:
        return None
    a, b = entry["participants"][:2]
    store = world.get("conversation_archive") or {}
    target = None
    rel = entry["tags"].get("relates_to") if entry.get("tags") else None
    if rel and (store.get(rel) or {}).get("argument_id"):
        target = (world.get("arguments") or {}).get(store[rel]["argument_id"])
    if target is None:
        subject = (arg_tags.get("subject") or "").lower()
        for arg in open_arguments_between(world, a, b):
            if arg["subject"].lower() == subject or arg["type"] == arg_tags.get("type"):
                target = arg
                break
    if target is None:
        target = open_argument(world, entry["participants"], arg_tags.get("type"), arg_tags.get("subject"),
                               initiator=_name_to_id(world, entry, arg_tags.get("started_by")) or entry["initiator"],
                               tick=entry.get("started_tick"))
    if entry["id"] not in target["conversation_ids"]:
        target["conversation_ids"].append(entry["id"])
        target["events"].append({"tick": entry.get("ended_tick"), "what": "conversation",
                                 "detail": (entry.get("tags") or {}).get("subject"), "conv_id": entry["id"]})
    entry["argument_id"] = target["id"]
    _arg_sync(world, target)
    from systems.feelings import note
    chars = world.get("characters") or {}
    for me, other in ((a, b), (b, a)):
        if me in chars:
            note(chars[me], other, world, f"argued about {target['subject']} ({target['type'].replace('_', ' ')})")
    return target


def file_fight(world, fight):
    """A fight between two people goes on the argument between them (the open one about the same thing, else the
    most recent open one, else a new one)."""
    parties = [p for p in fight.get("parties") or [] if p in (world.get("characters") or {})]
    if len(parties) < 2:
        return None
    a, b = parties[:2]
    open_ones = open_arguments_between(world, a, b)
    topic = (fight.get("topic") or "").lower()
    target = next((g for g in open_ones if g["subject"].lower() == topic), None) or \
        (max(open_ones, key=lambda g: g["opened_tick"]) if open_ones else None)
    if target is None:
        target = open_argument(world, parties, "unspecified", fight.get("topic"), initiator=fight.get("aggressor"),
                               tick=fight.get("tick"))
    if fight.get("id") not in target["fight_ids"]:
        target["fight_ids"].append(fight.get("id"))
        target["events"].append({"tick": fight.get("tick"), "what": "fight",
                                 "detail": f"{fight.get('topic')}: {str(fight.get('outcome', '')).replace('_', ' ')}"
                                           + (f", peaked at {fight['peak'].replace('_', ' ')}" if fight.get("peak") else ""),
                                 "fight_id": fight.get("id")})
    _arg_sync(world, target)
    return target


def resolve_between(world, a, b, how):
    for arg in open_arguments_between(world, a, b):
        arg["status"] = "resolved"
        arg["resolved_tick"] = world.get("tick", 0)
        arg["resolution"] = how
        arg["events"].append({"tick": world.get("tick", 0), "what": "resolved", "detail": how})
        _arg_sync(world, arg)


# =========================================================
# HEARSAY: what's said about someone who isn't there
# =========================================================

def _hearsay(world, entry, about):
    from systems.feelings import agitate, note, standing as feel
    chars = world.get("characters") or {}
    by_name = {}
    for cid, c in chars.items():
        if c.get("name"):
            by_name[c["name"].lower()] = cid
            by_name.setdefault(c["name"].split(" ")[0].lower(), cid)
    for item in about:
        subject_id = by_name.get(item["name"].lower())
        if not subject_id or subject_id in entry["participants"]:
            continue
        speaker_id = _name_to_id(world, entry, item.get("said_by")) or entry["initiator"]
        for listener_id in entry["participants"]:
            if listener_id == speaker_id:
                continue
            listener = chars.get(listener_id)
            if not listener:
                continue
            trust = ((listener.get("relationships") or {}).get(speaker_id) or {}).get("trust") or 0
            weight = max(0.2, min(1.0, 0.5 + trust / 200.0)) * (0.5 if item.get("rumour") else 1.0)
            tone = item.get("tone", 0)
            rel = listener.setdefault("relationships", {}).setdefault(subject_id, {})
            if tone < 0:
                rel["resentment"] = min(100, (rel.get("resentment") or 0) + round(-tone * 6 * weight, 1))
                rel["trust"] = max(-100, (rel.get("trust") or 0) - round(-tone * 4 * weight, 1))
                agitate(listener, subject_id, world, -tone * 5 * weight)
            elif tone > 0:
                rel["friendship"] = min(100, (rel.get("friendship") or 0) + round(tone * 4 * weight, 1))
                rel["respect"] = min(100, (rel.get("respect") or 0) + round(tone * 3 * weight, 1))
            speaker = entry["names"].get(speaker_id, "someone")
            note(listener, subject_id, world,
                 f"heard from {speaker}{' (a rumour)' if item.get('rumour') else ''}: {item.get('claim')}")


scheduler.register_recurring("convtags", _service, SERVICE_EVERY)
