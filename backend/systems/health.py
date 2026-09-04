"""
health.py -- Comprehensive health simulation system for HoloSims
"""

import random

# world["tick"] advances by exactly 1 per nominal game-second (see
# sim_loop.py::advance_calendar()'s own comment, and core/
# tick_schedule.py's TICK_RATE_SECONDS) -- these were previously 1/24/168,
# assuming 1 tick = 1 "hour," a pre-existing bug that made every
# interval below (medication cadence, the daily immune/condition tick,
# the weekly checks) fire roughly 3600x too often. Corrected here.
TICKS_PER_HOUR = 3600
TICKS_PER_DAY  = TICKS_PER_HOUR * 24
TICKS_PER_WEEK = TICKS_PER_DAY * 7

MIN_HEART_ATTACK_SURVIVAL_MINUTES = 15
CARDIAC_ARREST_BRAIN_DAMAGE_PER_MIN = 0.08
STROKE_DISSOLVE_CHANCE_PER_CHECK    = 0.20
COMA_RECOVERY_CHANCE_BASE           = 0.25
COMA_DEATH_RISK_PER_WEEK            = 0.05

# Still used by _apply_head_impact (trigger_seizure's head-impact roll) --
# the old apply_blunt_trauma's own thresholds (bone-break/lung-damage/
# unconscious) are gone with it, deleted in Round 3 of the damage-system
# rework in favor of definitions.json's health_hazard_templates.
BLUNT_HEAD_MENTAL_TRAIT_THRESHOLD = 0.60

TRAUMA_MENTAL_TRAITS = [
    "depression", "paranoid_personality", "antisocial_personality",
    "ptsd", "dementia", "bipolar_disorder"
]


# ---------------------------------------------------------------------------
# Memory helper (graceful fallback if brain module absent)
# ---------------------------------------------------------------------------

def _remember(char, msg, weight, tags, category, tick):
    try:
        from brain.memory import store_memory
        store_memory(char, msg, weight, tags, category, tick)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Immune score
# ---------------------------------------------------------------------------

def _age_immune_penalty(age):
    """Daily immune decay bonus/penalty from age alone.
    Children (<12) and elderly (>65) have naturally weaker immune systems."""
    if age is None:
        return 0.0
    if age < 5:
        return -1.5   # infants — very vulnerable
    if age < 12:
        return -0.5   # children — still developing
    if age < 30:
        return 0.0    # peak immunity
    if age < 50:
        return -0.2   # gradual decline
    if age < 65:
        return -0.6
    if age < 75:
        return -1.2
    return -2.0       # elderly 75+ — substantially weakened


# physical_trait_templates entries with a plausible constitutional effect on
# disease susceptibility -- read from char["physical_traits"] (not
# char["traits"], which holds personality traits). The other 27 entries in
# the registry (extra_toe, giant_penis, colorblind, ...) are cosmetic/sensory
# and have no health-relevant effect.
_TRAIT_IMMUNE_DELTAS = {
    "obese":             -1.0,
    "underweight":       -0.8,
    "low_stamina":       -0.6,
    "high_stamina":       0.5,
    "slow_metabolism":   -0.3,
    "fast_metabolism":    0.3,
    "insomnia":          -0.5,
    "sensitive_stomach": -0.3,
}


def _trait_immune_penalty(char):
    return sum(_TRAIT_IMMUNE_DELTAS.get(t, 0.0) for t in char.get("physical_traits", []))


def immune_modifier(char):
    """
    Returns a 0.0-1.0 multiplier for random health-check probabilities.
    At 100 immune_score the modifier is 1.0 (no amplification).
    At 0 it is 2.5 (two and a half times more likely to get/worsen conditions).
    """
    score = char.get("immune_score", 100.0)
    # Linear interpolation: score 100 → 1.0, score 0 → 2.5
    return 1.0 + (1.0 - score / 100.0) * 1.5


def compute_daily_immune_delta(char, world):
    log = char.get("daily_log", {})
    delta = 0.0

    sleep_h = log.get("sleep_hours", 7)
    if sleep_h < 4:
        delta -= 6.0
    elif sleep_h < 6:
        delta -= 3.0
    elif sleep_h > 10:
        delta -= 1.0

    if log.get("sleep_time_variance_hours", 0) > 2:
        delta -= 1.5
    if log.get("meal_timing_variance_hours", 0) > 3:
        delta -= 1.0

    for q in log.get("meal_quality", []):
        if q == "healthy":
            delta += 0.5
        elif q == "junk":
            delta -= 1.0
        elif q == "none":
            delta -= 2.0

    delta -= log.get("alcohol_units", 0) * 0.8
    if log.get("drug_use", False):
        delta -= 3.0
    if log.get("caffeine_cups", 0) > 4:
        delta -= 0.5
    if log.get("sugar_intake_high", False):
        delta -= 0.8

    # Poor hygiene contact (set by contagion system)
    if log.get("contacted_unhygienic_person", False):
        delta -= 0.5

    if sleep_h >= 7 and not log.get("drug_use", False) and log.get("alcohol_units", 0) < 2:
        delta += 1.5

    for cond_key in char.get("physical_health", []):
        if cond_key == "std_hiv":
            delta -= 2.0
        elif cond_key == "cancer_high":
            delta -= 1.5
        elif cond_key == "cancer_medium":
            delta -= 0.8

    # Neglected physical needs (c["body"], live state -- distinct from the
    # daily_log snapshot above, e.g. sleep_debt is accumulated across days
    # while sleep_hours only reflects last night).
    b = char.get("body", {})
    if b.get("hygiene", 100) < 30:
        delta -= 0.8
    if b.get("hunger", 0) > 85:
        delta -= 1.2
    if b.get("hydration", 100) < 25:
        delta -= 1.5
    if b.get("sleep_debt", 0) > 75:
        delta -= 1.0

    # Age penalty
    delta += _age_immune_penalty(char.get("age"))

    # Physical trait penalty/bonus
    delta += _trait_immune_penalty(char)

    return delta


def tick_immune_score(char, world):
    if "immune_score" not in char:
        char["immune_score"] = 100.0
    delta = compute_daily_immune_delta(char, world)
    char["immune_score"] = max(0.0, min(100.0, char["immune_score"] + delta))
    # Low immune score → opportunistic infection; age amplifies risk
    opp_threshold = 0.15 * immune_modifier(char)
    if char["immune_score"] < 40 and random.random() < opp_threshold:
        _trigger_opportunistic_infection(char, world)


def _trigger_opportunistic_infection(char, world):
    candidates = ["common_cold", "influenza", "aggressive_gut_bacteria"]
    condition = random.choice(candidates)
    if condition not in char.get("physical_health", []):
        char.setdefault("physical_health", []).append(condition)
        try:
            from systems.contagion import update_contagious_state
            update_contagious_state(char, world.get("tick", 0))
        except ImportError:
            pass
        _remember(char, "Became ill from a weakened immune system.", 0.80,
                  ["health", condition], "health", world.get("tick", 0))


# ---------------------------------------------------------------------------
# Physical condition progression
# ---------------------------------------------------------------------------

def tick_physical_conditions(char, world):
    defs = world.get("definitions", {})
    ph_templates = defs.get("physical_health_templates", {})
    tick = world.get("tick", 0)

    for cond_key in list(char.get("physical_health", [])):
        tmpl = ph_templates.get(cond_key)
        if not tmpl:
            continue

        state = char.setdefault("condition_state", {}).setdefault(cond_key, {
            "severity_index": 0.0, "days_elapsed": 0
        })
        state["days_elapsed"] += 1

        if tmpl.get("progressive"):
            state["severity_index"] = min(
                1.0,
                state["severity_index"] + tmpl.get("worsening_rate_per_day", 0.002)
            )

        if cond_key == "heart_disease_high":
            _check_heart_disease_high(char, world, tick)

        if cond_key == "cancer_high" and state["days_elapsed"] % 7 == 0:
            risk = tmpl.get("mortality_risk_per_week", 0.03) * immune_modifier(char)
            if random.random() < risk:
                _trigger_death(char, world, "cancer_high_terminal")

        if cond_key == "epilepsy":
            meds = char.get("health_state", {}).get("medications_taken", {})
            has_med = "antiepileptic" in meds
            base = (tmpl.get("seizure_chance_without_meds_per_day", 0.35)
                    if not has_med else tmpl.get("seizure_trigger_chance_per_day", 0.08))
            chance = min(0.95, base * immune_modifier(char))
            if random.random() < chance:
                trigger_seizure(char, world, tick)

        if cond_key == "concussion":
            # Multiple concussions: cumulative CTE risk
            count = sum(1 for c in char.get("condition_state", {})
                        if c == "concussion")
            if count >= 3 and random.random() < 0.05 * count:
                _apply_trauma_mental_trait(char, world, tick, "repeated_concussions")

        if cond_key == "borrelia":
            days = state.get("days_elapsed", 0)
            meds = char.get("health_state", {}).get("medications_taken", {})
            if days >= tmpl.get("becomes_chronic_after_days", 60) and "antibiotic_broad" not in meds:
                if "nerve_damage" not in char.get("physical_health", []):
                    char["physical_health"].append("nerve_damage")
                char["physical_health"].remove("borrelia")
                _remember(char, "Borrelia became chronic, causing nerve damage.", 0.9,
                          ["health", "borrelia"], "health", tick)

        # symptoms[] (an array of {hazard_template, probability} referencing
        # health_hazard_templates DIRECTLY -- the 2-level chain collapse,
        # decision #1 of the disease-schema-overhaul round) is the new
        # disease-side driver -- periodically rolls which hazard (if any) is
        # currently felt and routes its pain through the same hazard
        # vocabulary injuries use. Diseases not yet migrated onto this shape
        # keep the old always-on active_symptoms list unchanged.
        if tmpl.get("symptoms"):
            _tick_disease_symptom(char, world, defs, tmpl, state, tick, cond_key)
        else:
            for symptom_key in tmpl.get("active_symptoms", []):
                _apply_symptom_penalties(char, world, symptom_key, defs)
                tick_symptom_reactions(char, world, defs, symptom_key, state["severity_index"])

        advance_treatment_progress(char, world, cond_key, tmpl, state, tick)

        sp = tmpl.get("stamina_penalty", 0)
        if sp:
            char["stamina"] = max(0.0, char.get("stamina", 1.0) - sp * 0.01)

    _check_recoveries(char, world, ph_templates, tick)
    char.setdefault("health_state", {})["doctor_visits_needed"] = \
        _compute_doctor_visits_needed(char, ph_templates)


def _compute_doctor_visits_needed(char, ph_templates):
    """How many doctor/hospital visits would fully treat this character's
    current undertreated conditions right now -- severity-scaled (see
    systems/offgrid.py::maybe_schedule_doctor_visit, the consumer). A
    condition already covered by medications_taken doesn't keep demanding
    visits, so this falls back to 0 once treatment catches up."""
    total = 0
    meds = char.get("health_state", {}).get("medications_taken", {})
    for cond_key in char.get("physical_health", []):
        tmpl = ph_templates.get(cond_key, {})
        medicine = tmpl.get("medicine", [])
        if medicine and any(m in meds for m in medicine):
            continue
        total += max(1, round(tmpl.get("severity", 3) / 3))
    return min(total, 5)


def _check_heart_disease_high(char, world, tick):
    tmpl = (world.get("definitions", {})
            .get("physical_health_templates", {})
            .get("heart_disease_high", {}))
    emergencies = char.setdefault("health_state", {}).setdefault("active_emergencies", {})

    mod = immune_modifier(char)
    if "heart_attack" not in emergencies:
        if random.random() < tmpl.get("heart_attack_risk_per_day", 0.08) * mod:
            trigger_heart_attack(char, world, tick)

    if "unconscious" not in emergencies:
        if random.random() < tmpl.get("collapse_risk_per_day", 0.05) * mod:
            emergencies["unconscious"] = {"severity": 7, "onset_tick": tick,
                                           "cause": "heart_disease_high_collapse"}
            _remember(char, "Collapsed from severe heart disease.", 0.95,
                      ["health", "heart_disease"], "health", tick)


def _apply_need_penalty_map(char, need_penalties):
    """need_penalties keys (0-1 scale, authored on symptom_templates for
    legacy diseases and directly on health_hazard_templates for the new
    2-level shape, decision #2) don't correspond to any top-level character
    field -- route each to its real home: hunger/hygiene live in c["body"]
    (0-100 scale), energy has no dedicated field so it feeds the inverse
    (fatigue), and fun/social are long-term-need satisfaction, tracked as
    frustration in c["lt_needs"]."""
    b  = char.setdefault("body", {})
    lt = char.get("lt_needs", {})
    for need, amount in need_penalties.items():
        mag = abs(amount) * 5  # authored 0-1 scale -> body.py's 0-100 scale
        if need == "hunger":
            b["hunger"] = min(100, b.get("hunger", 0) + mag)
        elif need == "hygiene":
            b["hygiene"] = max(0, b.get("hygiene", 100) - mag)
        elif need == "energy":
            b["fatigue"] = min(100, b.get("fatigue", 0) + mag)
        elif need in ("fun", "social"):
            nd = lt.get("play" if need == "fun" else "socialize")
            if nd:
                nd["frustration"] = min(1.0, nd.get("frustration", 0.0) + abs(amount) * 0.3)


def _apply_symptom_penalties(char, world, symptom_key, defs):
    """Legacy-path wrapper: need_penalties authored on symptom_templates,
    for the 25 diseases still on the flat active_symptoms loop (decision #1
    -- symptom_templates stays frozen, not deleted, as their driver)."""
    tmpl = defs.get("symptom_templates", {}).get(symptom_key, {})
    _apply_need_penalty_map(char, tmpl.get("need_penalties", {}))


# Symptom -> reaction type, for the symptoms with a clean, distinct
# physical cue worth an observable reaction (see reactions.py's
# push_reaction/REACTION_ANIMATIONS -- the same mechanism hostile actions
# already use). Deliberately not every visual symptom in symptom_templates:
# convulsions already gets dramatic treatment via trigger_seizure()'s own
# active_emergencies path, and the rest (mood_swings/runny_nose/rash/
# speech_difficulty) don't have a clean single-clip cue -- skipped rather
# than forcing a weak mapping.
_SYMPTOM_REACTION_MAP = {
    "coughing":             "cough",
    "sweating":             "sweating",
    "fever":                "sweating",
    "shortness_of_breath":  "breathless",
    "dizziness":            "dizzy",
    "runny_nose":           "sneeze",   # previously skipped as having no
                                         # clean cue -- sneeze fits it directly
}


def tick_symptom_reactions(char, world, defs, symptom_key, severity_index):
    """
    For the symptoms with a clean visual cue, fires a real observable
    reaction. Called from tick_physical_conditions()'s existing
    per-condition loop -- same daily cadence, no new cadence machinery.
    """
    tmpl = defs.get("symptom_templates", {}).get(symptom_key)
    if not tmpl:
        return

    if not tmpl.get("visual"):
        return
    reaction_type = _SYMPTOM_REACTION_MAP.get(symptom_key)
    if not reaction_type:
        return
    try:
        from systems.reactions import trigger_reaction
        trigger_reaction(char, world, reaction_type, tick=world.get("tick", 0))
    except Exception:
        pass


def _clear_symptom_hazard(char, state):
    """Tears down the mirrored hazard instance (decision #11) for the
    currently-selected symptom (onset), called when that symptom expires
    or gets rerolled away, and resets stage tracking (decision #12) --
    called BEFORE state["current_symptom"] is overwritten at every call
    site, so hazard_key below is still the outgoing hazard."""
    locality = state.get("symptom_pain_locality", "systemic")
    hazard_key = state.get("current_symptom")
    if hazard_key:
        hs = char.get("health_state", {})
        if locality in BODY_PARTS:
            hs.get("body_parts", {}).get(locality, {}).get("hazards", {}).pop(hazard_key, None)
        else:
            hs.get("systemic_hazards", {}).pop(hazard_key, None)
    state["stage_index"] = -1
    state["stage_recovery_progress_tick"] = None


def _minutes_to_ticks(minutes):
    """health_hazard_templates' new stages[*].duration / interval_minutes /
    recovery_minutes_per_stage fields are authored in minutes; this file's
    existing onset-elapsed math (stroke/seizure, TICKS_PER_HOUR) already
    treats 1 tick as 1 hour, so minutes -> ticks divides by 60. Floors at 1
    tick so a short authored value never silently becomes a no-op."""
    return max(1, round(minutes / (60.0 / TICKS_PER_HOUR)))


# Recovery-timer trait modifiers (decision #14) -- multiplies
# recovery_minutes_per_stage, <1 recovers faster / >1 slower. Mirrors
# _TRAIT_IMMUNE_DELTAS' own precedent: a hardcoded per-trait lookup here
# rather than a new numeric field on physical_trait_templates, matching how
# every other entry in that registry is authored (name/description/polarity
# only).
_TRAIT_RECOVERY_DELTAS = {
    "physically_resilient": 0.6,
    "tough":                0.75,
    "low_blood_cells":      1.5,
}


def _recovery_trait_modifier(char):
    mod = 1.0
    for t in char.get("physical_traits", []):
        if t in _TRAIT_RECOVERY_DELTAS:
            mod *= _TRAIT_RECOVERY_DELTAS[t]
    return mod


# Posture vocabulary a character must be in for rest-driven stage recovery
# to progress (decision #14) -- deliberately the same restful set
# manifestations' preferred_postures already advises toward, giving that
# advisory field real mechanical weight. "crouching" from the original spec
# isn't a real stance_templates key in this codebase (only "crawling",
# which is pain-driven, not restful) -- omitted rather than crashing on a
# key that doesn't exist.
_RESTFUL_POSTURES = {"sitting_seat", "sitting_floor", "lying", "leaning_wall"}


def _hazard_instance(char, locality, hazard_key):
    """Looks up the mirrored hazard-instance dict written by
    _tick_disease_symptom's onset (decision #11) -- body_parts[locality].
    hazards[hazard_key] for a body-part locality, or systemic_hazards[key]
    otherwise. Returns None if it hasn't been mirrored (e.g. still onboarding
    this tick) rather than creating one -- onset is solely _tick_disease_
    symptom's responsibility."""
    hs = char.get("health_state", {})
    if locality in BODY_PARTS:
        return hs.get("body_parts", {}).get(locality, {}).get("hazards", {}).get(hazard_key)
    return hs.get("systemic_hazards", {}).get(hazard_key)


def _advance_hazard_stage(char, hazard_tmpl, state, tick):
    """Stage/severity escalation + rest-driven recovery (decision #12/#14).
    Elapsed-minutes-since-onset climbs health_hazard_templates' stages
    ladder; while NOT actively climbing (next threshold not yet reached)
    and the character is in a restful posture, a separate recovery timer
    counts down and drops current_stage back one tier on completion,
    scaled by _recovery_trait_modifier. Writes the resolved health_state
    tier name (not the stage key) directly onto the mirrored hazard
    instance so compute_severity() needs no template lookup of its own."""
    stages = hazard_tmpl.get("stages")
    if not stages:
        return
    hazard_key = state.get("current_symptom")
    locality = state.get("symptom_pain_locality", "systemic")
    instance = _hazard_instance(char, locality, hazard_key)
    if instance is None:
        return

    ordered = list(stages.items())
    started = state.get("symptom_started_tick", tick)
    elapsed_minutes = (tick - started) * (60.0 / TICKS_PER_HOUR)

    target_idx = -1
    for i, (_skey, sdata) in enumerate(ordered):
        if elapsed_minutes >= sdata.get("duration", 0):
            target_idx = i
    current_idx = state.get("stage_index", -1)

    if target_idx > current_idx:
        state["stage_index"] = target_idx
        state["stage_recovery_progress_tick"] = tick
        instance["current_stage"] = ordered[target_idx][1].get("health_state")
        return

    if current_idx < 0:
        return
    if char.get("posture") not in _RESTFUL_POSTURES:
        return
    recovery_minutes = hazard_tmpl.get("recovery_minutes_per_stage")
    if not recovery_minutes:
        return
    recovery_ticks = _minutes_to_ticks(recovery_minutes) * _recovery_trait_modifier(char)
    last = state.get("stage_recovery_progress_tick", tick)
    if tick - last >= recovery_ticks:
        new_idx = current_idx - 1
        state["stage_index"] = new_idx
        state["stage_recovery_progress_tick"] = tick
        instance["current_stage"] = ordered[new_idx][1].get("health_state") if new_idx >= 0 else None


def _apply_manifestation(char, world, cond_key, m, tick):
    """Applies one rolled manifestation (decision #8) -- gesture reaction,
    contagion burst, and locomotion restriction, routed through existing
    primitives rather than a new posture-setting path
    (apply_severity_consequences stays the sole set_posture authority,
    reconciling posture from functional_status this writes on its own
    very next call)."""
    gesture = m.get("gesture")
    if gesture:
        try:
            from systems.reactions import push_reaction
            push_reaction(char, gesture, tick)
        except Exception:
            pass

    restrict = m.get("locomotion_restricted_to")
    if restrict == "crawl":
        hs = char.setdefault("health_state", {})
        for leg in ("left_leg", "right_leg"):
            bp = hs.setdefault("body_parts", {}).setdefault(leg, _blank_body_part())
            bp["functional_status"] = "unusable"

    if m.get("spreads_contagion"):
        try:
            from systems.contagion import attempt_manifestation_contagion_burst
            attempt_manifestation_contagion_burst(char, world, cond_key, tick)
        except Exception:
            pass

    if m.get("interrupts_interaction"):
        try:
            from systems.activity_queue import suspend_activity_queue
            suspend_activity_queue(char, world, reason="symptom_manifestation")
        except Exception:
            pass


_PASSIVE_TRAIT_INCREMENT = 2.0
_DIZZY_TRAIT_DURATION_TICKS = 60


def _apply_passive_traits(char, hazard_tmpl, tick):
    """Decision #7: type=='passive' hazards don't roll manifestations --
    they continuously nudge a real character field instead. tired/
    low_energy -> body.fatigue, low_stamina -> stamina, moody/short_temper
    -> emotional_temperature (the same incremental way stress/sleep_debt
    already are), dizzy -> the one genuinely new piece of state,
    health_state.temporary_traits, self-renewed each visit and read by
    movement.py's intoxication fatigue-curve multiplier rather than
    duplicating that curve."""
    traits = hazard_tmpl.get("passive_traits")
    if not traits:
        return
    b = char.setdefault("body", {})
    for t in traits:
        if t in ("tired", "low_energy"):
            b["fatigue"] = min(100, b.get("fatigue", 0) + _PASSIVE_TRAIT_INCREMENT)
        elif t == "low_stamina":
            char["stamina"] = max(0.0, char.get("stamina", 1.0) - _PASSIVE_TRAIT_INCREMENT * 0.01)
        elif t in ("moody", "short_temper"):
            char["emotional_temperature"] = min(100, char.get("emotional_temperature", 20) + _PASSIVE_TRAIT_INCREMENT)
        elif t == "dizzy":
            hs = char.setdefault("health_state", {})
            hs.setdefault("temporary_traits", {})["dizzy"] = tick + _DIZZY_TRAIT_DURATION_TICKS


def _sweep_temporary_traits(char, tick):
    tt = char.get("health_state", {}).get("temporary_traits")
    if not tt:
        return
    for key in [k for k, expires in tt.items() if expires <= tick]:
        del tt[key]


def tick_hazard_manifestations(char, world):
    """Every-tick driver (called unconditionally from process_health, like
    tick_health_hazards) for health_hazard_templates' manifestations map --
    the periodic gesture/contagion-burst/pain/incapacitation episodes
    layered on top of the once-a-day hazard SELECTION _tick_disease_symptom
    already does. interval_minutes is minutes-denominated like stages'
    duration (see _minutes_to_ticks), so a manifestation's cadence is
    independent of and much finer than the daily reroll. apply_during_
    treatment==False hazards (decision #15) are skipped entirely while
    their disease's treatment is in progress; a hazard instance already
    marked treated (e.g. by the ambulance bridge, decision #13) stops
    manifesting too. Stage advancement/recovery (decision #12/#14) runs
    every visit regardless of the manifestation roll cadence."""
    defs = world.get("definitions", {})
    hazard_registry = defs.get("health_hazard_templates", {})
    tick = world.get("tick", 0)
    treatment_progress = char.get("health_state", {}).get("treatment_progress", {})

    _sweep_temporary_traits(char, tick)

    for cond_key, state in char.get("condition_state", {}).items():
        current = state.get("current_symptom")
        if not current:
            continue
        hazard_tmpl = hazard_registry.get(current)
        if not hazard_tmpl:
            continue

        _advance_hazard_stage(char, hazard_tmpl, state, tick)

        if hazard_tmpl.get("type") == "passive":
            _apply_passive_traits(char, hazard_tmpl, tick)
            continue
        if hazard_tmpl.get("type") != "active":
            continue
        if not hazard_tmpl.get("apply_during_treatment", True) and \
                treatment_progress.get(cond_key, {}).get("treatment_started"):
            continue
        instance = _hazard_instance(char, state.get("symptom_pain_locality", "systemic"), current)
        if instance and instance.get("treated"):
            continue

        manifestations = hazard_tmpl.get("manifestations")
        if not manifestations:
            continue
        interval = _minutes_to_ticks(hazard_tmpl.get("interval_minutes", 60))
        last = state.get("last_manifestation_tick", tick - interval)
        if tick - last < interval:
            continue
        state["last_manifestation_tick"] = tick
        pick = weighted_pick(list(manifestations.values()))
        if pick:
            _apply_manifestation(char, world, cond_key, pick, tick)


def _hazard_locality(hazard_tmpl):
    """Picks a representative body locality for a hazard instance --
    derived from its dominant (highest-probability) manifestation's
    pain_target where the hazard has manifestations (type=='active'),
    else systemic. This is a coarse
    per-day-check signal distinct from the finer per-manifestation pain_mod
    rolls the manifestation cadence itself applies (Round 4)."""
    manifestations = hazard_tmpl.get("manifestations")
    if manifestations:
        best = max(manifestations.values(), key=lambda m: m.get("probability", 0))
        target = best.get("pain_target")
        if target and target != "all":
            return target
    return "systemic"


def _tick_disease_symptom(char, world, defs, tmpl, state, tick, cond_key=None):
    """Disease-side driver of the shared symptom/hazard machinery: on
    symptom_refresh_interval cadence, rolls symptoms[] (weighted_pick --
    same mutually-exclusive {ref, probability} pool convention as
    everywhere else in the chain, a shortfall is "no symptom right now")
    to decide which health_hazard_templates entry (if any) is currently
    felt -- the 2-level chain collapse: symptoms[] references
    health_hazard_templates DIRECTLY, no more symptom_templates middle
    layer for diseases migrated onto this shape. The selected hazard
    lands on a body part via _hazard_locality() or systemic otherwise.
    need_penalties keep applying every day-check while a hazard stays
    selected, same granularity the old always-on active_symptoms loop
    had. Gesture/contagion-burst manifestation behavior is wired
    separately on its own interval_minutes cadence (Round 4)."""
    interval = tmpl.get("symptom_refresh_interval", 240)
    hazard_registry = defs.get("health_hazard_templates", {})
    current = state.get("current_symptom")

    if current:
        hazard_tmpl = hazard_registry.get(current, {})
        # indefinite (decision #13) ignores duration_hours entirely -- the
        # hazard persists until cleared by one of its own treatable_by
        # methods (e.g. the ambulance bridge in emergency.py::resolve()),
        # never by this timer.
        duration = 0 if hazard_tmpl.get("indefinite") else hazard_tmpl.get("duration_hours", 0) * TICKS_PER_HOUR
        started = state.get("symptom_started_tick", tick)
        if duration and tick - started >= duration:
            _clear_symptom_hazard(char, state)
            current = None
            state["current_symptom"] = None

    last_check = state.get("last_symptom_check_tick", tick - interval)
    if tick - last_check >= interval:
        state["last_symptom_check_tick"] = tick
        if current:
            _clear_symptom_hazard(char, state)
        pick = weighted_pick(tmpl.get("symptoms", []))
        current = pick.get("hazard_template") if pick else None
        state["current_symptom"] = current
        if current:
            state["symptom_started_tick"] = tick
            hazard_tmpl = hazard_registry.get(current, {})
            locality = _hazard_locality(hazard_tmpl)
            state["symptom_pain_locality"] = locality
            state["stage_index"] = -1
            state["stage_recovery_progress_tick"] = None

            # Mirror a lightweight hazard-instance entry (decision #11) --
            # reuses the exact shape apply_injury's body_parts[*].hazards
            # already writes, plus expires_tick/current_stage for the
            # frontend tooltip/stage system. Non-body-part localities
            # ("systemic") get an equivalent entry under the new
            # health_state.systemic_hazards dict instead.
            duration = 0 if hazard_tmpl.get("indefinite") else hazard_tmpl.get("duration_hours", 0) * TICKS_PER_HOUR
            instance = {
                "tick_applied": tick, "last_ticked": tick, "treated": False,
                "hazard_template": current,
                "expires_tick": (tick + duration) if duration else None,
                "current_stage": None,
            }
            hs = char.setdefault("health_state", {})
            if locality in BODY_PARTS:
                hs.setdefault("body_parts", {}).setdefault(locality, _blank_body_part())["hazards"][current] = instance
            else:
                hs.setdefault("systemic_hazards", {})[current] = instance

    if not current:
        return
    hazard_tmpl = hazard_registry.get(current)
    if not hazard_tmpl:
        return
    _apply_need_penalty_map(char, hazard_tmpl.get("need_penalties", {}))


def _blank_treatment_progress(tick):
    """See decision #16: treatment_started stays False until step 0 (index
    0) completes; last_completed_tick is None until then, since there's no
    prior completion to measure expiry_days from -- step 0's own deadline
    is the disease-level must_treat_within instead. step0_started_tick is
    this engine's own bookkeeping (not part of the user's spec) for driving
    a 'rest' step's day-count before treatment_started flips true."""
    return {
        "treatment_started": False, "step_index": 0, "last_completed_tick": None,
        "times_done": 0, "appointment_booked": False, "step0_started_tick": tick,
    }


def _advance_treatment_step(tp, tick):
    """On completing a step: treatment_started -> True, step_index += 1,
    last_completed_tick = this tick (decision #16)."""
    tp["treatment_started"] = True
    tp["step_index"] += 1
    tp["last_completed_tick"] = tick
    tp["times_done"] = 0
    tp["appointment_booked"] = False


def _drive_appointment_step(char, world, step, tp, tick, business_key, reason):
    """doctors_visit/hospital_treatment/surgery step types -- generalizes
    maybe_schedule_doctor_visit's book/poll pattern (systems/appointments.py)
    keyed to a treatment step instead of severity. appointment_booked cycles
    False (not yet booked) -> True (booked, waiting for the slot) -> "sent"
    (off-grid now, decision #9/#10's side_effects resolve in offgrid.py::
    process_return once they return) -> back to False once the trip
    completes, which is this function's signal the step is done."""
    from systems.appointments import has_upcoming_appointment, is_appointment_due, book

    if tp.get("appointment_booked") == "sent":
        if not char.get("off_grid"):
            tp["appointment_booked"] = False
            return True
        return False

    appt = has_upcoming_appointment(char, business_key)
    if appt:
        if is_appointment_due(appt, world):
            appt["fulfilled"] = True
            duration = 90 if reason in ("surgery", "hospital_treatment") else 20
            from systems.offgrid import send_offgrid
            char.setdefault("health_state", {})["_active_treatment_step"] = dict(step)
            if send_offgrid(char, world, reason, duration):
                tp["appointment_booked"] = "sent"
        return False

    if not tp.get("appointment_booked"):
        from core.definitions import load_definitions
        business = (load_definitions(world.get("sim_id", "default")).get("company_templates") or {}).get(business_key)
        if business:
            book(char, world, business_key, business, reason)
            tp["appointment_booked"] = True
    return False


def _drive_medication_step(char, world, cond_key, step, tp, tick):
    """medication step type. Reuses the existing medications_taken
    mechanism (already populated by the legacy doctor/hospital branch in
    offgrid.py::process_return) as the "do we have and are we taking this"
    signal, rather than building a separate item-purchase/inventory path --
    a deliberate scope decision, not an oversight (dangerous_combinations'
    own consumption-scaling logic is likewise deferred, per this round's
    documented scope cuts). Not yet obtained -> book a pharmacy trip;
    once obtained -> "administer" on the step's interval-day cadence for
    num_times applications."""
    med_key = step.get("medication")
    if not med_key:
        return True

    meds = char.setdefault("health_state", {}).setdefault("medications_taken", {})
    if med_key not in meds:
        if tp.get("appointment_booked") == "sent":
            if not char.get("off_grid"):
                tp["appointment_booked"] = False
                meds[med_key] = {"tick": tick, "treats": cond_key}
            return False
        if not tp.get("appointment_booked"):
            from systems.offgrid import send_offgrid
            if send_offgrid(char, world, "pharmacy", 15):
                tp["appointment_booked"] = "sent"
        return False

    num_times = step.get("num_times", 1) if step.get("application_type") == "num_times" else 1
    interval_days = step.get("interval", 1)
    ref = tp.get("last_med_tick")
    if ref is None:
        ref = tp.get("last_completed_tick") if tp["treatment_started"] else tp.get("step0_started_tick", tick)
    if ref is not None and tick - ref >= interval_days * TICKS_PER_DAY:
        tp["times_done"] = tp.get("times_done", 0) + 1
        tp["last_med_tick"] = tick
        _roll_medication_side_effects(char, world, med_key, tick)
        if tp["times_done"] >= num_times:
            return True
    return False


def _roll_medication_side_effects(char, world, med_key, tick):
    """Round 6: item_templates[med_key].side_effects (a {hazard_template:
    probability} map, converted from the old flat string list) gets one
    independent roll per administration -- mirrors apply_injury's
    possible_hazards roll (independent per-hazard, not weighted_pick's
    mutually-exclusive pool, since a medication can plausibly trigger more
    than one side effect on the same dose)."""
    defs = world.get("definitions", {})
    item_tmpl = defs.get("item_templates", {}).get(med_key, {})
    hazard_registry = defs.get("health_hazard_templates", {})
    hs = char.setdefault("health_state", {})
    for hazard_key, prob in item_tmpl.get("side_effects", {}).items():
        if hazard_key not in hazard_registry or random.random() >= prob:
            continue
        locality = _hazard_locality(hazard_registry[hazard_key])
        instance = {
            "tick_applied": tick, "last_ticked": tick, "treated": False,
            "hazard_template": hazard_key, "expires_tick": None, "current_stage": None,
        }
        if locality in BODY_PARTS:
            bp = hs.setdefault("body_parts", {}).setdefault(locality, _blank_body_part())
            bp["hazards"][hazard_key] = instance
            if not bp.get("severity_level"):
                bp["severity_level"] = "low"
            bp["functional_status"] = _functional_status_for(bp["severity_level"], bp["hazards"])
        else:
            hs.setdefault("systemic_hazards", {})[hazard_key] = instance


def _drive_treatment_step(char, world, cond_key, step, tp, tick):
    step_type = step.get("type")
    if step_type == "rest":
        ref = tp.get("last_completed_tick") if tp["treatment_started"] else tp.get("step0_started_tick", tick)
        interval_days = step.get("interval", 3)
        return ref is not None and tick - ref >= interval_days * TICKS_PER_DAY
    if step_type == "doctors_visit":
        return _drive_appointment_step(char, world, step, tp, tick, "gp_clinic", "doctor")
    if step_type in ("hospital_treatment", "surgery"):
        return _drive_appointment_step(char, world, step, tp, tick, "hospital", step_type)
    if step_type == "medication":
        return _drive_medication_step(char, world, cond_key, step, tp, tick)
    return False


def advance_treatment_progress(char, world, cond_key, tmpl, state, tick):
    """Drives physical_health_templates' treatments[] array through
    decision #16's exact adherence semantics. Called from tick_physical_
    conditions' daily per-condition loop for every disease that authors
    treatments[], new-shape or legacy alike -- treatments[] is independent
    of the symptoms[]/active_symptoms chain-collapse split."""
    treatments = tmpl.get("treatments")
    if not treatments:
        return

    tp_all = char.setdefault("health_state", {}).setdefault("treatment_progress", {})
    tp = tp_all.get(cond_key)
    if tp is None:
        tp = _blank_treatment_progress(tick)
        tp_all[cond_key] = tp

    step_index = min(tp["step_index"], len(treatments) - 1)
    step = treatments[step_index]

    # Adherence check -- skipped once there's no next step left to be
    # overdue for (decision #16's "Edge case, resolved").
    if tp["treatment_started"] and step_index < len(treatments) - 1:
        expiry_days = step.get("expiry_days")
        last = tp.get("last_completed_tick")
        if expiry_days and last is not None and tick - last > expiry_days * TICKS_PER_DAY:
            tp_all[cond_key] = _blank_treatment_progress(tick)
            return

    if _drive_treatment_step(char, world, cond_key, step, tp, tick):
        _advance_treatment_step(tp, tick)
        # Weight-extreme diseases (malnutrition/obesity_metabolic_disorder,
        # decision #9) are indefinite -- treatments[] never "cures" them,
        # it just nudges weight_kg each time a full cycle completes, then
        # loops. Any other disease's treatment_effect (if ever authored)
        # gets the same nudge-and-loop treatment.
        effect = tmpl.get("treatment_effect")
        if effect and tp["step_index"] >= len(treatments):
            if effect == "weight_gain":
                char["weight_kg"] = char.get("weight_kg", 70) + 2.0
            elif effect == "weight_loss":
                char["weight_kg"] = max(20.0, char.get("weight_kg", 70) - 2.0)
            tp_all[cond_key] = _blank_treatment_progress(tick)


def _check_recoveries(char, world, ph_templates, tick):
    for cond_key in list(char.get("physical_health", [])):
        tmpl = ph_templates.get(cond_key, {})
        state = char.setdefault("condition_state", {}).get(cond_key, {})
        days = state.get("days_elapsed", 0)
        meds = char.get("health_state", {}).get("medications_taken", {})
        treated = any(m in meds for m in tmpl.get("medicine", []))

        # Untreated progression to a worse condition -- checked before
        # recovery/self-resolve so a condition left untreated long enough
        # gets worse instead of just clearing on its own.
        progresses_to = tmpl.get("next_stage")
        threshold = tmpl.get("must_treat_within")
        if progresses_to and threshold and not treated and days >= threshold:
            char["physical_health"].remove(cond_key)
            char.get("condition_state", {}).pop(cond_key, None)
            if progresses_to not in char["physical_health"]:
                char["physical_health"].append(progresses_to)
            new_name = ph_templates.get(progresses_to, {}).get("name", progresses_to)
            _remember(char, f"{tmpl.get('name', cond_key)} worsened into {new_name} after going untreated.",
                      0.9, ["health", "progression"], "health", tick)
            continue

        recovered = False
        if tmpl.get("curable") and not tmpl.get("progressive"):
            duration = tmpl.get("typical_duration_days", 7)
            # A weaker/older character (higher immune_modifier) takes longer
            # to shake off a condition even when treated.
            required = duration * (0.6 if treated else 1.0) * immune_modifier(char)
            if days >= required:
                recovered = True

        # Self-resolve (Round 5) -- an independent path distinct from the
        # treated-cure branch above: gives ANY condition (regardless of
        # curable/progressive flags, and regardless of treatment) a way to
        # eventually clear on its own after self_resolve_days, per the
        # "will it go away even if untreated" spec.
        if not recovered and tmpl.get("self_resolves") and days >= tmpl.get("self_resolve_days", 9999):
            recovered = True

        if recovered:
            char["physical_health"].remove(cond_key)
            try:
                from systems.contagion import update_contagious_state
                update_contagious_state(char, tick)
            except ImportError:
                pass
            _remember(char, f"Recovered from {tmpl.get('name', cond_key)}.", 0.7,
                      ["health", "recovery"], "health", tick)


# ---------------------------------------------------------------------------
# Heart attack
# ---------------------------------------------------------------------------

def trigger_heart_attack(char, world, tick):
    em = char.setdefault("health_state", {}).setdefault("active_emergencies", {})
    em["heart_attack"] = {
        "severity": 9, "onset_tick": tick,
        "heart_stopped": False, "minutes_elapsed": 0
    }
    _remember(char, "Is having a heart attack!", 1.0, ["health", "emergency"], "health", tick)


def tick_heart_attack(char, world):
    tick = world.get("tick", 0)
    state = char.get("health_state", {}).get("active_emergencies", {}).get("heart_attack")
    if not state:
        return
    state["minutes_elapsed"] = (tick - state["onset_tick"]) * (60 / TICKS_PER_HOUR)
    if state["minutes_elapsed"] >= MIN_HEART_ATTACK_SURVIVAL_MINUTES and not state["heart_stopped"]:
        state["heart_stopped"] = True
        char["health_state"]["active_emergencies"]["cardiac_arrest"] = {
            "severity": 10, "onset_tick": tick, "minutes_elapsed": 0
        }
    if state["heart_stopped"]:
        _tick_cardiac_arrest(char, world)


def _tick_cardiac_arrest(char, world):
    tick = world.get("tick", 0)
    state = char.get("health_state", {}).get("active_emergencies", {}).get("cardiac_arrest")
    if not state:
        return
    state["minutes_elapsed"] = (tick - state["onset_tick"]) * (60 / TICKS_PER_HOUR)
    if state["minutes_elapsed"] >= 4:
        _trigger_death(char, world, "cardiac_arrest")


def resolve_heart_attack(char, world):
    tick = world.get("tick", 0)
    em = char.get("health_state", {}).get("active_emergencies", {})
    ha = em.get("heart_attack", {})
    ca = em.get("cardiac_arrest", {})

    coma_risk = 0.0
    if ca:
        coma_risk = min(0.95, ca.get("minutes_elapsed", 0) * CARDIAC_ARREST_BRAIN_DAMAGE_PER_MIN)
        em.pop("cardiac_arrest", None)
    ha_min = ha.get("minutes_elapsed", 0)
    if ha_min > 8:
        coma_risk = max(coma_risk, (ha_min - 8) * 0.03)
    em.pop("heart_attack", None)

    if random.random() < coma_risk:
        trigger_coma(char, world, "heart_attack_revival", tick)
    else:
        _remember(char, "Survived a heart attack and is recovering.", 0.95,
                  ["health", "heart_attack"], "health", tick)


# ---------------------------------------------------------------------------
# Stroke
# ---------------------------------------------------------------------------

def trigger_stroke(char, world, tick):
    em = char.setdefault("health_state", {}).setdefault("active_emergencies", {})
    em["stroke"] = {"severity": 8, "onset_tick": tick, "checks_failed": 0}
    _remember(char, "Is having a stroke!", 1.0, ["health", "emergency"], "health", tick)


def tick_stroke(char, world):
    tick = world.get("tick", 0)
    state = char.get("health_state", {}).get("active_emergencies", {}).get("stroke")
    if not state:
        return
    if random.random() < STROKE_DISSOLVE_CHANCE_PER_CHECK:
        char["health_state"]["active_emergencies"].pop("stroke", None)
        _remember(char, "Stroke has dissolved. Monitoring for after-effects.", 0.85,
                  ["health", "stroke"], "health", tick)
    else:
        state["checks_failed"] += 1
        existing = char.get("mental_health", [])
        candidates = [t for t in TRAUMA_MENTAL_TRAITS if t not in existing]
        if candidates:
            trait = random.choice(candidates)
            char.setdefault("mental_health", []).append(trait)
            _remember(char, f"Stroke caused {trait.replace('_', ' ')}.", 0.9,
                      ["health", "stroke", "mental_health"], "health", tick)


# ---------------------------------------------------------------------------
# Coma
# ---------------------------------------------------------------------------

def trigger_coma(char, world, cause, tick):
    em = char.setdefault("health_state", {}).setdefault("active_emergencies", {})
    em["coma"] = {"severity": 10, "onset_tick": tick, "weeks_in_coma": 0, "cause": cause}
    char["location"] = "hospital"
    _remember(char, f"Has fallen into a coma ({cause.replace('_', ' ')}).", 1.0,
              ["health", "coma"], "health", tick)


def tick_coma(char, world):
    tick = world.get("tick", 0)
    state = char.get("health_state", {}).get("active_emergencies", {}).get("coma")
    if not state:
        return
    state["weeks_in_coma"] += 1
    weeks = state["weeks_in_coma"]
    if random.random() < COMA_DEATH_RISK_PER_WEEK:
        _trigger_death(char, world, f"coma_week_{weeks}")
        return
    recovery_chance = max(0.05, COMA_RECOVERY_CHANCE_BASE - weeks * 0.02)
    if random.random() < recovery_chance:
        char["health_state"]["active_emergencies"].pop("coma", None)
        if weeks > 2 and random.random() < 0.40:
            existing = char.get("mental_health", [])
            candidates = [t for t in TRAUMA_MENTAL_TRAITS if t not in existing]
            if candidates:
                trait = random.choice(candidates)
                char.setdefault("mental_health", []).append(trait)
                _remember(char, f"Emerged from coma but developed {trait.replace('_', ' ')}.", 0.95,
                          ["health", "coma", "mental_health"], "health", tick)
        else:
            _remember(char, "Emerged from coma and is recovering.", 0.95,
                      ["health", "coma"], "health", tick)


# ---------------------------------------------------------------------------
# Seizure
# ---------------------------------------------------------------------------

def trigger_seizure(char, world, tick):
    em = char.setdefault("health_state", {}).setdefault("active_emergencies", {})
    em["convulsions"] = {"severity": 6, "onset_tick": tick}
    if random.random() < 0.20:
        _apply_head_impact(char, world, 0.45, tick)
    _remember(char, "Had a seizure.", 0.85, ["health", "epilepsy"], "health", tick)


# ---------------------------------------------------------------------------
# Unified per-bodypart injury engine -- replaced apply_blade_injury/
# apply_blunt_trauma/apply_burn_injury (deleted in Round 3 of the
# damage-system rework once all 4 real call sites -- accidents.py,
# hostile_actions.py, emergency.py's tick_fire_incidents, exercise.py's
# injury check -- were migrated to apply_injury() below). This is the
# entry point content authors reach through definitions.json's
# injury_templates/health_hazard_templates chain (Round 1).
# ---------------------------------------------------------------------------

BODY_PARTS = (
    "head", "neck", "chest", "abdomen", "pelvis",
    "left_arm", "right_arm", "left_leg", "right_leg",
)
_CORE_BODY_PARTS = {"head", "neck", "chest", "abdomen", "pelvis"}


def _blank_body_part():
    return {
        "hazards": {},
        "damage_type": None,
        "severity_level": None,
        "functional_status": "normal",
        "injury_template": None,
        "cause": None,
        "tick": None,
        "history": [],
    }


def weighted_pick(options):
    """Rolls a mutually-exclusive {ref, probability} pool (interaction/
    accident -> injury, injury -> body_part) -- a shortfall from 1.0 is an
    implicit 'nothing happens' chance, so this can legitimately return
    None. Shared by accidents.py and hostile_actions.py so the whole
    content chain rolls outcomes identically."""
    roll = random.random()
    cursor = 0.0
    for opt in options:
        cursor += opt.get("probability", 0.0)
        if roll < cursor:
            return opt
    return None


def _functional_status_for(severity_level, hazards):
    """severe + an untreated hazard renders the part unusable until
    treated (the user's explicit spec); medium is usable but impaired;
    low/no hazards is normal."""
    if severity_level == "severe" and any(not h.get("treated") for h in hazards.values()):
        return "unusable"
    if severity_level == "medium":
        return "impaired"
    return "normal"


def apply_injury(char, world, injury_template_key, cause, tick=None):
    """
    Single unified injury entry point. Looks up
    definitions["injury_templates"][injury_template_key] (Round 1
    content), rolls possible_body_parts (mutually exclusive -- one body
    part gets hit) and possible_hazards (independent per-hazard rolls --
    a severe injury can plausibly produce more than one hazard at once,
    e.g. a stab_wound rolling both bleeding_wound AND internal_bleeding),
    writes the target body_parts[part] entry. Returns a small result dict, or None if the
    template/body-part roll didn't resolve to anything.
    """
    if tick is None:
        tick = world.get("tick", 0)
    defs = world.get("definitions", {})
    tmpl = defs.get("injury_templates", {}).get(injury_template_key)
    if not tmpl:
        return None

    part_pick = weighted_pick(tmpl.get("possible_body_parts", []))
    if not part_pick:
        return None
    body_part = part_pick.get("body_part")
    if body_part not in BODY_PARTS:
        return None

    severity_level = tmpl.get("severity_level", "low")
    damage_type = tmpl.get("damage_type")

    hs = char.setdefault("health_state", {})
    bp = hs.setdefault("body_parts", {}).setdefault(body_part, _blank_body_part())
    bp["damage_type"] = damage_type
    bp["severity_level"] = severity_level
    bp["injury_template"] = injury_template_key
    bp["cause"] = cause
    bp["tick"] = tick
    history = bp.setdefault("history", [])
    history.append({"tick": tick, "cause": cause, "severity_level": severity_level, "damage_type": damage_type})
    bp["history"] = history[-3:]

    hazard_registry = defs.get("health_hazard_templates", {})
    for h in tmpl.get("possible_hazards", []):
        if random.random() >= h.get("probability", 0.0):
            continue
        hkey = h.get("hazard_template")
        hazard_tmpl = hazard_registry.get(hkey, {})
        bp["hazards"][hkey] = {
            "tick_applied": tick, "last_ticked": tick, "treated": False,
            "hazard_template": hkey,
        }
        # Bleeding-type hazards feed the existing active_emergencies["bleeding"]/
        # tick_bleeding()/treat_bleeding() pipeline unchanged -- just now
        # populated from the new hazard instead of apply_blade_injury's old
        # bleeding_severity field.
        if hkey in ("bleeding_wound", "internal_bleeding"):
            em = hs.setdefault("active_emergencies", {})
            existing = em.get("bleeding", {})
            rate = hazard_tmpl.get("pain_per_tick", 2) * 0.02
            if hkey == "internal_bleeding":
                rate *= 2  # more serious than any other hazard, regardless of body part
            total_rate = existing.get("blood_loss_rate", 0.0) + rate
            em["bleeding"] = {
                "severity": int(min(10, total_rate * 20)),
                "location": body_part,
                "blood_loss_rate": round(min(1.0, total_rate), 4),
                "hard_to_close": hkey == "internal_bleeding",
            }

    bp["functional_status"] = _functional_status_for(severity_level, bp["hazards"])

    # Severe blunt trauma to the torso / a severe head hit keep the old
    # emergency/mental-trait side effects apply_blunt_trauma used to
    # produce off its own force thresholds -- these are genuinely
    # emergency/mental-trait logic, not hazard-vocabulary data, so they
    # stay small Python branches here rather than becoming registry
    # content.
    if severity_level == "severe" and body_part in ("chest", "abdomen"):
        hs.setdefault("active_emergencies", {})["severe_trauma"] = {
            "severity": 8, "source": injury_template_key
        }
    if severity_level == "severe" and body_part == "head" and random.random() < 0.35:
        _apply_trauma_mental_trait(char, world, tick, "head_trauma")

    _remember(char, f"Sustained a {tmpl.get('name', injury_template_key).lower()} to the {body_part.replace('_', ' ')}.",
              0.85, ["health", "injury", damage_type or "injury"], "health", tick)
    return {"body_part": body_part, "injury_template": injury_template_key, "severity_level": severity_level}


def treat_body_part(char, world, body_part, method="first_aid"):
    """Applies first aid (or any other treatable_by method) to every
    treatable, untreated hazard on one body part -- marks each treated
    (halving its future re-tick escalation, see tick_health_hazards),
    matching the user's "slows down bleeding, doesn't remove it" spec
    rather than an instant cure."""
    hs = char.get("health_state", {})
    bp = hs.get("body_parts", {}).get(body_part)
    if not bp:
        return False
    defs = world.get("definitions", {})
    hazard_registry = defs.get("health_hazard_templates", {})
    treated_any = False
    for hkey, hazard in bp.get("hazards", {}).items():
        if hazard.get("treated"):
            continue
        tmpl = hazard_registry.get(hkey, {})
        if method not in tmpl.get("treatable_by", []):
            continue
        hazard["treated"] = True
        treated_any = True
    if treated_any:
        bp["functional_status"] = _functional_status_for(bp.get("severity_level"), bp.get("hazards", {}))
    return treated_any


def treat_all_by_method(char, world, method):
    """Applies treat_body_part's per-hazard method matching across EVERY
    body part plus health_state.systemic_hazards at once -- decision #13's
    'ambulance' treatable_by value needs to clear every qualifying hazard on
    a patient in one shot (emergency.py::resolve()'s medical responder
    branch), not just one named body part the way first-aid/hospital calls
    already do. Marking a systemic hazard treated also stops
    tick_hazard_manifestations from rolling further episodes for it."""
    hs = char.get("health_state", {})
    treated_any = False
    for body_part in list(hs.get("body_parts", {}).keys()):
        if treat_body_part(char, world, body_part, method=method):
            treated_any = True

    defs = world.get("definitions", {})
    hazard_registry = defs.get("health_hazard_templates", {})
    for hkey, hazard in hs.get("systemic_hazards", {}).items():
        if hazard.get("treated"):
            continue
        tmpl = hazard_registry.get(hkey, {})
        if method not in tmpl.get("treatable_by", []):
            continue
        hazard["treated"] = True
        treated_any = True
    return treated_any


_SEVERITY_LEVEL_LADDER = ("low", "medium", "severe")


def tick_health_hazards(char, world):
    """Over-time hazard escalation ("some will tick over time due to
    defined intervals... the more serious things should push the health
    state to the next level over time until eventually it reaches
    death"). Static hazards (interval_ticks==0) never re-tick and never
    self-heal -- they just sit until treated. Ticking, non-superficial
    hazards step their body part's severity_level up a tier each time
    escalation_per_tick accumulates past 100 (treated hazards escalate
    slower, not not at all); once the aggregate tier reaches critical,
    rolls the same class of death-risk check heart_attack/coma already
    use (generalized, not duplicated)."""
    hs = char.get("health_state")
    if not hs or not hs.get("body_parts"):
        return
    defs = world.get("definitions", {})
    hazard_registry = defs.get("health_hazard_templates", {})
    tick = world.get("tick", 0)
    for part, bp in hs.get("body_parts", {}).items():
        for hkey, hazard in list(bp.get("hazards", {}).items()):
            tmpl = hazard_registry.get(hkey)
            if not tmpl or tmpl.get("interval_ticks", 0) <= 0:
                continue
            interval = tmpl["interval_ticks"]
            last = hazard.get("last_ticked", hazard.get("tick_applied", tick))
            if tick - last < interval:
                continue
            hazard["last_ticked"] = tick
            if tmpl.get("superficial", True):
                continue
            relief_mult = 0.4 if hazard.get("treated") else 1.0
            escalation = tmpl.get("escalation_per_tick", 0) * relief_mult
            if not escalation:
                continue
            hazard["escalation_accum"] = hazard.get("escalation_accum", 0.0) + escalation
            if hazard["escalation_accum"] >= 100.0:
                hazard["escalation_accum"] = 0.0
                current = bp.get("severity_level") or "low"
                idx = _SEVERITY_LEVEL_LADDER.index(current) if current in _SEVERITY_LEVEL_LADDER else 0
                bp["severity_level"] = _SEVERITY_LEVEL_LADDER[min(idx + 1, len(_SEVERITY_LEVEL_LADDER) - 1)]
                bp["functional_status"] = _functional_status_for(bp["severity_level"], bp.get("hazards", {}))
            _, tier = compute_severity(char)
            if tier == "critical":
                death_risk = min(0.02, escalation * 0.002)
                if random.random() < death_risk:
                    _trigger_death(char, world, f"untreated_{hkey}")
                    return


def tick_bleeding(char, world):
    tick = world.get("tick", 0)
    state = char.get("health_state", {}).get("active_emergencies", {}).get("bleeding")
    if not state:
        return
    total = char.get("health_state", {}).setdefault("total_blood_lost", 0.0)
    total += state.get("blood_loss_rate", 0.0)
    char["health_state"]["total_blood_lost"] = total
    if total >= 1.0:
        _trigger_death(char, world, "haemorrhagic_shock")
    elif total > 0.5:
        em = char["health_state"]["active_emergencies"]
        if "unconscious" not in em:
            em["unconscious"] = {"severity": 8, "onset_tick": tick, "cause": "blood_loss"}


def treat_bleeding(char, world, success_rate=0.85):
    if random.random() < success_rate:
        char.get("health_state", {}).get("active_emergencies", {}).pop("bleeding", None)
        _remember(char, "Bleeding controlled.", 0.80,
                  ["health", "injury"], "health", world.get("tick", 0))
        return True
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_trauma_mental_trait(char, world, tick, cause="head_trauma"):
    existing = char.get("mental_health", [])
    candidates = [t for t in TRAUMA_MENTAL_TRAITS if t not in existing]
    if not candidates:
        return None
    trait = random.choice(candidates)
    char.setdefault("mental_health", []).append(trait)
    _remember(char, f"{cause.replace('_', ' ').title()} caused {trait.replace('_', ' ')}.", 0.9,
              ["health", "mental_health", cause], "health", tick)
    return trait


def _apply_head_impact(char, world, force, tick):
    if force >= BLUNT_HEAD_MENTAL_TRAIT_THRESHOLD:
        risk = min(0.90, (force - BLUNT_HEAD_MENTAL_TRAIT_THRESHOLD) * 2.5)
        if random.random() < risk:
            _apply_trauma_mental_trait(char, world, tick, "head_impact")


def _trigger_death(char, world, cause):
    char["alive"] = False
    char["death_cause"] = cause
    char["death_tick"] = world.get("tick", 0)
    _remember(char, f"Died: {cause.replace('_', ' ')}.", 1.0,
              ["death", cause], "health", world.get("tick", 0))


# ---------------------------------------------------------------------------
# Character initialisation
# ---------------------------------------------------------------------------

def init_health_state(char):
    char.setdefault("immune_score", 100.0)
    char.setdefault("physical_health", [])
    char.setdefault("mental_health", [])
    char.setdefault("abnormal_traits", [])
    char.setdefault("phobias", [])
    char.setdefault("fetishes", [])
    char.setdefault("allergies", [])
    char.setdefault("condition_state", {})
    char.setdefault("health_state", {
        "active_emergencies": {},
        "injuries": [],
        "active_symptoms": {},
        "medications_taken": {},
        "total_blood_lost": 0.0
    })
    char.setdefault("alive", True)
    char.setdefault("stamina", 1.0)


def assign_random_traits(char, defs,
                         abnormal_count=(0, 2), phobia_count=(0, 1),
                         fetish_count=(0, 2), allergy_count=(0, 1)):
    """
    Assign random keyword-tag traits from registries at character creation.

    Probability rules:
      problems       — 75% → 0, 25% → 1 or 2 (weighted toward 1)
      natural_talents — 75% → 0, 25% → exactly 1
      abnormal_traits — 0-2 per count_range arg
      phobias, fetishes, allergies — per count_range args
    """
    def pick(registry_key, count_range):
        registry = defs.get(registry_key, [])
        n = random.randint(*count_range)
        return random.sample(registry, min(n, len(registry))) if registry else []

    # problems: 75% none, 20% one, 5% two
    prob_roll = random.random()
    if prob_roll < 0.75:
        n_problems = 0
    elif prob_roll < 0.95:
        n_problems = 1
    else:
        n_problems = 2
    reg_problems = defs.get("problems_registry", [])
    char["problems"] = (random.sample(reg_problems, min(n_problems, len(reg_problems)))
                        if reg_problems else [])

    # natural_talents: 75% none, 25% exactly one
    reg_talents = defs.get("natural_talents_registry", [])
    if random.random() < 0.25 and reg_talents:
        char["natural_talents"] = [random.choice(reg_talents)]
    else:
        char["natural_talents"] = []

    char["abnormal_traits"] = pick("abnormal_traits_registry", abnormal_count)
    char["phobias"]         = pick("phobias_registry",         phobia_count)
    char["fetishes"]        = pick("fetishes_registry",        fetish_count)
    char["allergies"]       = pick("allergies_registry",       allergy_count)


# ---------------------------------------------------------------------------
# Unified severity
# ---------------------------------------------------------------------------
# c["health_state"] (this function's only input) is, per this round's
# research, the one health-adjacent structure that's actually internally
# consistent -- c["health"]/c["physical_health"]/c["body"] each track their
# own independent, non-communicating state. Every existing severity number
# in this codebase (0-10 active_emergencies, 0-1 bleeding_severity/force,
# 0-100 fire incidents, open-ended grievance floats) lives on its own scale;
# this is the first place they get reduced to one comparable number.

_SEVERITY_TIERS = [
    ("healthy",  0,  20),
    ("mild",    20,  40),
    ("moderate",40,  60),
    ("severe",  60,  80),
    ("critical",80, 101),
]


_BODY_PART_SEVERITY_FLOOR = {
    "severe": 65, "medium": 40, "low": 15,
    # Stage/severity escalation (decision #12 of the disease-schema-overhaul
    # round) generalizes this same floor mechanism to accept a
    # health_hazard_templates stages[*].health_state tier name directly --
    # "severe" above already covers both vocabularies (65 stands in for
    # both the legacy severity_level and the new tier name).
    "healthy": 0, "mild": 20, "moderate": 40, "critical": 80,
}


def compute_severity(char):
    """
    Returns (score, tier). score is 0-100, weighted toward the worst single
    signal rather than purely additive -- one severe emergency should
    dominate five mild ones, not average them away. Body-part damage and
    active diseases feed this exactly like active_emergencies always have
    -- this is the character's "overall health state as levels," now
    genuinely computed from the per-bodypart damage/health rework instead
    of the old flat injuries-list breakdown.
    """
    if char.get("alive") is False:
        return 100.0, "dead"

    hs = char.get("health_state", {})
    signals = []

    for em in hs.get("active_emergencies", {}).values():
        signals.append(min(100.0, em.get("severity", 0) * 10))

    for bp in hs.get("body_parts", {}).values():
        sev = bp.get("severity_level")
        if not sev or not bp.get("hazards"):
            continue
        floor = _BODY_PART_SEVERITY_FLOOR.get(sev, 0)
        untreated = any(not h.get("treated") for h in bp["hazards"].values())
        signals.append(floor if untreated else floor * 0.5)

    # Disease-hazard stage escalation (decision #12) -- current_stage holds
    # the resolved health_state tier name directly (see _advance_hazard_stage),
    # injected as a floor signal the same soft way severity_level already is.
    for bp in hs.get("body_parts", {}).values():
        for hz in bp.get("hazards", {}).values():
            stage = hz.get("current_stage")
            if stage:
                signals.append(_BODY_PART_SEVERITY_FLOOR.get(stage, 0))
    for hz in hs.get("systemic_hazards", {}).values():
        stage = hz.get("current_stage")
        if stage:
            signals.append(_BODY_PART_SEVERITY_FLOOR.get(stage, 0))

    for cond_key in char.get("physical_health", []):
        state = char.get("condition_state", {}).get(cond_key, {})
        signals.append(min(100.0, state.get("severity_index", 0.0) * 100))

    blood_lost = hs.get("total_blood_lost", 0.0)
    if blood_lost:
        signals.append(min(100.0, blood_lost * 100))

    if not signals:
        return 0.0, "healthy"

    worst = max(signals)
    avg = sum(signals) / len(signals)
    score = min(100.0, worst * 0.7 + avg * 0.3)

    for tier, lo, hi in _SEVERITY_TIERS:
        if lo <= score < hi:
            return score, tier
    return score, "critical"


# ---------------------------------------------------------------------------
# Real consequences -- posture, movement (via posture), and the 911 bridge.
# This is the actual payoff of the whole severity system: health.py already
# had a fully-working emergency/injury/death engine with zero downstream
# effect (posture.py's unconscious/dead stances had zero call sites; a dead
# character kept thinking and walking normally). This function is where
# that finally changes.
# ---------------------------------------------------------------------------

_MEDICAL_INCIDENT_TIERS = ("severe", "critical")

# "crawling" here is self-healing every tick: an LLM-issued
# stand_up/move while the character's severity tier is still "critical"
# just gets silently overridden back on the very next tick.


def apply_severity_consequences(char, world):
    from systems.posture import set_posture

    if not char.get("alive", True):
        set_posture(char, world, "incapacitated")
        return

    score, tier = compute_severity(char)
    em = char.get("health_state", {}).get("active_emergencies", {})
    body_parts = char.get("health_state", {}).get("body_parts", {})

    # Both legs unusable -> crawling (reuses the existing posture, no new
    # stance needed); both arms unusable -> force-drop whatever's held,
    # since held-item actions get stripped from build_available_actions()
    # once neither arm can hold anything.
    legs_unusable = body_parts and all(
        body_parts.get(leg, {}).get("functional_status") == "unusable"
        for leg in ("left_leg", "right_leg")
    )
    arms_unusable = body_parts and all(
        body_parts.get(arm, {}).get("functional_status") == "unusable"
        for arm in ("left_arm", "right_arm")
    )
    if arms_unusable and char.get("held_item"):
        char["held_item"] = None

    if "unconscious" in em or "coma" in em:
        set_posture(char, world, "incapacitated")
    elif tier == "critical" or legs_unusable:
        set_posture(char, world, "crawling")
    elif char.get("posture") in ("crawling", "incapacitated_pain"):
        # Severity has receded below threshold -- this posture was
        # severity-driven, not a deliberate choice (sitting/lying for
        # other reasons is untouched, since posture won't be "crawling"
        # in that case). "incapacitated_pain" is a retired posture value
        # -- still matched here so any character with that value already
        # saved from before the pain system's removal recovers instead
        # of staying stuck on a value nothing sets anymore.
        set_posture(char, world, "standing")
    elif char.get("posture") == "incapacitated":
        # Recovered from unconscious/coma (still alive, since the alive
        # check above already returned for the dead case) -- there was
        # no revert path for this before "unconscious" and "dead" shared
        # no common posture to revert from.
        set_posture(char, world, "standing")

    if char.get("posture") == "incapacitated" and char.get("travel_state"):
        try:
            from systems.travel import interrupt_travel_for_incapacitation
            interrupt_travel_for_incapacitation(char, world)
        except Exception:
            pass

    needs_medical_report = tier in _MEDICAL_INCIDENT_TIERS
    if needs_medical_report:
        if not char.get("_medical_incident_reported"):
            char["_medical_incident_reported"] = True
            try:
                from systems.emergency import report_medical_emergency_incident
                report_medical_emergency_incident(world, char)
            except Exception:
                pass
    else:
        char["_medical_incident_reported"] = False


# ---------------------------------------------------------------------------
# Main tick entry point
# ---------------------------------------------------------------------------

DEHYDRATION_COUGH_THRESHOLD = 30.0  # body.py's hydration scale, 100=hydrated
DEHYDRATION_COUGH_CHANCE    = 0.05


def _maybe_dehydration_cough(char, world):
    """Coughing "as a result of ... dehydration" per the user's ask --
    smoking-driven coughing is already covered by the existing symptom
    pipeline (_SYMPTOM_REACTION_MAP["coughing"]) whenever smoking
    actually causes a tracked respiratory condition; there's no separate
    standalone smoking-habit field in this codebase to hook a second,
    independent trigger off of."""
    hydration = char.get("body", {}).get("hydration", 100.0)
    if hydration >= DEHYDRATION_COUGH_THRESHOLD:
        return
    if random.random() >= DEHYDRATION_COUGH_CHANCE:
        return
    try:
        from systems.reactions import trigger_reaction
        trigger_reaction(char, world, "cough", tick=world.get("tick", 0))
    except Exception:
        pass


def process_health(char, world):
    apply_severity_consequences(char, world)
    if not char.get("alive", True):
                return
    _maybe_dehydration_cough(char, world)
    tick_health_hazards(char, world)
    tick_hazard_manifestations(char, world)
    tick = world.get("tick", 0)

    if tick % TICKS_PER_DAY == 0:
        tick_immune_score(char, world)
        tick_physical_conditions(char, world)

    if tick % TICKS_PER_WEEK == 0:
        tick_coma(char, world)

    em = char.get("health_state", {}).get("active_emergencies", {})

    if "heart_attack" in em:
        tick_heart_attack(char, world)

    if "stroke" in em and tick % TICKS_PER_HOUR == 0:
        tick_stroke(char, world)

    if "bleeding" in em:
        tick_bleeding(char, world)


# ---------------------------------------------------------------------------
# Legacy shim
# ---------------------------------------------------------------------------

def trigger_health_event(c, world):
    process_health(c, world)


def apply_health_cost(c, world, cost):
    ins = c.get("insurance", {})
    if ins.get("health"):
        cost *= (1 - ins.get("coverage", 0.5))
    h = world.get("households", {}).get(c.get("household_id"))
    if h:
        h["wealth"] -= cost
    return cost
