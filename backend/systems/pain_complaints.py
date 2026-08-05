"""
systems/pain_complaints.py

Recurring, escalating spontaneous complaints about physical pain
(health_state["pain"], see systems/health.py). Bypasses the LLM turn-based
action system entirely -- fires directly through
systems/incidental_speech.py::fire_incidental(), the same non-blocking
speech-bubble pipeline used for departure announcements, plus a physical
reaction via systems/reactions.py for visible feedback. Canned text pools
per tier/age rather than LLM-generated, matching incidental_speech.py's
existing non-LLM pattern -- no added LLM load per character per cooldown
cycle.

Tier breakpoints mirror systems/health.py's own pain thresholds
(PAIN_CRAWL_THRESHOLD=60, PAIN_INCAPACITATED_THRESHOLD=80) loosely, but
are independently defined here since the complaint ladder starts earlier
(10) and has its own middle breakpoint (50) that health.py has no use for.
"""

import random

PAIN_COMPLAIN_MIN     = 10
PAIN_TIER_MODERATE     = 50
PAIN_TIER_SEVERE       = 80

# Cooldown shrinks as pain worsens -- complaints both escalate in content
# and recur more often, per the user's "reoccurring... escalate" ask.
_COOLDOWN_MILD     = 180
_COOLDOWN_MODERATE = 90
_COOLDOWN_SEVERE   = 45

_MILD_LINES = [
    "Ah, that hurts.",
    "Ow... that's really sore.",
    "Ugh, this pain won't quit.",
    "That stings more than it should.",
    "My body's really aching right now.",
]

_MILD_LINES_CHILD = [
    "Ow, that hurts.",
    "It hurts a little.",
    "Ow ow ow.",
]

_MODERATE_LINES = [
    "Damn it, this really hurts!",
    "Ah, hell, that's bad.",
    "Ow! This is really painful!",
    "Christ, that hurts.",
    "Ugh -- this pain is getting bad.",
]

_MODERATE_LINES_CHILD = [
    "*sobbing* It hurts, it hurts!",
    "*crying* Make it stop hurting!",
    "*whimpering* It hurts so much...",
]

_SEVERE_LINES = [
    "AAAH! IT HURTS SO MUCH!",
    "MAKE IT STOP, PLEASE!",
    "I CAN'T TAKE THIS PAIN!",
    "GOD, IT HURTS!",
    "SOMEBODY HELP, IT HURTS SO BAD!",
]

_SEVERE_LINES_CHILD = [
    "*screaming and sobbing* IT HURTS, IT HURTS!",
    "*wailing* MAKE IT STOP! IT HURTS SO BAD!",
    "*crying hysterically* I WANT IT TO STOP!",
]


def _tier_for(pain):
    if pain >= PAIN_TIER_SEVERE:
        return "severe"
    if pain >= PAIN_TIER_MODERATE:
        return "moderate"
    return "mild"


_TIER_COOLDOWN = {"mild": _COOLDOWN_MILD, "moderate": _COOLDOWN_MODERATE, "severe": _COOLDOWN_SEVERE}
_TIER_REACTION = {"mild": "wince", "moderate": "cry_out", "severe": "cry_out"}


def _pick_line(tier, is_child):
    pools = {
        "mild":     _MILD_LINES_CHILD if is_child else _MILD_LINES,
        "moderate": _MODERATE_LINES_CHILD if is_child else _MODERATE_LINES,
        "severe":   _SEVERE_LINES_CHILD if is_child else _SEVERE_LINES,
    }
    return random.choice(pools[tier])


def tick_pain_complaints(c, world):
    """Call once per character per tick from agent_loop.py, right after
    process_health() so it sees the tick's final pain value."""
    if not c.get("alive", True):
        return

    pain = c.get("health_state", {}).get("pain", 0.0)
    if pain < PAIN_COMPLAIN_MIN:
        return

    tick = world.get("tick", 0)
    tier = _tier_for(pain)
    cooldown = _TIER_COOLDOWN[tier]
    last = c.get("_pain_complaint_last", -999999)
    if tick - last < cooldown:
        return

    from systems.incidental_speech import fire_incidental
    from systems.reactions import push_reaction

    is_child = c.get("age_group") == "child"
    text = _pick_line(tier, is_child)
    fire_incidental(c, "pain_complaint", text, world)
    push_reaction(c, _TIER_REACTION[tier], tick)

    c["_pain_complaint_last"] = tick
