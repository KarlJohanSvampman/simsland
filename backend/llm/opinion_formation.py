import json

from llm.llm_client import call_llm_safe

# =========================================================
# GENERATE OPINION
# =========================================================
# Narrow-purpose LLM call, modeled directly on social_interpretation.py's
# generate_social_interpretation() -- own session, strict-JSON output,
# applied by the caller onto brain/opinions.py's per-topic store rather
# than mutated here. Given the character's own values (with plain-English
# explanations, since the LLM has no other way to know what "conform"
# means for a given category) plus the topic, produces a stance.
#
# Doubles as the argument-generation call for systems/action_router.py's
# make_argument (Round 5) -- pass argument_mode to get an extra prose
# argument_text + self-rated argument_strength in the same response,
# reframed as countering a prior argument or introducing a new point,
# instead of a fresh from-scratch opinion.

_VALUE_EXPLANATIONS = {
    "family":     "how much this person values family, and whether family life should be governed by shared rules/expectations (conform) or left to individual choice (non-conform)",
    "friends":    "how much this person values friendships, and whether friendship obligations should be governed by shared rules (conform) or left to individual choice (non-conform)",
    "work":       "how much this person values their work, and whether work/career norms should be governed by shared rules (conform) or left to individual choice (non-conform)",
    "leisure":    "how much this person values leisure/free time, and whether how people spend it should be governed by shared rules (conform) or left to individual choice (non-conform)",
    "education":  "how much this person values education, and whether it should be governed by shared rules/standards (conform) or left to individual choice (non-conform)",
    "romance":    "how much this person values romance, and whether romantic relationships should be governed by shared rules/expectations (conform) or left to individual choice (non-conform)",
    "children":   "how much this person values raising children, and whether child-rearing should be governed by shared rules (conform) or left to individual choice (non-conform)",
    "religion":   "how much this person values religion, and whether it's a matter that should be governed by shared rules/structure (conform) or a personal matter (non-conform)",
    "politics":   "how much this person values politics, and whether political life should be governed by shared rules/structure (conform) or left to individual choice (non-conform)",
    "community":  "how much this person values their wider community (neighborhood/municipality/region), and whether community life should be governed by shared rules (conform) or left to individual choice (non-conform)",
    "solidarity": "how much this person values solidarity with others, and who that solidarity extends to -- conform means it's selective, extended mainly to people like them, in exchange for order and shared standards; non-conform means it's universal, extended to the wider community without being selective about who deserves it",
    "traditions": "how much this person values traditions, and whether they should be upheld by shared expectation (conform) or are a personal matter (non-conform)",
}


def _format_values(values):
    lines = []
    for category, v in (values or {}).items():
        blurb = _VALUE_EXPLANATIONS.get(category, category)
        if category == "solidarity":
            # Solidarity's conform/non-conform axis is selective vs.
            # universal, not rules vs. freedom -- see _VALUE_EXPLANATIONS
            # above and context_builder.py's _build_values_context.
            stance = "selective, in-group solidarity" if v.get("conform") else "open, universal solidarity"
        else:
            stance = "favors shared rules/structure" if v.get("conform") else "favors individual freedom of choice"
        lines.append(f"- {category} (importance {v.get('importance', 0.5):.2f}, {stance}): {blurb}")
    return "\n".join(lines)


async def generate_opinion(c, topic, context, world, session):
    """
    context: {
        "reason":         str,             # why this topic surfaced
        "prior_stance":   dict | None,      # brain/opinions.py snapshot, if reconsidering
        "argument_mode":  "counter"|"new_point"|None,
        "prior_argument": str | None,       # text being countered, if argument_mode=="counter"
        "speaker_name":   str | None,       # who raised the topic/argument, if any
    }
    Returns a strict-JSON dict {"stance": -1..1, "confidence": 0..1,
    "reasoning": str, "relevant_values": [category,...]} -- plus
    "argument_text"/"argument_strength": 0..1 when argument_mode is set --
    or None on any failure (LLM unreachable, error response, unparseable
    JSON). Callers should treat None as "no opinion/argument formed this
    pass," not raise.
    """
    values_block = _format_values(c.get("values"))
    reason = context.get("reason", "")
    prior = context.get("prior_stance")
    argument_mode = context.get("argument_mode")
    prior_argument = context.get("prior_argument")
    speaker_name = context.get("speaker_name")

    prior_block = ""
    if prior:
        prior_block = (
            f"\nYour previous stance on this: {prior.get('stance')} "
            f"(confidence {prior.get('confidence')}), reasoning: {prior.get('reasoning')}\n"
        )

    argument_instruction = ""
    if argument_mode == "counter":
        argument_instruction = f"""
{speaker_name or "Someone"} just argued: "{prior_argument}"
COUNTER this specific argument -- explain why it doesn't change your mind, from your own values.
Also include "argument_text" (your spoken counter-argument, 1-2 sentences) and
"argument_strength" (0-1, how persuasive you think your own counter is).
"""
    elif argument_mode == "new_point":
        argument_instruction = f"""
You are in a discussion about this topic with {speaker_name or "someone"}.
Introduce a NEW supporting point for your own stance (not a repeat of your prior reasoning).
Also include "argument_text" (your spoken argument, 1-2 sentences) and
"argument_strength" (0-1, how persuasive you think your own argument is).
"""

    extra_schema_fields = (
        ',\n    "argument_text": "...",\n    "argument_strength": 0.5'
        if argument_mode else ""
    )

    prompt = f"""
You are simulating a person's PERSONAL OPINION on a topic, grounded in
their own values -- not objective truth, not what's "correct," just what
THIS person, given who they are, would actually think.

Person: {c.get("name")}
Personality traits: {c.get("traits", [])}

Their personal values (category: importance 0-1, conform/non-conform stance):
{values_block}

Topic/question: "{topic}"
Context: {reason}
{prior_block}{argument_instruction}

Form (or revise) their opinion. Ground the stance and reasoning in the
values listed above -- cite which ones are actually relevant to this
specific topic, not all of them.

Return STRICT JSON only.

Schema:
{{
    "stance": 0,
    "confidence": 0.5,
    "reasoning": "...",
    "relevant_values": ["..."]{extra_schema_fields}
}}
"""

    messages = [
        {"role": "system", "content": "Return STRICT JSON only."},
        {"role": "user", "content": prompt},
    ]

    result = await call_llm_safe(messages, session=session)

    if isinstance(result, dict) and result.get("error"):
        return None

    text = result.get("text", "") if isinstance(result, dict) else result

    try:
        data = json.loads(text)
    except Exception:
        return None

    if "stance" not in data:
        return None
    return data
