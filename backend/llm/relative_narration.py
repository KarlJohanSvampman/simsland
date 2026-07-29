from llm.llm_client import call_llm_safe


# =========================================================
# GENERATE RELATIVE BIO NARRATION
# =========================================================
# Narrow-purpose LLM call, modeled on offgrid_narration.py's
# generate_offgrid_narration() -- own bespoke prompt, no dependency on
# brain/llm_brain.py's decision-schema machinery. The procedurally-derived
# traits/hobbies (relative_gen.derive_relative()) are already decided by
# the time this is called -- the LLM writes bio prose consistent with those
# picks, it does not invent its own trait set.

async def generate_relative_narration(
    source_char,
    relation_type,
    derived_traits,
    derived_hobbies,
    derived_age,
    derived_sex,
):
    """
    Returns a prose bio string, or None on any failure -- caller falls
    back to relative_gen._fallback_bio().
    """
    source_name = source_char.get("name", "Someone")
    source_bio  = source_char.get("bio", "")
    source_traits = source_char.get("traits", [])
    source_hobbies = source_char.get("hobbies", [])
    source_age = source_char.get("age", "unknown")
    source_sex = source_char.get("sex", "unknown")

    bio_block = f"\n{source_name}'s bio: {source_bio}\n" if source_bio else ""

    prompt = f"""
{source_name} ({source_age}, {source_sex}) has traits {source_traits} and
hobbies {source_hobbies}.{bio_block}
You are writing a short biography for {source_name}'s {relation_type},
a {derived_age}-year-old {derived_sex}.

This relative's traits: {derived_traits}
This relative's hobbies: {derived_hobbies}

Write a short (2-4 sentence) plain-prose biography for this relative, in
third person. It should feel like a real relative of {source_name} --
plausible shared history, family resemblance in temperament where it fits
the traits above, and its own distinct life. Prose only -- no JSON, no
preamble, no quotation marks around the whole thing.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Write a short plain-prose character biography. "
                "Prose only -- no JSON, no preamble."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    result = await call_llm_safe(messages, session={"history": []}, char_id=None)

    if isinstance(result, dict) and result.get("error"):
        return None
    if not isinstance(result, str) or not result.strip():
        return None
    return result.strip()
