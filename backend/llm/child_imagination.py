"""
llm/child_imagination.py

What a small child makes up when they don't understand something grown-ups
are doing and nobody's explained it. One sentence, in the child's own voice,
built from the things a child that age actually knows (toys, bedtime, treats,
monsters, who got in trouble) -- never an adult reason. Same shape as
llm/behavior_theory.py: narrow strict-JSON call, deterministic fallback.

Pure function of its arguments: it runs on a systems/bg_llm worker thread and
must not touch the world.
"""

import json

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND

_SYSTEM = (
    "You write what a young child imagines when they don't understand something the grown-ups "
    "around them are doing. Always the child's own simple voice and the child's own world. "
    "Return STRICT JSON only."
)

# When the model is unreachable: a few honest-to-childhood guesses by kind of scene.
FALLBACKS = {
    "tense": [
        "Maybe somebody ate the last cookie and now everybody's mad.",
        "I think they're playing a grown-up game where somebody has to lose.",
        "Maybe one of them did something bad and has to say sorry.",
    ],
    "emotional": [
        "Maybe somebody lost something special.",
        "I think they're sad because it's a sad day.",
        "Maybe they miss someone.",
    ],
}


async def _imagine(name, age, question, tone):
    mood = "angry with each other" if tone == "tense" else "very upset"
    prompt = f"""
{name}, a {age}-year-old child, saw some grown-ups being {mood}, and wonders: "{question}"
Nobody has explained it.

Write ONE short sentence, in {name}'s own voice, with the vivid made-up explanation a child that
age would come up with, using things a child knows (toys, treats, bedtime, monsters, kings and
queens, who got in trouble). It should make sense to a child, not be a real adult reason.

Respond with STRICT JSON only: {{"text": <one sentence>}}
"""
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": prompt},
    ]
    result = await call_llm_safe(messages, session={"history": []}, char_id=None)
    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        out = json.loads(text).get("text")
    except Exception:
        return None
    return out.strip()[:200] if isinstance(out, str) and out.strip() else None


def imagine_explanation(name, age, question, tone):
    """Blocking; call from a bg_llm worker. Returns a sentence, or None."""
    result = run_llm_call(_imagine(name, age, question, tone), priority=PRIORITY_BACKGROUND)
    return result if isinstance(result, str) else None
