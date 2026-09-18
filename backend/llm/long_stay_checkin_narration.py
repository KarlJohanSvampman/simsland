import json

from llm.llm_client import call_llm_safe


# Narrow-purpose LLM call, modeled directly on offgrid_narration.py::
# generate_offgrid_narration()'s shape -- own bespoke prompt, own session
# key, plain prose output. Triggered MID-stay (systems/offgrid.py::
# tick_long_stay_checkins) rather than on return, for any character
# currently off-grid on a long/uncapped-duration reason (jail, cps_care,
# temporary_separation, held_pending_trial, hospital, ...).

_REASON_FLAVOR = {
    "jail":                 "serving time in jail",
    "held_pending_trial":   "being held in custody awaiting trial",
    "cps_care":             "in the care of social services",
    "temporary_separation": "staying away from home after a falling-out",
    "hospital":             "recovering in the hospital",
    "hospital_treatment":   "undergoing hospital treatment",
    "surgery":              "recovering from surgery",
}


async def generate_checkin_summary(c, world, reason):
    """Returns a short prose "what's happened since" blurb, or None on
    any failure -- caller falls back to a deterministic template."""
    session = c.setdefault(
        "long_stay_checkin_sessions", {}
    ).setdefault(
        reason, {"history": []}
    )

    flavor = _REASON_FLAVOR.get(reason, "away from home for an extended stretch")
    traits = c.get("traits", [])

    prompt = f"""
Character: {c.get("name", "Someone")}
Traits: {traits}
Currently: {flavor}

Write a short (1-2 sentence) plain-prose "what's been happening" check-in
update, in third person, past/present tense as fits. Nothing dramatic --
this is a routine periodic update on how they're getting on, not a
resolution of their situation. Prose only -- no JSON, no preamble, no
quotation marks around the whole thing.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "Write a short plain-prose periodic check-in update for "
                "someone away for an extended stretch. Prose only."
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
