"""
llm/scripted_conversation.py

Generates the WHOLE back-and-forth for a remote shared_event (a phone
call or SMS exchange between two characters who aren't co-located) as
ONE real LLM call -- mirrors llm/shared_event_narration.py's shape (one
call, strict JSON, real deterministic fallback), just producing an
ordered list of turns instead of a single summary.

Playback timing (systems/scripted_conversations.py) is a separate
concern -- this module only decides WHAT gets said, grounded in the
same already-decided tier/severity/subcategory systems/events.py rolls
before this ever runs, plus real grievance/goodwill history so the
dialogue reflects actual standing between the two, not a vacuum.
"""

import json
import random

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND

_TIER_GUIDANCE = {
    "neutral":    "A perfectly ordinary, forgettable exchange -- nothing notable happened either way.",
    "pleasant":   "A genuinely nice moment -- friendly, warm, or otherwise good-natured.",
    "unpleasant": "An unpleasant, mildly tense exchange -- not a real argument, just an uncomfortable moment.",
    "argument":   "A real argument -- a back-and-forth dispute over something specific.",
    "conflict":   "A real, serious conflict -- sharp, heated, and hard to walk away from cleanly.",
}

_MIN_TURNS, _MAX_TURNS = 4, 8


def _grievance_goodwill_line(a, b, world):
    from systems.grievances import get_grievance_score
    from systems.goodwill import get_goodwill_score
    grievance = get_grievance_score(a, b["id"]) + get_grievance_score(b, a["id"])
    goodwill = get_goodwill_score(a, b["id"]) + get_goodwill_score(b, a["id"])
    if grievance > 15:
        return "\nThere's real, unresolved tension between them from past disagreements."
    if goodwill > 15:
        return "\nThey genuinely get along well and have a warm history."
    return ""


def _fallback_script(a_name, b_name, tier, medium):
    """A short, real, generic exchange matching the tier -- never blank.
    2-3 turns, alternating speakers."""
    opener = f"Hey, {b_name}." if medium == "text" else f"Hey, it's {a_name}."
    if tier == "pleasant":
        lines = [(a_name, opener), (b_name, "Hey! Good to hear from you."),
                  (a_name, "Just wanted to catch up.")]
    elif tier in ("unpleasant",):
        lines = [(a_name, opener), (b_name, "Oh. Hi."),
                  (a_name, "This won't take long.")]
    elif tier in ("argument", "conflict"):
        lines = [(a_name, opener), (b_name, "What do you want?"),
                  (a_name, "We need to talk about this."),
                  (b_name, "Fine. Go ahead.")]
    else:
        lines = [(a_name, opener), (b_name, "Hey, what's up?"),
                  (a_name, "Not much, just checking in.")]
    return [{"speaker": name, "line": line} for name, line in lines]


def _to_speaker_ids(script_by_name, a, b):
    """Resolve each turn's 'speaker' (a real name) back to a real
    character id, defaulting to alternating a/b if the LLM's name
    doesn't match either participant cleanly."""
    name_to_id = {a["name"]: a["id"], b["name"]: b["id"]}
    out = []
    last_speaker = None
    for i, turn in enumerate(script_by_name):
        speaker_name = turn.get("speaker", "")
        speaker_id = name_to_id.get(speaker_name)
        if not speaker_id:
            speaker_id = b["id"] if last_speaker == a["id"] else a["id"]
        out.append({"speaker_id": speaker_id, "line": turn.get("line", "").strip() or "..."})
        last_speaker = speaker_id
    return out


async def _generate(world, a, b, tier, severity, medium, subcategory):
    session = world.setdefault("_scripted_conversation_llm_sessions", {}).setdefault(
        f"{a['id']}_{b['id']}_{world.get('tick', 0)}", {"history": []}
    )
    guidance = _TIER_GUIDANCE.get(tier, _TIER_GUIDANCE["neutral"])
    severity_line = f"\nSeverity: {severity} -- reflect this intensity honestly." if severity else ""
    history_line = _grievance_goodwill_line(a, b, world)
    medium_line = (
        "This is a PHONE CALL -- lines should sound spoken, natural back-and-forth."
        if medium == "call" else
        "This is a TEXT MESSAGE exchange -- lines should read like real texts (short, informal)."
    )
    n_turns = random.randint(_MIN_TURNS, _MAX_TURNS)

    prompt = f"""
Writing a real {medium} conversation between {a['name']} and {b['name']} in a
life-simulation game.

What kind of moment this is has ALREADY been decided -- do not invent a
different tone: {guidance}{severity_line}{history_line}

{medium_line}

Write exactly {n_turns} lines, alternating speakers naturally (not
necessarily perfectly alternating -- someone can send two texts in a
row if that's realistic), starting with {a['name']} reaching out to
{b['name']}.

Respond with STRICT JSON only:
{{"lines": [{{"speaker": <"{a['name']}" or "{b['name']}">, "line": <what they say>}}, ...]}}
"""
    messages = [
        {"role": "system", "content": "You write a real, specific back-and-forth exchange between two characters in a life-simulation game, matching a tone that's already been decided for you. Return STRICT JSON only."},
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
        lines = parsed.get("lines")
        if not isinstance(lines, list) or not lines:
            return None
        return lines
    except Exception:
        return None


def generate_conversation_script(a, b, tier, world, severity=None, medium="call", subcategory=None):
    """Returns a real, ordered list of {"speaker_id", "line"} turns
    (4-8 entries). Deterministic fallback (2-3 turns) on LLM failure --
    never blank."""
    result = run_llm_call(
        _generate(world, a, b, tier, severity, medium, subcategory),
        priority=PRIORITY_BACKGROUND,
    )
    if not result:
        result = _fallback_script(a["name"], b["name"], tier, medium)
    return _to_speaker_ids(result, a, b)
