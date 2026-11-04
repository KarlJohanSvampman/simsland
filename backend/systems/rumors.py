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
  3. (now) Whoever has heard it may pass it on -- or tell the subject -- in their own conversations; the AI reading
     the conversation says so (social/discourse.py, social/rumours.py). Formerly: a believer near the subject may TELL them. Then it arrives through the learned
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
HEARD_OF_FAMILIARITY = 2                 # familiarity a believed compliment gives with someone the listener had not met
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


def emit_remark(speaker, listener, subject_id, kind, *, text, magnitude=None, discretion=0.6, ref=None, via=None):
    """From the speech path (a worker thread): only posts an event."""
    emit("third_party_remark", {"speaker_id": speaker["id"], "listener_id": listener["id"], "subject_id": subject_id,
                                "kind": kind, "magnitude": magnitude, "discretion": discretion, "text": text, "ref": ref, "via": via})


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


def _shift_listener(listener, subject_id, polarity, value):
    """A believed remark moves the listener's own feelings about the subject a little; praise makes a stranger a
    name they know."""
    from brain.relationships import ensure_relationship
    rel = ensure_relationship(listener, subject_id)
    for field, per10 in REMARK_DELTAS[polarity].items():
        rel[field] = round(max(-100, min(100, (rel.get(field, 0) or 0) + per10 * value / 10.0 * LISTENER_SCALE)), 3)
    if polarity > 0 and (rel.get("familiarity", 0) or 0) < HEARD_OF_FAMILIARITY:
        rel["familiarity"] = HEARD_OF_FAMILIARITY


def _on_remark(data, world):
    """A remark about someone outside the conversation (an online post, systems/online_posts.py): passed on as a
    rumour transmission (social/rumours.py) -- the listener's own credibility judgement, no dice."""
    chars = world.get("characters", {})
    speaker, listener, subject = chars.get(data["speaker_id"]), chars.get(data["listener_id"]), chars.get(data["subject_id"])
    if not speaker or not listener or not subject or subject["id"] in (speaker["id"], listener["id"]):
        return None
    tone = {"slander": -2, "meanness": -1, "compliment": 1}.get(data.get("kind"), 0)
    from social import rumours as R
    return R.transmit(world, speaker["id"], listener["id"], subject["id"], data.get("text") or "", tone=tone,
                      rumour=data.get("kind") == "slander" or data.get("via") == "post", conv_id=None,
                      via=data.get("via"), ref=(data.get("ref") or {}).get("id") if isinstance(data.get("ref"), dict) else data.get("ref"))


def tick_rumors(world):
    """Scheduled job: online posts get discovered; old talk is forgotten. Passing a rumour on -- including to the
    person it's about -- is the characters' own choice, in conversation (social/discourse.py)."""
    try:
        from systems.online_posts import tick_post_discovery
        tick_post_discovery(world)
    except Exception as exc:
        print(f"[online_posts] discovery failed: {exc!r}")
    from social import rumours as R
    R.tick(world)


subscribe("third_party_remark", _on_remark)
