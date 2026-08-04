import json

from llm.llm_client import call_llm_safe


# =========================================================
# GENERATE BUSINESS SUPPORT RESPONSE
# =========================================================
# Narrow-purpose LLM call, modeled directly on offgrid_narration.py's
# generate_offgrid_narration() -- own bespoke prompt, no dependency on
# brain/llm_brain.py's decision-schema machinery. A business isn't a real
# character with a think() loop, so this stands in for "a support rep (or
# receptionist, for a service business) looked at the inquiry and replied" --
# plain prose, not JSON.

async def generate_business_response(business, business_key, inquiry, world, session):
    """
    inquiry: {"kind": "call"|"voicemail"|"email", "reason": str,
              "caller_name": str, "wants_appointment": bool}
    Returns a short prose reply string, or None on any failure (LLM
    unreachable, error response, empty output) -- callers should skip
    that inbox entry this pass and retry next time process_business_inboxes
    runs, rather than losing the inquiry.
    """
    name = business.get("name", business_key)
    kind = inquiry.get("kind", "call")
    reason = inquiry.get("reason") or "an unspecified reason"
    caller = inquiry.get("caller_name", "the caller")

    prompt = f"""
Business: {name}
Industry: {business.get("industry", "")}
Business type: {business.get("business_kind", "")}

A customer named {caller} tried to reach you by {kind} about: "{reason}"
{"They wanted to book an appointment." if inquiry.get("wants_appointment") else ""}

Write a short (1-2 sentence) plain-prose reply from the business, as if a
support rep or receptionist is calling/writing back. Be specific to the
stated reason -- a plausible explanation, next step, or solution, not a
generic acknowledgment. Prose only -- no JSON, no preamble, no quotation
marks around the whole thing.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Write a short plain-prose customer-support reply. "
                "Prose only -- no JSON, no preamble."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    result = await call_llm_safe(messages, session=session, char_id=business_key)

    if isinstance(result, dict) and result.get("error"):
        return None
    if not isinstance(result, str) or not result.strip():
        return None
    return result.strip()
