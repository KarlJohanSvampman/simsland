"""
systems/addictions.py

Generalized usage-tracking/cooldown/craving system covering food, alcohol,
coffee, energy drinks, cigarettes, painkillers, cocaine, amphetamines,
ketamine, cannabis, tea, candy, and soda (definitions.json's
addiction_templates registry, decision #10 of the nutrition/energy/weight/
addiction/intoxication overhaul).

c["addictions"] = {addiction_key: {"usages": int,
                                    "last_used_sim_time": float|None,
                                    "next_decay_sim_time": float|None}}

All elapsed-time math uses world["sim_time"] (real seconds, the calendar's
own clock -- see sim_loop.py::advance_calendar), not raw tick counts, per
this round's time-convention choice (systems/body.py's own docstring).
"""

import random

SECONDS_PER_HOUR = 3600.0


def _ensure_entry(c, key):
    addictions = c.setdefault("addictions", {})
    entry = addictions.get(key)
    if entry is None:
        entry = {"usages": 0, "last_used_sim_time": None, "next_decay_sim_time": None}
        addictions[key] = entry
    return entry


def record_usage(c, key, world):
    """Called from the unified consumption pipeline (body.py::
    on_consume_complete) for item-driven vices, from the drug-consumption
    activity branch, and from nutrition.py's daily excess-nutrition check
    (key="food")."""
    tmpl = world.get("definitions", {}).get("addiction_templates", {}).get(key)
    if not tmpl:
        return
    entry = _ensure_entry(c, key)
    entry["usages"] = entry.get("usages", 0) + 1
    sim_time = world.get("sim_time", 0.0)
    entry["last_used_sim_time"] = sim_time
    # Any fresh use resets the decay clock -- decay only resumes once
    # cooldown_hours has passed since the *most recent* use.
    entry["next_decay_sim_time"] = sim_time + tmpl.get("cooldown_hours", 24) * SECONDS_PER_HOUR


def craving(c, key, world=None):
    """0-1 craving score, used to bias LLM intention/action selection
    (decision #10) -- min(1.0, usages / (threshold * 2))."""
    tmpl = (world or {}).get("definitions", {}).get("addiction_templates", {}).get(key) if world else None
    threshold = tmpl.get("threshold", 5) if tmpl else 5
    usages = c.get("addictions", {}).get(key, {}).get("usages", 0)
    return min(1.0, usages / (threshold * 2)) if threshold else 0.0


def _roll_hazards(c, world, key, tmpl):
    hazard_registry = world.get("definitions", {}).get("health_hazard_templates", {})
    from systems.health import BODY_PARTS, _blank_body_part, _functional_status_for, _hazard_locality
    hs = c.setdefault("health_state", {})
    for hazard_key, prob in tmpl.get("hazards", {}).items():
        if hazard_key not in hazard_registry or random.random() >= prob:
            continue
        locality = _hazard_locality(hazard_registry[hazard_key])
        instance = {
            "tick_applied": world.get("tick", 0), "last_ticked": world.get("tick", 0),
            "treated": False, "hazard_template": hazard_key,
            "expires_tick": None, "current_stage": None,
        }
        if locality in BODY_PARTS:
            bp = hs.setdefault("body_parts", {}).setdefault(locality, _blank_body_part())
            bp["hazards"][hazard_key] = instance
            if not bp.get("severity_level"):
                bp["severity_level"] = "low"
            bp["functional_status"] = _functional_status_for(bp["severity_level"], bp["hazards"])
        else:
            hs.setdefault("systemic_hazards", {})[hazard_key] = instance


# Prolonged alcohol/hard-drug use is a real, likely cause of depression
# -- per explicit user direction. Deliberately NOT caffeine/nicotine/
# food-adjacent addictions (cigarettes, coffee, energy_drinks, candy,
# soda, tea) or painkillers -- scoped to what was actually asked for
# ("drug or alcohol"), not every substance this registry tracks.
_DEPRESSION_INDUCING_ADDICTIONS = {"alcohol", "cocaine", "amphetamines", "ketamine", "cannabis"}
DEPRESSION_INDUCTION_CHANCE = 0.03  # rolled each time usages cross threshold, same moment _roll_hazards() checks


def maybe_induce_depression_from_addiction(c, key, world):
    if key not in _DEPRESSION_INDUCING_ADDICTIONS:
        return
    mental_health = c.setdefault("mental_health", [])
    if "depression" in mental_health:
        return
    if random.random() < DEPRESSION_INDUCTION_CHANCE:
        mental_health.append("depression")


def tick_addictions(world):
    """Hourly cadence (sim_time-gated, not a raw tick divisor -- see module
    docstring). Called from a moderate CADENCE entry in sim_loop.py; no-ops
    internally until a full sim-hour has actually passed."""
    templates = world.get("definitions", {}).get("addiction_templates", {})
    if not templates:
        return
    sim_time = world.get("sim_time", 0.0)
    last_check = world.get("_addictions_last_check_sim_time")
    if last_check is not None and sim_time - last_check < SECONDS_PER_HOUR:
        return
    world["_addictions_last_check_sim_time"] = sim_time

    for c in world.get("characters", {}).values():
        addictions = c.get("addictions")
        if not addictions:
            continue
        for key, entry in addictions.items():
            tmpl = templates.get(key)
            if not tmpl or entry.get("usages", 0) <= 0:
                continue

            last_used = entry.get("last_used_sim_time")
            if last_used is None:
                continue
            hours_since_use = (sim_time - last_used) / SECONDS_PER_HOUR
            if hours_since_use < tmpl.get("cooldown_hours", 24):
                continue

            next_decay = entry.get("next_decay_sim_time")
            refresh_seconds = tmpl.get("refresh_rate_hours", 24) * SECONDS_PER_HOUR
            if next_decay is None:
                entry["next_decay_sim_time"] = sim_time + refresh_seconds
                continue
            while sim_time >= next_decay and entry["usages"] > 0:
                entry["usages"] -= 1
                next_decay += refresh_seconds
            entry["next_decay_sim_time"] = next_decay

            if entry.get("usages", 0) >= tmpl.get("threshold", 9999):
                _roll_hazards(c, world, key, tmpl)
                maybe_induce_depression_from_addiction(c, key, world)
