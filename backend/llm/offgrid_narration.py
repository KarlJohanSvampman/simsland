import json

from llm.llm_client import call_llm_safe


# =========================================================
# GENERATE OFF-GRID NARRATION
# =========================================================
# Narrow-purpose LLM call, modeled on social_interpretation.py's
# generate_social_interpretation() -- own bespoke prompt, own session key,
# no dependency on brain/llm_brain.py's decision-schema machinery. Output
# here is plain prose (not JSON), since this call narrates a completed
# off-grid trip rather than deciding an action.

_NORMALCY_GUIDANCE = {
    "normal":  "Nothing noteworthy happened. Keep it brief and mundane.",
    "notable": "One small, plausible, mildly interesting thing happened -- "
               "not dramatic, just worth a sentence.",
    "rare":    "Something genuinely unusual happened this trip -- make it "
               "the center of the account.",
}


async def generate_offgrid_narration(
    c,
    world,
    category,
    details,
    normalcy,
    history,
    enforced_cover_story=None,
):
    """
    Returns a short prose summary string, or None on any failure (LLM
    unreachable, error response, empty output) -- callers fall back to the
    existing procedural _story() generator in that case.
    """
    session = c.setdefault(
        "offgrid_llm_sessions", {}
    ).setdefault(
        category, {"history": []}
    )

    traits = c.get("traits", [])
    guidance = _NORMALCY_GUIDANCE.get(normalcy, _NORMALCY_GUIDANCE["normal"])

    history_lines = "\n".join(f"- {h['summary']}" for h in history) or "(none yet)"

    cover_story_block = ""
    if enforced_cover_story:
        cover_story_block = (
            "\nThe character is concealing something about this trip. The "
            "account you produce MUST match this cover story exactly and "
            "must not reveal or contradict it:\n"
            f"\"{enforced_cover_story}\"\n"
        )

    prompt = f"""
Character: {c.get("name", "Someone")}
Traits: {traits}
Trip category: {category}
Normalcy: {normalcy} -- {guidance}

Trip details:
{json.dumps(details, ensure_ascii=False)}

Recent similar trips (for tone/continuity -- do not repeat these):
{history_lines}
{cover_story_block}
Write a short (1-3 sentence) plain-prose summary of what happened on this
trip, in third person, past tense. Prose only -- no JSON, no preamble, no
quotation marks around the whole thing.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Write a short plain-prose summary of an off-grid trip. "
                "Prose only -- no JSON, no preamble."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    result = await call_llm_safe(messages, session=session, char_id=c.get("id"))

    if isinstance(result, dict) and result.get("error"):
        return None
    if not isinstance(result, str) or not result.strip():
        return None
    return result.strip()
