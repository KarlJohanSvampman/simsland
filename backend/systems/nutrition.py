"""
systems/nutrition.py

Daily nutrition-day settlement: weight change, BMI band -> physical trait +
weight-extreme disease sync, weight-band health hazard rolls, and next-day
toilet-visit load. Called once per character from body.py::update_body_needs
when it detects a real calendar-midnight rollover (world["calendar"]["day"]
changing), NOT on any approximate tick-count cadence -- see body.py's own
comment for why (this round's tick/real-time convention, decision #0).

c["body"]["nutrients_today"] is a fraction of "a day's recommended
nutrition" (1.0 = exactly on target), accumulated by body.py::
on_consume_complete every time something is eaten/drunk.
"""

import math
import random

WEIGHT_STEP_KG   = 0.1
WEIGHT_MIN_KG    = 20.0

# ── BMI band matrix (decision #7) ───────────────────────────────────────────
# Ordered (upper_bmi_exclusive, trait_key) -- last entry catches everything
# above. "normal" has no trait of its own (the healthy middle of the curve).
_BMI_BANDS = [
    (16.0,  "thin"),
    (18.5,  "skinny"),
    (20.0,  "slim"),
    (25.0,  None),       # normal
    (28.0,  "chubby"),
    (32.0,  "fat"),
    (None,  "obese"),    # >= 32
]

# All trait keys this system ever assigns/removes -- used to clear whichever
# one no longer applies before adding the new one (body_composition.py's
# _sync_dynamic_trait pattern, generalized to a multi-way band swap).
_ALL_BAND_TRAITS = ["thin", "skinny", "slim", "chubby", "fat", "obese"]

_THIN_DISEASE  = "malnutrition"
_OBESE_DISEASE = "obesity_metabolic_disorder"
_ALL_BAND_DISEASES = [_THIN_DISEASE, _OBESE_DISEASE]

# ── weight-band health hazards (decision #8) ────────────────────────────────
# Hardcoded per-tier modifier table, matching health.py's _TRAIT_IMMUNE_
# DELTAS precedent -- independent per-hazard rolls (not a mutually-exclusive
# weighted_pick), reusing existing health_hazard_templates keys.
_WEIGHT_BAND_HAZARDS = {
    "thin":   [("dehydration", 0.10), ("tiredness", 0.15), ("fainting", 0.05)],
    "skinny": [("tiredness", 0.08)],
    "slim":   [],
    "normal": [],
    "chubby": [],
    "fat":    [("short_breath", 0.08), ("tiredness", 0.08)],
    "obese":  [("short_breath", 0.15), ("tiredness", 0.15), ("fainting", 0.05)],
}


def compute_bmi(c):
    height_cm = c.get("body_features", {}).get("height_cm", 170)
    weight_kg = c.get("weight_kg", 70)
    height_m = max(0.5, height_cm / 100.0)
    return weight_kg / (height_m ** 2)


def get_weight_band(bmi):
    for upper, band in _BMI_BANDS:
        if upper is None or bmi < upper:
            return band or "normal"
    return "obese"


def _sync_weight_band_trait(c, band):
    traits = c.setdefault("physical_traits", [])
    for t in _ALL_BAND_TRAITS:
        if t != band and t in traits:
            traits.remove(t)
    if band in _ALL_BAND_TRAITS and band not in traits:
        traits.append(band)


def _sync_weight_band_disease(c, band):
    conditions = c.setdefault("physical_health", [])
    wanted = _THIN_DISEASE if band == "thin" else (_OBESE_DISEASE if band == "obese" else None)
    for cond in _ALL_BAND_DISEASES:
        if cond != wanted and cond in conditions:
            conditions.remove(cond)
            c.get("condition_state", {}).pop(cond, None)
    if wanted and wanted not in conditions:
        conditions.append(wanted)


_UNDERWEIGHT_BANDS = {"thin", "skinny"}


def _roll_weight_band_hazards(c, world, band):
    if band in _UNDERWEIGHT_BANDS:
        # Explicit user direction: hunger must never inflict a hazard.
        # thin/skinny are hunger's own bands (fat/obese bands are
        # overeating-driven, not hunger, and keep theirs below).
        return
    defs = world.get("definitions", {})
    hazard_registry = defs.get("health_hazard_templates", {})
    from systems.health import BODY_PARTS, _blank_body_part, _functional_status_for, _hazard_locality
    hs = c.setdefault("health_state", {})
    for hazard_key, prob in _WEIGHT_BAND_HAZARDS.get(band, []):
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


def settle_nutrition_day(c, world):
    """Called once, exactly at real calendar midnight, by body.py::
    update_body_needs. Settles yesterday's nutrients_today into weight
    change (decision #6), BMI-band trait/disease sync (decision #7/#9),
    weight-band hazard rolls (decision #8), and tomorrow's toilet-visit
    load (decision #8) -- then resets the running tally."""
    b = c.setdefault("body", {})
    nutrients = b.get("nutrients_today", 0.0)

    if nutrients > 1.0:
        excess = nutrients - 1.0
        c["weight_kg"] = c.get("weight_kg", 70) + WEIGHT_STEP_KG * (1 + excess)
        toilet_visits = 1 + math.floor(excess / 0.5)

        # Excess-nutrition day -> food-addiction bump (decision #10).
        try:
            from systems.addictions import record_usage
            record_usage(c, "food", world)
        except ImportError:
            pass
    else:
        deficit = 1.0 - nutrients
        c["weight_kg"] = max(WEIGHT_MIN_KG, c.get("weight_kg", 70) - WEIGHT_STEP_KG * (1 + deficit))
        toilet_visits = 1

    b["toilet_visits_needed_today"] = toilet_visits
    b["nutrients_today"] = 0.0

    bmi = compute_bmi(c)
    band = get_weight_band(bmi)
    _sync_weight_band_trait(c, band)
    _sync_weight_band_disease(c, band)
    _roll_weight_band_hazards(c, world, band)
