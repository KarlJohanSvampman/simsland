"""
llm/account_agreement.py

Do two different people's answers to the same question tell the child the
same thing? Narrow strict-JSON call, same shape as llm/behavior_theory.py.
Returns True (they agree), False (they conflict), or None (couldn't tell --
the caller treats that as "no new information", never as a conflict).

Pure function of its text arguments: it's run on a bg_llm worker thread and
must not touch the world.
"""

import json

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND

_SYSTEM = (
    "You judge whether two people's answers to a child's question tell the child the same "
    "thing. Judge the substance (the reason or reassurance given), not the wording. "
    "Return STRICT JSON only."
)


async def _judge(question, first_name, first_text, second_name, second_text):
    prompt = f"""
A child asked: "{question}"

{first_name} answered: "{first_text}"
{second_name} answered: "{second_text}"

Do the two answers say essentially the same thing to the child (same reason, or both
reassuring in the same way), or do they conflict (different reasons, or one contradicts or
dismisses the other)?

Respond with STRICT JSON only: {{"agree": true or false}}
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
        agree = json.loads(text).get("agree")
    except Exception:
        return None
    return agree if isinstance(agree, bool) else None


def accounts_agree(question, first_name, first_text, second_name, second_text):
    """Blocking; call from a bg_llm worker, not from a tick."""
    result = run_llm_call(
        _judge(question, first_name, first_text, second_name, second_text),
        priority=PRIORITY_BACKGROUND,
    )
    return result if isinstance(result, bool) else None
