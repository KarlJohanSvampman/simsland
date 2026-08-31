"""
llm/diary_narration.py

End-of-day diary entries, written in the character's own words from
their REAL stored memories of the day -- modeled directly on
llm/story_condensation.py's shape (own bespoke prompt, own session key,
plain-text out). Doubles as an informal verification tool for the
memory system: a diary entry with no real content behind it is a real
signal something upstream isn't storing memories correctly.
"""

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call


async def _generate_diary_text(c, world, day_memories):
    session = world.setdefault("_diary_sessions", {}).setdefault(c["id"], {"history": []})

    memory_lines = "\n".join(f"- {m['text']}" for m in day_memories[:15]) or "- Nothing much happened today."

    style_id = c.get("speech_style")
    style_line = ""
    if style_id:
        defs = world.get("definitions", {})
        style = defs.get("speech_style_registry", {}).get(style_id)
        if style:
            style_line = f"\nWrite in this distinctive voice: {style['description']}\n"

    prompt = f"""
Write a short first-person diary entry (3-6 sentences) for {c.get('name', 'this character')},
summarizing their day based on what actually happened to them today.
Write as THEM, in their own voice -- personal, reflective, not a news report.
{style_line}
Today's real events:
{memory_lines}

Respond with ONLY the diary entry text, no date header, no quotes.
"""
    messages = [
        {"role": "system", "content": "You write first-person diary entries for characters in a life-simulation game, grounded strictly in the real events given -- never invent events that aren't listed."},
        {"role": "user", "content": prompt},
    ]

    result = await call_llm_safe(messages, session=session, char_id=c.get("id"))
    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    if not isinstance(text, str) or not text.strip():
        return None
    return text.strip().strip('"')


def generate_diary_entry(c, world, day_memories):
    """Sync entry point -- bridges the async LLM call via run_llm_call(),
    same mechanism as story_condensation.py/choice.py. Falls back to a
    deterministic, still-grounded-in-real-memories summary on LLM
    failure rather than a blank/generic entry."""
    text = run_llm_call(_generate_diary_text(c, world, day_memories))
    if text:
        return text
    return _fallback_entry(c, day_memories)


def _fallback_entry(c, day_memories):
    if not day_memories:
        return "Nothing much happened today. Just an ordinary day."
    top = sorted(day_memories, key=lambda m: -m.get("importance", 0))[:3]
    lines = "; ".join(m["text"].rstrip(".") for m in top)
    return f"Today: {lines}."
