import json

from llm.llm_client import call_llm_safe

# =========================================================
# GENERATE SECRET COVER
# =========================================================
# Narrow-purpose LLM call, modeled directly on llm/opinion_formation.py's
# generate_opinion() -- own session, strict-JSON output. Given a character
# and a secret (systems/secrets.py's shape, extended with subject_type/
# label by systems/secret_keeping.py), decides WHY they'd keep it from the
# people it's hidden from and what their PREFERRED LIE would be -- the one
# they'll keep telling, for consistency, rather than improvising a fresh
# story every time they're asked.
#
# What/whether to hide is decided deterministically in Python (existing
# excuses.py disapproval-detection, or an explicit affair/secret_crush
# relationship label) -- the LLM's only job here is the WHY and the LIE,
# matching how this codebase reserves LLM calls for narrative/text content
# and keeps decision logic in code.

_FALLBACK_REASONS = {
    "infidelity": "It would destroy the relationship if it came out.",
    "crime":      "It could mean real legal trouble if anyone found out.",
    "identity":   "It's not something they'd understand or accept.",
    "finance":    "It would just cause a fight about money.",
    "health":     "It's private, and they'd worry more than it's worth.",
    "past":       "It's embarrassing and better left in the past.",
    "relationship": "It would only cause unnecessary drama.",
    "other":      "It's just easier if this stays private.",
}

_FALLBACK_LIES = {
    "infidelity": "Says they were with a friend from work.",
    "crime":      "Claims they were somewhere else entirely.",
    "identity":   "Changes the subject or gives a vague non-answer.",
    "finance":    "Says it's handled, no need to worry about it.",
    "health":     "Says it's nothing, just tired.",
    "past":       "Waves it off as not worth talking about.",
    "relationship": "Says it's complicated and leaves it at that.",
    "other":      "Gives a vague, unmemorable answer.",
}


async def generate_secret_cover(c, world, secret, session):
    """secret: a systems/secrets.py-shaped dict, already carrying
    subject_type/label (see systems/secret_keeping.py::mark_secret).
    Returns {"reason": str, "preferred_lie": str}. Deterministic
    category-keyed fallback on any LLM failure -- never returns empty
    strings, since excuses.py depends on always having something to say."""
    category = secret.get("category", "other")

    prompt = f"""
You are simulating why a person keeps something private, and what they'd
consistently say if asked about it.

Person: {c.get("name")}
Personality traits: {c.get("traits", [])}
What they're hiding: {secret.get("content")}
Category: {category}
Hidden from: {len(secret.get("deception_targets", {}))} specific people

Come up with:
1. "reason" -- ONE short sentence, their own private reasoning for why they
   don't want this known (not moralizing, just their real motive).
2. "preferred_lie" -- ONE short sentence, the cover story they'd actually
   give if pressed about it. It should be plausible and specific enough to
   repeat consistently, not just "I'd rather not say."

Return STRICT JSON only.

Schema:
{{
    "reason": "...",
    "preferred_lie": "..."
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
        reason = data.get("reason") or _FALLBACK_REASONS.get(category, _FALLBACK_REASONS["other"])
        lie = data.get("preferred_lie") or _FALLBACK_LIES.get(category, _FALLBACK_LIES["other"])
        return {"reason": reason, "preferred_lie": lie}
    except Exception:
        return {
            "reason": _FALLBACK_REASONS.get(category, _FALLBACK_REASONS["other"]),
            "preferred_lie": _FALLBACK_LIES.get(category, _FALLBACK_LIES["other"]),
        }
