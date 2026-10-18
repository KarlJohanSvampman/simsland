"""
systems/expressions.py

One-way verbal expressions: exclaims, remarks, mutters, vents, shouts, curses --
speech that is NOT an attempt to start a conversation.

Before this, every line a character spoke either threaded into a conversation
(apply_speech() defaults an untargeted line to whoever is nearest, which then
owes a reply and holds "the ball", see systems/conversation_floor.py) or was a
bubble with no audience bookkeeping at all (incidental_speech.fire_incidental).
A muttered "I can't stand this" or a yelled insult across the yard is neither.

An expression:
  - shows a speech bubble like any other line (volume decides how far it carries)
  - never creates a conversation, a floor, or an obligation to answer
  - records who could actually hear it (range, walls, sleep, hearing traits) and
    how clearly, who it was aimed at, and who was mentioned by name
  - emits `expression_made` for the relationship-impact system to evaluate
    per hearer, and wakes a hearer only if it was aimed at / named them (they
    may then answer, which is an ordinary new conversation)

An expression is chosen by the speaker's model (`REMARK:` line) or by speech
act (EXPRESSION_ACTS).
"""

import re

SPEECH_BUBBLE_TICKS = 8
RECENT_EXPRESSIONS_CAP = 60

EXPRESSION_ACTS = {
    "exclaim", "remark", "mutter", "mumble", "grumble", "vent", "shout", "yell",
    "curse", "sigh", "sing", "hum",
}

_VOLUME_BY_ACT = {
    "shout": "high", "yell": "high",
    "mutter": "low", "mumble": "low", "grumble": "low", "sigh": "low", "hum": "low",
}


def is_expression(speech):
    if not speech:
        return False
    if (speech.get("mode") or "").lower() == "remark":
        return True
    return (speech.get("speech_act") or "").lower() in EXPRESSION_ACTS


def default_volume(speech_act):
    return _VOLUME_BY_ACT.get((speech_act or "").lower(), "medium")


def _is_npc(c):
    return bool(c.get("is_workplace_npc") or c.get("is_service_worker"))


def audience(world, speaker, volume):
    """Everyone who could hear `speaker` at this volume, with how clearly (0-1).
    Same rules perceive_audio() uses: tiered range scaled by hearing traits,
    walls/rooms muffle, a sleeper only hears yells or louder."""
    from brain.perception import (
        VOLUME_TIERS, SLEEP_HEARING_MIN_VOLUME, DEFAULT_VOLUME,
        volume_range, sound_modifier, manhattan,
    )
    sleep_min = VOLUME_TIERS[SLEEP_HEARING_MIN_VOLUME]
    tier = VOLUME_TIERS.get(volume, VOLUME_TIERS[DEFAULT_VOLUME])
    out = []
    for other in world.get("characters", {}).values():
        if other.get("id") == speaker.get("id") or _is_npc(other) or other.get("alive") is False:
            continue
        if other.get("x") is None or other.get("y") is None or speaker.get("x") is None:
            continue
        asleep = (other.get("activity") or {}).get("type") == "sleep"
        if asleep and tier < sleep_min:
            continue
        hrange = volume_range(other, volume)
        if not hrange:
            continue
        effective = manhattan(other, speaker) / max(0.01, sound_modifier(other, speaker, volume))
        if effective > hrange:
            continue
        out.append({"id": other["id"], "clarity": round(max(0.0, 1 - effective / hrange), 2), "asleep": asleep})
    return out


def mentions(world, text, speaker_id):
    """Ids of characters named in the text (full name or first name), whether or
    not they are present."""
    found = []
    low = text or ""
    for c in world.get("characters", {}).values():
        if c.get("id") == speaker_id or _is_npc(c):
            continue
        name = (c.get("name") or "").strip()
        if not name:
            continue
        first = name.split()[0]
        for token in {name, first}:
            if len(token) >= 3 and re.search(r"\b" + re.escape(token) + r"\b", low, re.I):
                found.append(c["id"])
                break
    return found


def broadcast(speaker, world, text, speech_act="exclaim", volume=None, target_id=None, intent=None):
    """Work out the audience, log the expression and tell the rest of the sim.
    Does not touch the speaker's bubble -- express() / fire_incidental() do that."""
    tick = world.get("tick", 0)
    volume = volume or default_volume(speech_act)
    named = mentions(world, text, speaker["id"])
    hearers = []
    for h in audience(world, speaker, volume):
        h["directed"] = h["id"] == target_id
        h["mentioned"] = h["id"] in named
        hearers.append(h)
    record = {
        "id": f"expr_{tick}_{speaker['id'][-4:]}_{len(world.get('expressions', []))}",
        "tick": tick,
        "speaker": speaker["id"],
        "text": text,
        "speech_act": speech_act,
        "volume": volume,
        "target": target_id,
        "mentions": named,
        "hearers": hearers,
        "intent": intent,
    }
    log = world.setdefault("expressions", [])
    log.append(record)
    del log[:-RECENT_EXPRESSIONS_CAP]

    from core.event_bus import emit
    emit("expression_made", dict(record, x=speaker.get("x"), y=speaker.get("y"),
                                 building_id=speaker.get("building_id")))
    for h in hearers:
        if h["directed"] or h["mentioned"]:
            emit("heard_speech", {
                "listener_id": h["id"], "speaker_id": speaker["id"],
                "speaker_name": speaker.get("name") or speaker["id"], "utterance": text,
            })
    return record


def express(c, world, speech):
    """Say something aloud that is not meant to start a conversation."""
    text = (speech.get("utterance") or "").strip()
    if not text or (c.get("activity") or {}).get("type") == "sleep":
        return None
    tick = world.get("tick", 0)
    act = (speech.get("speech_act") or "remark").lower()
    volume = speech.get("volume") or default_volume(act)
    target_id = speech.get("target")
    c["current_speech"] = {
        "utterance": text,
        "speech_act": act,
        "topic": speech.get("topic", ""),
        "target": target_id,
        "volume": volume,
        "medium": "in_person",
        "expression": True,
        "expires_at_tick": tick + SPEECH_BUBBLE_TICKS,
    }
    c.setdefault("speech_log", []).append({"tick": tick, "utterance": text, "target": target_id, "type": act})
    c["speech_log"] = c["speech_log"][-20:]
    return broadcast(c, world, text, speech_act=act, volume=volume, target_id=target_id,
                     intent=speech.get("intent"))
