"""
llm/story_condensation.py

Condenses an evicted systems/stories.py entry down to roughly one
sentence for permanent long-term storage (brain/memory.py::store_memory,
kind="story_archive") -- modeled directly on llm/item_content.py's
shape (own bespoke prompt, own session key, plain-text out this time
since the desired output IS the text, not structured fields).
"""

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call


async def _generate_condensed_text(c, story, world):
    session = world.setdefault(
        "_story_condensation_sessions", {}
    ).setdefault(story["id"], {"history": []})

    prompt = f"""
Condense this story down to a single short sentence (max ~20 words) --
the version someone would actually say out loud if reminded of it
years later. Keep it punchy and specific, not vague.

Category: {story.get("category")}
Original: {story.get("summary", "")}

Respond with ONLY the condensed sentence, no quotes, no extra text.
"""
    messages = [
        {"role": "system", "content": "You condense stories into single punchy sentences for a life-simulation game's long-term memory."},
        {"role": "user", "content": prompt},
    ]

    result = await call_llm_safe(messages, session=session, char_id=c.get("id") if c else None)
    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    if not isinstance(text, str) or not text.strip():
        return None
    return text.strip().strip('"')


def condense_story(c, story, world):
    """Sync entry point -- bridges the async LLM call the same way
    systems/choice.py::choose() already does via run_llm_call(),
    rather than a new mechanism."""
    return run_llm_call(_generate_condensed_text(c, story, world))
