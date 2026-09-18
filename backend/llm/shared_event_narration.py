"""
llm/shared_event_narration.py

Real, semantic narration for a shared_event (systems/events.py) -- who
was there, where, what actually happened/was discussed, and any
remarkable detail. Modeled on llm/work_shift_narration.py's shape (one
LLM call, strict JSON, real deterministic fallback).

Tone is no longer left to the LLM's own free invention -- systems/
events.py rolls a real encounter tier (neutral/pleasant/unpleasant/
argument/conflict) and, for a negative tier, a real severity (Minor/
Low/Medium/High/Intense) BEFORE this ever runs, grounded in the pair's
actual grievance history. This module's only job is narrating THAT
already-decided outcome believably, not deciding what kind of moment it
was.

Returns {"text": str, "detail": str, "topic": str, "category": str}:
  - "text" is a short (1 sentence) version for a quick memory/summary.
  - "detail" is a fuller (2-4 sentence) version for a real retelling.
  - "topic" is a short phrase for what was actually discussed/happened.
  - "category" is a real systems/stories.py STORY_CATEGORIES value,
    picked by the LLM from the actual content.
"""

import json

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND

_STORY_CATEGORIES = (
    "shock", "humor", "informative", "gossip",
    "ridicule", "suspicious_activity", "unusual_behavior", "musing",
)

_TIER_GUIDANCE = {
    "neutral":    "A perfectly ordinary, forgettable exchange -- nothing notable happened either way.",
    "pleasant":   "A genuinely nice moment -- friendly, warm, or otherwise good-natured.",
    "unpleasant": "An unpleasant, mildly tense exchange -- not a real argument, just an uncomfortable moment.",
    "argument":   "A real argument -- a back-and-forth dispute over something specific.",
    "conflict":   "A real, serious conflict -- sharp, heated, and hard to walk away from cleanly.",
}


_NEGATIVE_TIER_PHRASE = {
    "unpleasant": "an unpleasant exchange",
    "argument":   "an argument",
    "conflict":   "a real conflict",
}

# Per-subcategory narration guidance -- refines WHAT the encounter was
# about within its already-decided tone, per systems/events.py's real,
# rolled subcategory (never invented freely by the LLM).
_SUBCATEGORY_GUIDANCE = {
    "gossip_thirdparty": "One of them shares a piece of gossip about {about} -- something that has nothing to do with either of them personally.",
    "praise":            "{source} praises or congratulates {focus} for something real and specific.",
    "invitation":        "{source} invites {focus} to a social or professional gathering, event, or dinner.",
    "sympathy":          "{focus} is looking for sympathy, comfort, or just someone to confide in about something difficult -- {source} is the one they're confiding in.",
    "negative_gossip":   "{source} shares negative gossip about {about} -- {gossip_about_self_or_contact}.",
}


def _subcategory_names(subcategory, world):
    if not subcategory:
        return {}
    characters = world.get("characters", {})
    out = {}
    for key in ("focus_id", "source_id", "about_id"):
        cid = subcategory.get(key)
        if cid and cid in characters:
            out[key.replace("_id", "")] = characters[cid]["name"]
    if "about" not in out and subcategory.get("about_id") is None:
        out["about"] = "someone unrelated to either of them"
    focus_id, about_id = subcategory.get("focus_id"), subcategory.get("about_id")
    out["gossip_about_self_or_contact"] = (
        "about the person themselves" if about_id == focus_id
        else "about someone close to them (family, a colleague, a close friend)"
    )
    return out


def _subcategory_guidance_line(subcategory, world):
    if not subcategory:
        return ""
    sub = subcategory.get("subcategory")
    template = _SUBCATEGORY_GUIDANCE.get(sub)
    if not template:
        return ""
    names = _subcategory_names(subcategory, world)
    try:
        return "\n" + template.format(**names)
    except KeyError:
        return ""


def _fallback_by_subcategory(subcategory, world, participant_names):
    sub = subcategory.get("subcategory") if subcategory else None
    names = _subcategory_names(subcategory, world) if subcategory else {}
    if sub == "gossip_thirdparty":
        return f"{names.get('about', 'someone unrelated to either of them')} came up, and they traded a bit of gossip about it."
    if sub == "praise":
        return f"{names.get('source')} praised {names.get('focus')} for something they'd done."
    if sub == "invitation":
        return f"{names.get('source')} invited {names.get('focus')} to an upcoming get-together."
    if sub == "sympathy":
        return f"{names.get('focus')} confided in {names.get('source')} about something difficult, looking for a little sympathy."
    if sub == "negative_gossip":
        about = names.get("about")
        subject = "themselves" if subcategory.get("about_id") == subcategory.get("focus_id") else "someone close to them"
        return f"{names.get('source')} spread some unflattering gossip about {about} ({subject}), and {names.get('focus')} caught wind of it."
    return None


def _fallback(tier, severity, participant_names, subcategory=None, world=None):
    names = " and ".join(participant_names) if participant_names else "some people"
    sub_text = _fallback_by_subcategory(subcategory, world, participant_names) if world is not None else None
    if sub_text:
        return {"text": sub_text, "detail": sub_text, "topic": (subcategory or {}).get("subcategory", tier), "category": None}
    if tier == "neutral":
        text = f"{names} crossed paths and exchanged a few ordinary words."
    elif tier == "pleasant":
        text = f"{names} had a genuinely pleasant exchange."
    else:
        phrase = _NEGATIVE_TIER_PHRASE.get(tier, tier)
        text = f"{names} had {phrase}"
        if severity:
            text += f", of {severity} severity,"
        text += " with each other."
    return {"text": text, "detail": text, "topic": tier, "category": None}


async def _generate(world, event, participant_names, location_name):
    session = world.setdefault("_shared_event_llm_sessions", {}).setdefault(event["id"], {"history": []})

    tier = event.get("type")
    severity = event.get("severity")
    subcategory = event.get("subcategory")
    guidance = _TIER_GUIDANCE.get(tier, _TIER_GUIDANCE["neutral"])
    severity_line = f"\nSeverity: {severity} -- reflect this intensity honestly, not stronger or weaker." if severity else ""
    subcategory_line = _subcategory_guidance_line(subcategory, world)

    prompt = f"""
Narrating a life-simulation game. {', '.join(participant_names) or 'Two people'} just had a
real, specific moment{f' at {location_name}' if location_name else ''}.

What kind of moment this was has ALREADY been decided -- do not invent a
different tone: {guidance}{severity_line}{subcategory_line}

Invent a plausible, specific, concrete account consistent with that
tone/severity/subject -- what was actually said or done, and what it was about.

Respond with STRICT JSON only:
{{"text": <1 sentence, for a quick memory>,
"detail": <2-4 sentences, the fuller account>,
"topic": <short phrase, what it was actually about>,
"category": <one of {list(_STORY_CATEGORIES)}, whichever best fits>}}
"""
    messages = [
        {"role": "system", "content": "You narrate a specific, concrete moment between two characters in a life-simulation game, matching a tone that's already been decided for you. Return STRICT JSON only."},
        {"role": "user", "content": prompt},
    ]
    result = await call_llm_safe(messages, session=session, char_id=None)
    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    if parsed.get("category") not in _STORY_CATEGORIES:
        parsed["category"] = None
    return parsed


def generate_shared_event_narration(world, event, participant_names, location_name=None):
    result = run_llm_call(
        _generate(world, event, participant_names, location_name),
        priority=PRIORITY_BACKGROUND,
    )
    if not result:
        return _fallback(event.get("type"), event.get("severity"), participant_names,
                          subcategory=event.get("subcategory"), world=world)
    return result
