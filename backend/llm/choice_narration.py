from llm.llm_client import call_llm_safe

# =========================================================
# GENERATE CHOICE
# =========================================================
# Narrow-purpose LLM call, modeled on offgrid_narration.py's
# generate_offgrid_narration() -- own bespoke prompt, own session key, no
# dependency on brain/llm_brain.py's full decision-schema machinery.
# Unlike that call (which produces prose), this one asks for a single
# bare option id, since the caller (systems/choice.py::choose()) needs a
# reliably parseable answer, not narration.


async def generate_choice(c, world, choice_type, options, occasion):
    """
    Returns the raw LLM response string (expected to be a bare option
    id), or None on any failure (LLM unreachable, error response, empty
    output) -- systems/choice.py falls back to a random pick in that case.
    """
    session = c.setdefault("choice_llm_sessions", {}).setdefault(choice_type, {"history": []})

    options_block = "\n".join(
        f"- id: {o['id']} | {o.get('label', o['id'])}"
        + (f" | tags: {', '.join(o.get('tags', []))}" if o.get("tags") else "")
        for o in options
    )

    occasion_block = f"\nOccasion / reason for this choice: {occasion}\n" if occasion else ""

    prompt = f"""
Character: {c.get("name", "Someone")}
Traits: {c.get("traits", [])}

Choosing a {choice_type} from the following options:
{options_block}
{occasion_block}
Pick exactly ONE option id from the list above that best fits this
character and occasion. Respond with ONLY the id, nothing else -- no
punctuation, no explanation.
"""

    messages = [
        {
            "role": "system",
            "content": (
                f"You are choosing a {choice_type} on behalf of a character. "
                "Respond with only the chosen option's id -- no other text."
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
