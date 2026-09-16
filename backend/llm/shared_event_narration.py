"""
llm/shared_event_narration.py

Real, semantic narration for a shared_event (systems/events.py) --
who was there, where, what actually happened/was discussed, and any
remarkable detail -- instead of the old flat templated one-liner
("Was involved in cafe_meet; outcome was accident."). Modeled directly
on llm/work_shift_narration.py's shape (one LLM call, strict JSON, real
deterministic fallback).

Returns {"text": str, "detail": str, "topic": str, "category": str}:
  - "text" is a short (1 sentence) version for a quick memory/summary.
  - "detail" is a fuller (2-4 sentence) version for a real retelling.
  - "topic" is a short phrase for what was actually discussed/happened.
  - "category" is a real systems/stories.py STORY_CATEGORIES value,
    picked by the LLM from the actual content -- not re-derived by
    keyword-matching flat template text after the fact (the confirmed
    root cause of "everything either becomes a story or doesn't
    depending on one magic word being present").
"""

import json

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND

_STORY_CATEGORIES = (
    "shock", "humor", "informative", "gossip",
    "ridicule", "suspicious_activity", "unusual_behavior", "musing",
)


def _fallback(event_type, participant_names):
    names = " and ".join(participant_names) if participant_names else "some people"
    text = f"{names} spent some time together during a {event_type.replace('_', ' ')}."
    return {
        "text": text,
        "detail": text,
        "topic": event_type.replace("_", " "),
        "category": None,
    }


async def _generate(world, event, participant_names, location_name):
    session = world.setdefault("_shared_event_llm_sessions", {}).setdefault(event["id"], {"history": []})

    prompt = f"""
Imagine you are narrating a life-simulation game. A "{event['type'].replace('_', ' ')}"
just happened between {', '.join(participant_names) or 'two people'}{f' at {location_name}' if location_name else ''}.

Freely invent a plausible, specific, fictional account of what actually
happened -- what was said, what it was about, how it went, and whether
anything remarkable came of it. Don't follow any predetermined outcome
or severity -- decide for yourself, the same way a narrator would, what
kind of moment this turned out to be (pleasant, tense, funny, dramatic,
forgettable, or anything else that fits).

Respond with STRICT JSON only:
{{"text": <1 sentence, for a quick memory>,
"detail": <2-4 sentences, the fuller account>,
"topic": <short phrase, what it was actually about>,
"category": <one of {list(_STORY_CATEGORIES)}, whichever best fits>}}
"""
    messages = [
        {"role": "system", "content": "You narrate a specific, concrete moment between two characters in a life-simulation game. Return STRICT JSON only."},
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
        return _fallback(event["type"], participant_names)
    return result
