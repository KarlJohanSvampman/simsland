import json

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND

# =========================================================
# GENERATE UNSETTLING LETTER
# =========================================================
# Narrow-purpose LLM call, same shape as llm/secret_authoring.py. The
# user's own flagship example for systems/detective_work.py: a letter
# addressed to a specific household member (often a kid) that reads as
# off -- not necessarily a threat or blackmail, more like it was written
# by someone troubled -- unsettling enough that the recipient identifies
# it as a real problem the moment they read it.

_FALLBACK_LETTERS = [
    "I know you don't remember me but I remember you. I see you sometimes. "
    "I hope you're doing okay. Please don't show this to anyone.",
    "You probably think everything is fine at your house. It isn't always "
    "what it looks like from outside. Just something to think about.",
    "I used to live near you. I think about that street a lot. Tell your "
    "family I said hello, even though they won't know who that is.",
]


async def _generate(c, world, session):
    prompt = f"""
Write a short, unsettling letter addressed to {c.get("name")}, age
{c.get("age")}. It should NOT be an outright threat or blackmail -- more
like it was written by someone troubled, lonely, obsessive, or not quite
right in the head. It should read as genuinely off in a way that would
make a real person uneasy, without being graphic or explicit. 3-5
sentences. No signature, or an ambiguous/unsettling one at most.

Return STRICT JSON only.

Schema:
{{
    "letter_text": "..."
}}
"""
    messages = [
        {"role": "system", "content": "Return STRICT JSON only."},
        {"role": "user", "content": prompt},
    ]
    try:
        result = await call_llm_safe(messages, session=session, char_id=c.get("id"))
        if isinstance(result, dict) and result.get("error"):
            raise ValueError("llm_error")
        text = result.get("text", "") if isinstance(result, dict) else result
        data = json.loads(text)
        letter = data.get("letter_text")
        if not letter or not isinstance(letter, str):
            raise ValueError("empty")
        return letter
    except Exception:
        import random
        return random.choice(_FALLBACK_LETTERS)


def generate_unsettling_letter(c, world):
    """Sync entry point -- bridges the async LLM call the same way
    systems/secret_keeping.py::_ensure_cover_story does."""
    session = world.setdefault("_unsettling_letter_sessions", {}).setdefault(c["id"], {"history": []})
    try:
        result = run_llm_call(_generate(c, world, session), priority=PRIORITY_BACKGROUND)
    except Exception:
        result = None
    # _generate() itself already falls back to a random _FALLBACK_LETTERS
    # entry on any internal failure -- but a preempted/cancelled call
    # bypasses that entirely (no exception is raised, so the `except
    # Exception` above never fires) and resolves here to run_llm_call's
    # own {"error": ...} dict instead, which would otherwise get mailed
    # out verbatim as the letter's content.
    if isinstance(result, dict) and "error" in result:
        result = None
    if not result:
        import random
        return random.choice(_FALLBACK_LETTERS)
    return result
