import json

from llm.llm_client import call_llm_safe


# Narrow-purpose LLM call, modeled on offgrid_narration.py's shape (own
# bespoke prompt, own session key, plain prose output) -- but resolved
# SYNCHRONOUSLY inside the route handler itself (see action_router.py::
# _route_examine), the same "no _scaffold(..., duration=N) wait at all"
# pattern _route_make_argument() already uses. examine used to be a flat
# 180-tick wait producing zero real content; this makes it resolve as
# fast as the LLM responds and actually teach the character something
# real, grounded in the target's own template facts.

async def generate_examine_description(c, entity_name, structured_facts, world):
    """Returns a short (1-2 sentence) plain-prose semantic description,
    or None on any failure -- caller falls back to a deterministic,
    fact-grounded template sentence in that case."""
    session = c.setdefault(
        "examine_llm_sessions", {}
    ).setdefault(
        entity_name, {"history": []}
    )

    facts_line = "; ".join(f"{k}: {v}" for k, v in structured_facts.items() if v not in (None, "", [])) \
        or "(no further details known)"

    prompt = f"""
Character: {c.get("name", "Someone")}
You are taking a closer look at: {entity_name}
Known facts about it: {facts_line}

Write a short (1-2 sentence) semantic description of this thing, in
first person as the character's own private observation -- what it is,
what it's good for, and anything worth noting (including whether it's
edible, if that's relevant). Ground it in the facts given; don't invent
details that contradict them. Prose only -- no JSON, no preamble, no
quotation marks around the whole thing.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Write a short, first-person, fact-grounded observation "
                "about something a character is examining. Prose only."
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


def _readable_name(entity_name):
    return str(entity_name).replace("_", " ").strip()


def fallback_examine_description(entity_name, structured_facts):
    """Deterministic, never-blank fallback -- built directly from
    whatever real facts are available, matching this codebase's
    universal no-blank-fallback rule."""
    category = structured_facts.get("category")
    description = structured_facts.get("description")
    edible = structured_facts.get("edible")
    name = _readable_name(entity_name)

    if category:
        article = "an" if category[:1].lower() in "aeiou" else "a"
        text = f"{name.capitalize()} -- {article} {category}."
    else:
        text = f"{name.capitalize()}."
    if description:
        text += f" {description}"
    if edible is True:
        text += " Looks edible."
    elif edible is False:
        text += " Not edible."
    return text
