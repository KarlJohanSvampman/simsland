"""
systems/mental_health_effects.py

Makes a diagnosed condition in c["mental_health"] (systems/
mental_health_gen.py assigns these at generation; systems/addictions.py
can also induce depression at runtime, see maybe_induce_depression_
from_addiction()) actually DO something. Confirmed via research: the
mental_health_templates registry's own authored need_penalties/mood_lock
fields are never read anywhere in this codebase -- a diagnosis has sat
completely inert. This gives depression specifically (what was asked
about) real, direct symptoms rather than wiring the generic
need_penalties pipeline, which doesn't exist for this registry and
would need its own separate research/design pass to build safely:
worse hygiene, a fixed per-character over/under-eating lean, more sleep,
and reduced interest in leaving the house.

Ongoing therapy/medication (c["mental_health_treatment"], set by
systems/withdrawal_concern.py's successful pushes) halves all of these
and gives a slow chance of the condition actually resolving.
"""

import random

HYGIENE_DECAY_EXTRA_PER_DAY = 4.0     # on top of whatever body.py's own decay already applies
SLEEP_DEBT_REDUCTION_PER_DAY = 8.0    # oversleeping pays down sleep debt faster than normal
EATING_BIAS_HUNGER_SHIFT = 12.0       # per day, toward over- or under-eating
HOME_BIAS_MULTIPLIER = 0.55           # multiplies an existing "roll to go do something" chance

TREATMENT_SEVERITY_MULTIPLIER = 0.5
WEEKLY_RECOVERY_CHANCE_MEDICATED = 0.04
WEEKLY_RECOVERY_CHANCE_THERAPY_ONLY = 0.015


def has_condition(c, condition_id):
    return condition_id in (c.get("mental_health") or [])


def _depression_profile(c):
    """Assigned once, the first time depression's effects are ticked --
    which way THIS character's depression leans (over- vs under-eating),
    consistent from then on rather than random noise every day, matching
    "possibly either" as a per-person lean, not a coin flip every tick."""
    profile = c.get("_depression_profile")
    if profile is None:
        profile = {"eating": random.choice(["over", "under"])}
        c["_depression_profile"] = profile
    return profile


def _treatment_state(c):
    return (c.get("mental_health_treatment") or {}).get("depression", {})


def tick_depression_effects(c, world):
    """Called once per real calendar day (see sim_loop.py). No-ops
    entirely for a character without the diagnosis."""
    if not has_condition(c, "depression"):
        return

    treatment = _treatment_state(c)
    in_treatment = bool(treatment.get("in_therapy") or treatment.get("on_medication"))
    mult = TREATMENT_SEVERITY_MULTIPLIER if in_treatment else 1.0

    body = c.setdefault("body", {})

    # Worse hygiene -- self-care neglect, on top of body.py's own decay.
    body["hygiene"] = max(0, body.get("hygiene", 100) - HYGIENE_DECAY_EXTRA_PER_DAY * mult)

    # Sleeping a lot -- extra sleep_debt paydown beyond a normal night's
    # sleep (body.py::on_sleep_complete already handles that separately).
    body["sleep_debt"] = max(0, body.get("sleep_debt", 0) - SLEEP_DEBT_REDUCTION_PER_DAY * mult)

    # Eating too much or too little -- a consistent per-character lean.
    # body.py convention: hunger 0=full, 100=starving.
    profile = _depression_profile(c)
    shift = EATING_BIAS_HUNGER_SHIFT * mult
    if profile["eating"] == "under":
        body["hunger"] = min(100, body.get("hunger", 50) + shift)
    else:
        body["hunger"] = max(0, body.get("hunger", 50) - shift)

    # Loss of interest -- a real, readable flag other systems could check
    # later (e.g. hobby-engagement code); not wired further this round.
    c["_depression_low_interest"] = True

    # Slow chance of real recovery once actually being treated -- checked
    # weekly, not daily (matches this codebase's own weekly-reset
    # precedent, e.g. sim_loop.py's _is_monday_midnight-gated checks).
    cal = world.get("calendar", {})
    if cal.get("weekday") == "Monday" and cal.get("hour") == 0:
        recovered = False
        if treatment.get("on_medication") and random.random() < WEEKLY_RECOVERY_CHANCE_MEDICATED:
            recovered = True
        elif treatment.get("in_therapy") and random.random() < WEEKLY_RECOVERY_CHANCE_THERAPY_ONLY:
            recovered = True
        if recovered:
            c["mental_health"].remove("depression")
            c.pop("_depression_profile", None)


def home_leaving_multiplier(c):
    """Multiplies an existing "roll to go do something" chance elsewhere
    (systems/offgrid.py) -- 1.0 (no change) unless depressed, in which
    case reduced, not zeroed (still sometimes goes out). Partially
    recovers once in therapy/medicated."""
    if not has_condition(c, "depression"):
        return 1.0
    treatment = _treatment_state(c)
    if treatment.get("in_therapy") or treatment.get("on_medication"):
        return (HOME_BIAS_MULTIPLIER + 1.0) / 2
    return HOME_BIAS_MULTIPLIER
