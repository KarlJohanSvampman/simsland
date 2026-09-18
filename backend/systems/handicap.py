"""
systems/handicap.py

Per the user's explicit ask: two real 0-100 properties per character --
c["physical_handicap"] and c["mental_handicap"] -- built up incrementally
as real conditions get diagnosed, not recomputed from a static lookup
each time. Each disease template's own `severity` field (already real,
authored content, roughly 1-10) derives a random handicap-contribution
range at the moment a condition is actually diagnosed -- rolled ONCE per
diagnosis, then added on top of whatever the character already has.
Deriving the range from severity (rather than hand-authoring a
handicap_range on all ~46 mental/physical health templates) gets the
same real, content-driven result -- a template's authored severity is
what decides how much it can hand out -- without a large, error-prone
one-off edit across every template.

Meant to genuinely affect two things: how demanding others' expectations
of this character are (systems/expectations.py), and how OTHER
characters approach them socially (narrated into context so the LLM's
own judgment can act on it, matching this codebase's established
signal-then-narrate pattern for social nuance -- see e.g.
attraction.py::get_attraction_context()).
"""

import random

MAX_HANDICAP = 100


def _handicap_range_for_severity(severity):
    severity = severity or 0
    return (severity * 2, severity * 5)


def apply_condition_handicap(c, tmpl, target_stat):
    """target_stat: "physical_handicap" | "mental_handicap". Called once,
    right when a NEW condition is actually diagnosed (see
    mental_health_gen.py::_assign_one_condition() and any later runtime
    diagnosis) -- rolls this template's own contribution and adds it to
    whatever the character already has; never overwrites, so it
    genuinely accumulates as conditions stack up."""
    low, high = _handicap_range_for_severity(tmpl.get("severity"))
    if high <= 0:
        return
    contribution = random.randint(low, high)
    current = c.get(target_stat, 0)
    c[target_stat] = min(MAX_HANDICAP, current + contribution)


def total_handicap(c):
    return min(MAX_HANDICAP, c.get("physical_handicap", 0) + c.get("mental_handicap", 0))


def handicap_label(handicap):
    """Plain-language band, for narration -- see get_handicap_context()."""
    if handicap >= 60:
        return "severely impaired"
    if handicap >= 30:
        return "noticeably impaired"
    if handicap >= 10:
        return "mildly impaired"
    return None


def get_handicap_context(other):
    """Narrated into an OBSERVER's own context about a nearby OTHER
    person -- per the user's ask that a handicap should affect how
    others approach someone. A real, computed signal handed to the LLM
    as plain-language fact; the LLM's own judgment decides how to
    actually act on it (more patience, offering help, simpler requests,
    lower expectations, ...), not a hardcoded behavior rule."""
    label = handicap_label(total_handicap(other))
    if not label:
        return None
    name = other.get("name", "they")
    return f"{name} is {label} -- worth being patient and considerate with them."
