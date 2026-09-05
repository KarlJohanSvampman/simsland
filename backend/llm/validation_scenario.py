import json

from llm.llm_client import call_llm_safe

# =========================================================
# GENERATE VALIDATION RESPONSE
# =========================================================
# Narrow-purpose LLM call, same shape as llm/opinion_formation.py and
# llm/secret_authoring.py. A character confiding in a trusted contact
# with a "seek_validation" need (systems/confiding.py) wants someone to
# put themselves in their shoes and judge whether they handled things
# right -- this generates that confidant's "what I would have done in
# your situation" take, plus whether they approve or disapprove overall.

_FALLBACK_APPROVE_TEXT = "Honestly? I think I'd have done the same thing in your shoes."
_FALLBACK_DISAPPROVE_TEXT = "I get it, but I think I'd have handled that differently."


async def generate_validation_response(confidant, confider, event_summary, world, session):
    """Returns {"approves": bool, "text": str}. Deterministic fallback
    (coin-flip approval with a generic but real line) on any LLM failure."""
    prompt = f"""
You are simulating {confidant.get("name")} listening to a friend/family
member, {confider.get("name")}, describe something that happened to them:

"{event_summary}"

{confidant.get("name")}'s own personality traits: {confidant.get("traits", [])}

React as {confidant.get("name")} genuinely would, given who they are.
Decide whether you'd have done the same thing in {confider.get("name")}'s
situation (approve) or think they could have handled it better
(disapprove) -- be honest to your own character, not just supportive by
default. Give ONE short spoken line, framed as "what I would have done in
your situation."

Return STRICT JSON only.

Schema:
{{
    "approves": true,
    "text": "..."
}}
"""
    messages = [
        {"role": "system", "content": "Return STRICT JSON only."},
        {"role": "user", "content": prompt},
    ]
    try:
        result = await call_llm_safe(messages, session=session)
        if isinstance(result, dict) and result.get("error"):
            raise ValueError("llm_error")
        text = result.get("text", "") if isinstance(result, dict) else result
        data = json.loads(text)
        approves = bool(data.get("approves", True))
        line = data.get("text") or (_FALLBACK_APPROVE_TEXT if approves else _FALLBACK_DISAPPROVE_TEXT)
        return {"approves": approves, "text": line}
    except Exception:
        import random
        approves = random.random() < 0.6
        return {"approves": approves, "text": _FALLBACK_APPROVE_TEXT if approves else _FALLBACK_DISAPPROVE_TEXT}
