"""
systems/offense_rationalization.py

Real, offender-specific rationalization generated at the moment an
assault/domestic_disturbance incident is created (emergency.py::
report_assault_incident) -- not invented after the fact when someone
finally asks. Grounds a real excuse in something already on the
character (a stressful job, a recent grievance they felt was unfair, a
volatile trait) rather than a generic denial, plus a real "resolve"
score that later determines whether they admit or insist the victim is
lying under real pressure (see systems/law.py's disclosure/confrontation
handling).

Also stamps real guilt/paranoia -- a character has to actually "know"
he did something wrong for that to show up in his own LLM context, not
just an invisible flag nothing surfaces.
"""

import random

from brain.memory import store_memory

_RESOLVE_UP_TRAITS = {"stubborn", "prideful", "aggressive", "controlling", "narcissistic", "defensive"}
_RESOLVE_DOWN_TRAITS = {"anxious", "honest", "guilt_prone", "insecure", "sensitive", "remorseful"}

_GUILT_PARANOIA_INCIDENT_BUMP = 45.0
_GUILT_PARANOIA_DECAY = 0.98
_GUILT_STRESS_BUMP = 15.0


def _find_grounding(offender, world):
    """A real, specific 'reason it felt justified' rooted in something
    already on the character -- job stress, a recent grievance they felt
    was unfair, or (fallback) a volatile trait. Never fabricated from
    nothing."""
    if offender.get("job") and offender.get("stress", 0) > 60:
        title = offender["job"].get("title") if isinstance(offender.get("job"), dict) else None
        return f"the pressure from work{f' as a {title}' if title else ''} had him on edge"

    grievances = offender.get("grievances", [])
    if grievances:
        top = max(grievances, key=lambda g: g.get("weight", 0))
        return f"he still felt wronged over {top.get('event_type', 'something that happened before').replace('_', ' ')}"

    traits = set(offender.get("traits", []) + offender.get("personality_traits", []))
    volatile = traits & {"aggressive", "impulsive", "short_tempered", "hot_headed", "volatile"}
    if volatile:
        return f"he just snapped -- {next(iter(volatile)).replace('_', ' ')} got the better of him"

    return "he felt provoked, even if no one else saw it that way"


def _compute_resolve(offender):
    traits = set(offender.get("traits", []) + offender.get("personality_traits", []))
    resolve = 0.5
    resolve += 0.15 * len(traits & _RESOLVE_UP_TRAITS)
    resolve -= 0.15 * len(traits & _RESOLVE_DOWN_TRAITS)
    return max(0.05, min(0.95, resolve))


def generate_offense_rationalization(offender, world, incident):
    """Called at incident-creation time. Stores the real, grounded excuse
    + resolve score on the offender, a real shame-tagged memory, and
    bumps a real, decaying guilt/paranoia accumulator."""
    grounding = _find_grounding(offender, world)
    excuse_text = f"It wasn't really my fault -- {grounding}."

    offender["_offense_rationalization"] = {
        "incident_id": incident["id"],
        "excuse_text": excuse_text,
        "grounding":   grounding,
        "resolve":     _compute_resolve(offender),
    }

    store_memory(
        offender,
        f"I know what I did was wrong. I hurt {offender.get('_last_victim_name', 'someone')} and I can't take it back.",
        importance=0.9, tags=["shame", "guilt", "assault"], kind="memory",
        tick=world.get("tick", 0),
    )

    offender["_guilt_paranoia"] = min(100.0, offender.get("_guilt_paranoia", 0.0) + _GUILT_PARANOIA_INCIDENT_BUMP)
    offender["stress"] = min(100.0, offender.get("stress", 0.0) + _GUILT_STRESS_BUMP)


def decay_guilt_paranoia(c):
    """Daily-cadence decay, same shape as this session's other 0-100
    accumulator fields (e.g. criminal_standing). Decays faster once the
    underlying incident is actually resolved one way or another."""
    level = c.get("_guilt_paranoia", 0.0)
    if level <= 0:
        return
    resolved = c.get("_offense_rationalization") is None
    rate = 0.90 if resolved else _GUILT_PARANOIA_DECAY
    c["_guilt_paranoia"] = max(0.0, level * rate)


def get_guilt_paranoia_context(c):
    """Narrated into the offender's own LLM context -- real, not
    invisible. A separate reader (brain/context_builder.py) is
    responsible for actually threading this line in."""
    level = c.get("_guilt_paranoia", 0.0)
    if level < 15:
        return None
    if level < 50:
        return "Something's been weighing on you -- you know what you did, and it hasn't sat right."
    return "You can't stop thinking about what you did. You're worried someone will find out, and it's eating at you."
