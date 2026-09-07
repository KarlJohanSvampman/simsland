import json

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call

# =========================================================
# GENERATE CHAPTER PLAN
# =========================================================
# Narrow-purpose LLM call, same shape as llm/behavior_theory.py and
# llm/secret_authoring.py -- own session (keyed by chapter id, so a
# stalled chapter re-rolled later isn't contaminated by an unrelated
# chapter's conversation history), strict-JSON output, deterministic
# fallback on any failure.
#
# The LLM is never asked to invent character ids or names for suspects --
# it's handed a numbered candidate roster (household + the detective's
# own closest contacts) and picks indices from it, or leaves a lead
# untied to anyone real ("unknown" is a valid, common outcome for an
# early chapter). This keeps suspect/involved tracking mechanically
# trustworthy regardless of what prose the model produces.

_FALLBACK_OUTCOME = {
    "plan_summary": "Keeps an eye on things and asks around quietly.",
    "outcome": "no_progress",
    "answer_summary": None,
    "resolution_action": None,
    "new_clue": None,
    "new_suspect_indices": [],
    "cleared_suspect_indices": [],
    "next_question": None,
}


def _format_candidates(candidates):
    if not candidates:
        return "(nobody else relevant comes to mind)"
    return "\n".join(f"{i}. {c['name']}" for i, c in enumerate(candidates))


async def _generate(c, world, story, chapter, candidates, session):
    candidate_block = _format_candidates(candidates)
    clues = story.get("clues") or ["(none yet)"]
    suspects_named = [cand["name"] for cand in candidates if cand["id"] in story.get("suspect_ids", [])]
    involved_named = [cand["name"] for cand in candidates if cand["id"] in story.get("involved_ids", [])]

    prompt = f"""
You are simulating {c.get("name")}'s own detective work on a real, personal
mystery -- not omniscient, only what they actually know.

Their role in this: {story.get("role")}
Their real motive for looking into it: {story.get("goal")}
Overall problem (tags: {story.get("tags")}): {story.get("problem_statement")}

Current chapter's problem statement: {chapter.get("problem_statement")}
Current chapter's main question: {chapter.get("main_question")}

Known clues so far: {clues}
Confirmed involved so far: {involved_named or "none yet"}
Currently suspected (not confirmed): {suspects_named or "none yet"}

People {c.get("name")} could plausibly ask, watch, or suspect (pick by
number ONLY from this list -- if the real answer isn't one of these
people, leave it unnamed):
{candidate_block}

Decide what {c.get("name")} actually does about the main question this
chapter, grounded in who they are, and what it leads to. Be willing to
say the trail goes cold (outcome "no_progress") if that's honestly the
more likely result -- most amateur snooping doesn't crack the case in
one sitting.

Return STRICT JSON only.

Schema:
{{
    "plan_summary": "one or two sentences, what they actually try",
    "outcome": "answered" | "more_questions" | "no_progress",
    "answer_summary": "if answered: what they now believe is true, else null",
    "resolution_action": "if answered and something concrete should now happen (e.g. 'return it to them', 'tell a parent'), else null",
    "new_clue": "one new fact/lead this chapter surfaced, or null",
    "new_suspect_indices": [ints from the candidate list, or empty],
    "cleared_suspect_indices": [ints from the candidate list previously suspected who now seem innocent, or empty],
    "next_question": "if outcome is more_questions, the new question this raises, else null"
}}
"""
    messages = [
        {"role": "system", "content": "Return STRICT JSON only."},
        {"role": "user", "content": prompt},
    ]
    try:
        result = await call_llm_safe(messages, session=session, char_id=c.get("id"))
        if isinstance(result, dict) and result.get("error"):
            raise ValueError("llm_error")
        text = result.get("text", "") if isinstance(result, dict) else result
        data = json.loads(text)
        if data.get("outcome") not in ("answered", "more_questions", "no_progress"):
            data["outcome"] = "no_progress"
        return data
    except Exception:
        return dict(_FALLBACK_OUTCOME)


def generate_chapter_plan(c, world, story, chapter, candidates):
    """Sync entry point -- bridges the async LLM call the same way
    systems/secret_keeping.py::_ensure_cover_story does. candidates:
    [{"id":..., "name":...}, ...], real known characters only."""
    session = world.setdefault("_detective_plan_sessions", {}).setdefault(
        chapter.get("id", "unknown"), {"history": []}
    )
    try:
        result = run_llm_call(_generate(c, world, story, chapter, candidates, session))
    except Exception:
        result = None
    return result or dict(_FALLBACK_OUTCOME)
