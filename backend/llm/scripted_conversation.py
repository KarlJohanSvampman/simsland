"""
llm/scripted_conversation.py

Writes the WHOLE back-and-forth for a remote shared_event (a phone call or
SMS exchange between two characters who aren't co-located) as ONE model call,
ahead of time, so the exchange can be played back like a script however slow
the model is -- mirrors llm/shared_event_narration.py's shape, just producing
an ordered list of turns instead of a single summary.

The call is made OFF the tick thread: systems/scripted_conversations.py
builds a plain-data request (build_script_request), hands write_script to
systems/bg_llm, and starts the call/text when the answer is taken. (It used
to run on the tick thread, which abandons a model call after 3 seconds, so
on a slow model every remote conversation fell back to the same four stock
lines.)

Playback timing (systems/scripted_conversations.py) is a separate concern --
this module only decides WHAT gets said, grounded in the already-decided
tier/severity/subcategory systems/events.py rolls before this ever runs, plus
real grievance/goodwill history and what the exchange is about, so the dialogue
reflects the actual standing between the two, not a vacuum.
"""

import random
import re

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND

_TIER_GUIDANCE = {
    "neutral":    "A perfectly ordinary, forgettable exchange -- nothing notable happened either way.",
    "pleasant":   "A genuinely nice moment -- friendly, warm, or otherwise good-natured.",
    "unpleasant": "An unpleasant, mildly tense exchange -- not a real argument, just an uncomfortable moment.",
    "argument":   "A real argument -- a back-and-forth dispute over something specific.",
    "conflict":   "A real, serious conflict -- sharp, heated, and hard to walk away from cleanly.",
}

# How long the whole exchange runs: a call talks longer than a text, a row longer than a pleasantry.
_TURNS = {
    "call": {"neutral": (8, 12), "pleasant": (8, 14), "unpleasant": (8, 12), "argument": (10, 16), "conflict": (12, 18)},
    "text": {"neutral": (6, 9),  "pleasant": (6, 10), "unpleasant": (6, 9),  "argument": (8, 12),  "conflict": (8, 14)},
}
MIN_SCRIPT_LINES = 4          # fewer parsed lines than this and the answer is not used


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


def _who_is_it_about(world, a, b, subcategory):
    """One line on what the exchange is about, from the subcategory systems/events.py already rolled."""
    if not subcategory:
        return ""
    names = {c["id"]: c["name"] for c in (a, b)}
    chars = world.get("characters", {})

    def nm(cid):
        return names.get(cid) or (chars.get(cid) or {}).get("name") or "someone they both know"

    sub = subcategory.get("subcategory")
    if sub == "gossip_thirdparty":
        return f"\nIt is mostly idle gossip about {nm(subcategory.get('about_id'))}."
    if sub == "praise":
        return f"\n{nm(subcategory.get('source_id'))} is praising {nm(subcategory.get('focus_id'))} for something specific."
    if sub == "invitation":
        return f"\n{nm(subcategory.get('source_id'))} is inviting {nm(subcategory.get('focus_id'))} to do something together."
    if sub == "sympathy":
        return f"\n{nm(subcategory.get('focus_id'))} is having a bad time and {nm(subcategory.get('source_id'))} is comforting them."
    if sub == "negative_gossip":
        return f"\n{nm(subcategory.get('source_id'))} is saying unkind things about {nm(subcategory.get('about_id'))}."
    return ""


def _standing(a, b):
    """What they are to each other, in a phrase, when the relationship record has one."""
    rel = (a.get("relationships") or {}).get(b["id"]) or {}
    bits = []
    if rel.get("designation"):
        bits.append(str(rel["designation"]).replace("_", " "))
    labels = [str(l).replace("_", " ") for l in (rel.get("labels") or [])]
    if labels:
        bits.append(", ".join(labels))
    return f"\nThey are: {'; '.join(bits)}." if bits else ""


def build_script_request(world, a, b, tier, severity=None, medium="call", subcategory=None):
    """Plain data (JSON-safe, no world references) for write_script -- it runs on a worker and must not touch the world."""
    lo, hi = _TURNS.get(medium, _TURNS["call"]).get(tier, (8, 12))
    return {
        "a_id": a["id"], "a_name": a["name"], "b_id": b["id"], "b_name": b["name"],
        "medium": medium, "tier": tier, "severity": severity,
        "guidance": _TIER_GUIDANCE.get(tier, _TIER_GUIDANCE["neutral"]),
        "context": (_who_is_it_about(world, a, b, subcategory) + _standing(a, b) + _grievance_goodwill_line(a, b, world)).strip(),
        "n_turns": random.randint(lo, hi),
    }


def _prompt(req):
    a, b, medium = req["a_name"], req["b_name"], req["medium"]
    severity_line = f"\nSeverity: {req['severity']} -- reflect this intensity honestly." if req.get("severity") else ""
    medium_line = (
        "This is a PHONE CALL -- lines should sound spoken, natural back-and-forth."
        if medium == "call" else
        "This is a TEXT MESSAGE exchange -- lines should read like real texts (short, informal)."
    )
    context = f"\n{req['context']}" if req.get("context") else ""
    return f"""Writing a real {medium} conversation between {a} and {b} in a life-simulation game.

What kind of moment this is has ALREADY been decided -- do not invent a different tone: {req['guidance']}{severity_line}{context}

{medium_line}

Write the WHOLE conversation, about {req['n_turns']} lines, from {a} reaching out to {b} until it naturally ends (a goodbye, someone hanging up, or it trailing off).
Keep it specific: the people actually say what the matter is, they do not just announce that they need to talk. Someone can speak twice in a row if that is realistic.

Reply with one line per turn in exactly this form, and nothing else:
{a}: what they say
{b}: what they say"""


async def _generate_text(req):
    messages = [
        {"role": "system", "content": "You write a real, specific back-and-forth exchange between two characters in a life-simulation game, matching a tone that has already been decided for you. Reply only with the lines, one per turn, as 'Name: line'."},
        {"role": "user", "content": _prompt(req)},
    ]
    result = await call_llm_safe(messages, char_id=None, max_tokens=60 * req["n_turns"] + 150)
    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    return text if isinstance(text, str) and text.strip() else None


def parse_script(req, text):
    """'Name: line' lines -> [{"speaker": name, "line": str}]. A reply cut off mid-way still gives the lines before the cut; a JSON
    {"lines": [...]} reply (what the model did before this format) is read too. Empty list when nothing usable."""
    if not isinstance(text, str):
        return []
    names = {req["a_name"].lower(): req["a_name"], req["b_name"].lower(): req["b_name"]}
    out = []
    for raw in text.strip().split("\n"):
        m = re.match(r"^[\s>*_#\-\d.)]*([^:\n]{1,40}?)[\s*_]*:\s*(.+)$", raw.strip())
        if not m:
            continue
        name = names.get(m.group(1).strip().strip("*_\"'").lower())
        line = m.group(2).strip().strip("*_").strip().strip('"').strip()
        if name and line:
            out.append({"speaker": name, "line": line})
    if len(out) >= MIN_SCRIPT_LINES:
        return out
    try:
        import json
        data = json.loads(text)
        lines = data.get("lines") if isinstance(data, dict) else None
        if isinstance(lines, list):
            return [{"speaker": t.get("speaker", ""), "line": t.get("line", "")} for t in lines if isinstance(t, dict)]
    except Exception:
        pass
    return out


def write_script(req):
    """Blocking; runs on a bg_llm worker. The parsed script as [{"speaker", "line"}] -- None when the model gave nothing usable."""
    from llm.llm_gate import gate_failed
    text = run_llm_call(_generate_text(req), priority=PRIORITY_BACKGROUND)
    if not text or gate_failed(text):
        return None
    lines = parse_script(req, text)
    return lines if len(lines) >= MIN_SCRIPT_LINES else None


def script_from_lines(req, lines):
    """Resolve each turn's speaker name back to a character id (defaulting to alternating if a name does not match) and tidy the lines.
    A malformed turn is read as an empty line from whoever's turn it is, not a crash."""
    if not isinstance(lines, list):
        return []
    name_to_id = {req["a_name"]: req["a_id"], req["b_name"]: req["b_id"]}
    out, last = [], None
    for turn in lines:
        if not isinstance(turn, dict):
            turn = {}
        speaker_id = name_to_id.get(turn.get("speaker", ""))
        if not speaker_id:
            speaker_id = req["b_id"] if last == req["a_id"] else req["a_id"]
        out.append({"speaker_id": speaker_id, "line": (turn.get("line") or "").strip() or "..."})
        last = speaker_id
    return out


def generate_conversation_script(a, b, tier, world, severity=None, medium="call", subcategory=None):
    """Blocking, for callers off the tick thread: the full script as [{"speaker_id", "line"}]. Falls back to a short stock exchange if
    the model gives nothing -- the normal path (systems/scripted_conversations.py) does not use the fallback."""
    req = build_script_request(world, a, b, tier, severity, medium, subcategory)
    lines = write_script(req)
    if not lines:
        lines = _fallback_script(a["name"], b["name"], tier, medium)
    return script_from_lines(req, lines)
