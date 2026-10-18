"""
llm/self_assessment.py

A character who has just caught themselves repeating the same activity over and
over reflects on why -- in their own voice, from the facts of their situation.
The thought is stored with the failure (so it doubles as a debugging trace of what
the character believes is going on) and fed back into their next decision.

Same shape as llm/child_imagination.py: narrow strict-JSON call, deterministic
fallback, pure function of its arguments (runs on a systems/bg_llm worker thread
and must not touch the world).
"""

import json

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND

_SYSTEM = (
    "You are a person in a life simulation pausing to look honestly at your own behaviour. "
    "Answer in first person, plainly, like a private thought. Return STRICT JSON only."
)


def fallback_thought(activity, count, intention_reason):
    what = activity.replace("_", " ")
    why = f" (I told myself: {intention_reason})" if intention_reason else ""
    return (f"I keep doing {what} again and again{why} and it isn't getting me anywhere. "
            f"I should stop and work out what I actually need.")


async def _assess(name, age, activity, count, minutes, intention_reason, situation):
    what = activity.replace("_", " ")
    prompt = f"""
You are {name}, age {age}. You just noticed you have started "{what}" {count} times in a row over the
last {minutes} minutes -- each time it ends and you immediately go and do it again.
{f'What you told yourself you were doing it for: {intention_reason}' if intention_reason else ''}

What is going on with you right now:
{situation}

In one or two sentences, in your own voice: why do you think you keep doing this, and what will you do
about it instead? Be honest -- if something more important is being neglected, say so.

Respond with STRICT JSON only: {{"thought": <one or two sentences>, "instead": <what you will do, a few words>}}
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
        data = json.loads(text)
    except Exception:
        return None
    thought = data.get("thought")
    if not isinstance(thought, str) or not thought.strip():
        return None
    instead = data.get("instead")
    return {"thought": thought.strip()[:400],
            "instead": instead.strip()[:120] if isinstance(instead, str) else None}


def assess(name, age, activity, count, minutes, intention_reason, situation):
    """Blocking; call from a bg_llm worker. {"thought", "instead"} or None."""
    result = run_llm_call(_assess(name, age, activity, count, minutes, intention_reason, situation),
                          priority=PRIORITY_BACKGROUND)
    return result if isinstance(result, dict) and result.get("thought") else None
