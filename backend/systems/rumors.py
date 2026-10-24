"""
systems/rumors.py -- what is said ABOUT someone behind their back (docs/relationship_impact_plan.md, section 6:
"mentioned to a third party").

A character tells a listener something about a third person who is not part of the conversation -- gossip, a lie about
them (slander), or praise. Three things follow:

  1. The LISTENER weighs it. How far they believe it depends on how much they trust and like the speaker and how
     they feel about the subject (a friend's honour is defended). A believed remark shifts the listener's own
     feelings about the subject a little and is remembered ("X told me that Y ...").
  2. It becomes a RUMOR (world["rumors"]) that the believers carry. Nothing is written on the speaker/subject pair's
     ledger yet: the subject has not heard it. (If the subject WAS within earshot the ordinary speech path
     already handled it -- they are a `mentioned` hearer there.)
  3. A believer who later finds themselves near the subject may TELL them. Then it arrives through the learned
     channel: the ordinary evaluation ladder runs for the subject (it is delivered, so it is perceivable and
     aimed at them), and if it registers it is written on the (speaker, subject) pair -- which is where a grudge can
     open against the person who said it. The teller's own part (loose tongue or honest friend) is remembered too.

Kinds: a hurtful remark is `meanness`, a lie about someone `slander`, praise `compliment`. Rumors lapse after
RUMOR_LIFETIME_TICKS and are told at most once to the subject.
"""

import random

from core.event_bus import emit, subscribe

HOUR = 3600
RUMOR_LIFETIME_TICKS = 72 * HOUR
TELL_CHANCE_PER_LOOK = 0.15              # per believer, per look (every 5 sim-minutes) while the subject is in view
MAX_RUMORS = 200
BELIEF_FLOOR, BELIEF_CEIL = 0.1, 0.95
LISTENER_SCALE = 0.6                     # how much of the kind's effect a believed remark has on the listener's own view
CHATTY_TRAITS = {"gossipy", "talkative", "honest", "loyal", "tactless", "blunt", "extroverted", "charismatic"}
DISCREET_TRAITS = {"secretive", "discreet", "reserved", "tactful", "diplomatic", "private"}

# What a believed remark does to the listener's feelings about the SUBJECT, per 10 points of value.
REMARK_DELTAS = {
    -1: {"friendship": -2.0, "respect": -2.0, "trust": -1.0},
    +1: {"friendship": 1.5, "respect": 2.0, "trust": 1.0},
}


def remark_kind(speech_act, intent):
    """The impact kind of a remark about a third person, or None if the line says nothing about them in this sense."""
    valence = (intent or {}).get("valence") if isinstance(intent, dict) else None
    act = (speech_act or "").lower()
    if valence == "deceive" or act == "lie":
        return "slander"
    if valence == "hurt" or act == "gossip":
        return "meanness"
    if valence == "help":
        return "compliment"
    return None


def emit_remark(speaker, listener, subject_id, kind, *, text, magnitude=None, discretion=0.6, ref=None):
    """From the speech path (a worker thread): only posts an event."""
    emit("third_party_remark", {"speaker_id": speaker["id"], "listener_id": listener["id"], "subject_id": subject_id,
                                "kind": kind, "magnitude": magnitude, "discretion": discretion, "text": text, "ref": ref})


def _rel(c, other_id):
    return (c.get("relationships") or {}).get(other_id) or {}


def credibility(listener, speaker_id, subject_id, kind, polarity):
    rel_s, rel_x = _rel(listener, speaker_id), _rel(listener, subject_id)
    c = 0.35 + (rel_s.get("trust", 0) or 0) / 150.0 + (rel_s.get("friendship", 0) or 0) / 300.0
    if polarity < 0:
        c -= ((rel_x.get("friendship", 0) or 0) + (rel_x.get("trust", 0) or 0)) / 300.0     # a friend of the subject resists
    if kind == "slander":
        c -= 0.15                                                                           # a lie has to be swallowed
    if (listener.get("age") or 30) < 10:
        c += 0.2                                                                            # children believe what they are told
    return max(BELIEF_FLOOR, min(BELIEF_CEIL, c))


def _on_remark(data, world):
    chars = world.get("characters", {})
    speaker, listener, subject = chars.get(data["speaker_id"]), chars.get(data["listener_id"]), chars.get(data["subject_id"])
    if not speaker or not listener or not subject or subject["id"] in (speaker["id"], listener["id"]):
        return None
    from systems import impact_kinds
    specs = impact_kinds.kinds(world)
    kind = data["kind"]
    if kind not in specs:
        return None
    spec = specs[kind]
    polarity = spec["polarity"]
    M = data.get("magnitude") if data.get("magnitude") is not None else spec["base"]
    tick = world.get("tick", 0)
    believed = random.random() < credibility(listener, speaker["id"], subject["id"], kind, polarity)
    if believed:
        _shift_listener(listener, subject["id"], polarity, M)
    _remember(listener, speaker, subject, kind, data.get("text"), believed, tick)
    rumors = world.setdefault("rumors", {})
    rid = next((k for k, r in rumors.items() if r["source"] == speaker["id"] and r["subject"] == subject["id"]
                and r["kind"] == kind and r["text"] == (data.get("text") or "")[:160]), None)
    if rid is None:
        rid = f"rumor_{tick}_{len(rumors)}"
        rumors[rid] = {"id": rid, "source": speaker["id"], "subject": subject["id"], "kind": kind, "polarity": polarity,
                       "magnitude": M, "discretion": data.get("discretion", 0.6), "text": (data.get("text") or "")[:160],
                       "tick": tick, "believers": [], "told_to_subject": False, "ref": data.get("ref")}
        for old in sorted(rumors, key=lambda k: rumors[k]["tick"])[:max(0, len(rumors) - MAX_RUMORS)]:
            rumors.pop(old, None)
    if believed and listener["id"] not in rumors[rid]["believers"]:
        rumors[rid]["believers"].append(listener["id"])
    return rumors[rid], believed


def _shift_listener(listener, subject_id, polarity, value):
    from brain.relationships import ensure_relationship
    rel = ensure_relationship(listener, subject_id)
    for field, per10 in REMARK_DELTAS[polarity].items():
        rel[field] = round(max(-100, min(100, (rel.get(field, 0) or 0) + per10 * value / 10.0 * LISTENER_SCALE)), 3)


def _remember(listener, speaker, subject, kind, text, believed, tick):
    try:
        from brain.memory import store_memory
        said = f"\"{text}\"" if text else "something"
        mood = "" if believed else " I'm not sure I believe it."
        what = "praised" if kind == "compliment" else "talked about"
        store_memory(listener, f"{speaker['name']} {what} {subject['name']} to me: {said}.{mood}",
                     importance=0.45 if believed else 0.3, tags=["gossip", "rumor"], people=[speaker["id"], subject["id"]],
                     tick=tick, source="heard")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# carrying it to the subject
# ---------------------------------------------------------------------------

def tick_rumors(world):
    """Scheduled job: believers near the subject may tell them; old rumors lapse."""
    tick = world.get("tick", 0)
    chars = world.get("characters", {})
    rumors = world.get("rumors")
    if not rumors:
        return
    for rid in list(rumors):
        r = rumors[rid]
        if r["told_to_subject"] or tick - r["tick"] > RUMOR_LIFETIME_TICKS:
            if tick - r["tick"] > RUMOR_LIFETIME_TICKS:
                rumors.pop(rid, None)
            continue
        subject = chars.get(r["subject"])
        if not subject or subject.get("alive") is False or subject.get("off_grid"):
            continue
        for bid in r["believers"]:
            teller = chars.get(bid)
            if not teller or teller.get("alive") is False or teller.get("off_grid"):
                continue
            if not any(p.get("id") == subject["id"] for p in (teller.get("perception") or {}).get("visible_people", [])):
                continue
            if random.random() < _tell_chance(teller, subject, r):
                _tell(world, r, teller, subject)
                break


def _tell_chance(teller, subject, rumor):
    traits = set(teller.get("traits") or [])
    f = max(0.3, min(1.5, 0.3 + (_rel(teller, subject["id"]).get("friendship", 0) or 0) / 60.0))
    if traits & CHATTY_TRAITS:
        f *= 1.6
    if traits & DISCREET_TRAITS:
        f *= 0.4
    if rumor["polarity"] > 0:
        f *= 1.5                                       # good news is easier to pass on
    return TELL_CHANCE_PER_LOOK * f


def _tell(world, rumor, teller, subject):
    chars = world.get("characters", {})
    speaker = chars.get(rumor["source"])
    if not speaker:
        rumor["told_to_subject"] = True
        return
    rumor["told_to_subject"] = True
    rumor["told_by"] = teller["id"]
    rumor["told_tick"] = world.get("tick", 0)
    # delivered straight to them: the ladder runs for the subject; if it registers, it is written on (speaker, subject)
    emit("impact_intent", {
        "source_id": speaker["id"], "target_id": subject["id"], "kind": rumor["kind"], "magnitude": rumor["magnitude"],
        "discretion": 0.1, "channel": "learned_secondhand", "audience": "targets", "volume": "low",
        "text": rumor["text"], "ref": {"type": "rumor", "id": rumor["id"], "told_by": teller["id"]},
        "mentions": [], "victim_id": None, "memory_refs": [],
    })
    try:
        from brain.memory import store_memory
        tick = world.get("tick", 0)
        about = "said nice things about" if rumor["polarity"] > 0 else "was talking about"
        store_memory(subject, f"{teller['name']} told me that {speaker['name']} {about} me: \"{rumor['text']}\".",
                     importance=0.6, tags=["gossip", "rumor", "heard_about_me"], people=[teller["id"], speaker["id"]],
                     tick=tick, source="heard")
        store_memory(teller, f"I told {subject['name']} what {speaker['name']} had said about them.",
                     importance=0.3, tags=["gossip", "rumor"], people=[subject["id"], speaker["id"]], tick=tick, source="internal")
    except Exception:
        pass


subscribe("third_party_remark", _on_remark)
