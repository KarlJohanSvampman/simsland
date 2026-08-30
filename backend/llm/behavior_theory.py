"""
llm/behavior_theory.py

Generates a theory for why a character exhibits a newly-noticed
behavior pattern (systems/behavior_patterns.py) -- modeled on
llm/story_condensation.py's shape (own prompt, own session key,
deterministic fallback). Classified optimistic (normal: work, gym,
errands) or pessimistic (suspicious: crime, an affair) -- a pessimistic
result feeds systems/worries.py's real suspicion tracking, generated
once when the pattern is first created, never re-rolled on repeat
sightings.
"""

import json

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call


async def _generate(c, other, pattern, world):
    session = world.setdefault(
        "_behavior_theory_sessions", {}
    ).setdefault(pattern["id"], {"history": []})

    lo, hi = pattern["hour_range"]
    prompt = f"""
{c.get('name', 'Someone')} has noticed {other.get('name', 'someone')} doing
"{pattern['activity']}" repeatedly, usually around {lo}:00-{hi}:00.

Come up with a plausible theory for why they do this. It can be
completely mundane (work, gym, errands, a hobby) or something more
suspicious (an affair, criminal activity, hiding something) -- pick
whichever feels most fitting given the behavior itself, not always the
dramatic option.

Respond with STRICT JSON only: {{"text": <one-sentence theory>, "valence": "optimistic" or "pessimistic"}}
"""
    messages = [
        {"role": "system", "content": "You invent plausible in-character theories about why someone in a life-simulation game exhibits a behavior pattern. Return STRICT JSON only."},
        {"role": "user", "content": prompt},
    ]
    result = await call_llm_safe(messages, session=session, char_id=c.get("id"))
    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    if parsed.get("valence") not in ("optimistic", "pessimistic"):
        parsed["valence"] = "optimistic"
    return parsed


def generate_theory(c, other, pattern, world):
    """Sync entry point -- bridges the async LLM call the same way
    systems/choice.py::choose() already does via run_llm_call()."""
    return run_llm_call(_generate(c, other, pattern, world))
