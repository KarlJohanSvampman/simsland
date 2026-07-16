"""
health.py -- Comprehensive health simulation system for HoloSims
"""

import random

TICKS_PER_HOUR = 1
TICKS_PER_DAY  = 24
TICKS_PER_WEEK = TICKS_PER_DAY * 7

MIN_HEART_ATTACK_SURVIVAL_MINUTES = 15
CARDIAC_ARREST_BRAIN_DAMAGE_PER_MIN = 0.08
STROKE_DISSOLVE_CHANCE_PER_CHECK    = 0.20
COMA_RECOVERY_CHANCE_BASE           = 0.25
COMA_DEATH_RISK_PER_WEEK            = 0.05

BLUNT_BONE_BREAK_THRESHOLD        = 0.55
BLUNT_LUNG_DAMAGE_THRESHOLD       = 0.70
BLUNT_UNCONSCIOUS_THRESHOLD       = 0.65
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

        for symptom_key in tmpl.get("active_symptoms", []):
            _apply_symptom_penalties(char, world, symptom_key, defs)
            tick_symptom_reactions(char, world, defs, symptom_key, state["severity_index"])

        sp = tmpl.get("stamina_penalty", 0)
        if sp:
            char["stamina"] = max(0.0, char.get("stamina", 1.0) - sp * 0.01)

    _check_recoveries(char, world, ph_templates, tick)


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


def _apply_symptom_penalties(char, world, symptom_key, defs):
    """need_penalties keys (authored on symptom_templates, 0-1 scale) don't
    correspond to any top-level character field -- route each to its real
    home: hunger/hygiene live in c["body"] (0-100 scale), energy has no
    dedicated field so it feeds the inverse (fatigue), and fun/social are
    long-term-need satisfaction, tracked as frustration in c["lt_needs"]."""
    tmpl = defs.get("symptom_templates", {}).get(symptom_key, {})
    b  = char.setdefault("body", {})
    lt = char.get("lt_needs", {})
    for need, amount in tmpl.get("need_penalties", {}).items():
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
}


def tick_symptom_reactions(char, world, defs, symptom_key, severity_index):
    """
    One active symptom's contribution to the unified pain field (see
    add_pain() above) and, for the symptoms with a clean visual cue, a
    real observable reaction. Called from tick_physical_conditions()'s
    existing per-condition loop -- same daily cadence, no new cadence
    machinery. severity_index (0-1, already tracked per-condition) scales
    the pain contribution: a mild new cold barely hurts, a progressed one
    does.
    """
    tmpl = defs.get("symptom_templates", {}).get(symptom_key)
    if not tmpl:
        return

    add_pain(char, 2 + severity_index * 6)

    if not tmpl.get("visual"):
        return
    reaction_type = _SYMPTOM_REACTION_MAP.get(symptom_key)
    if not reaction_type:
        return
    try:
        from systems.reactions import push_reaction
        push_reaction(char, reaction_type, world.get("tick", 0))
    except Exception:
        pass


def _check_recoveries(char, world, ph_templates, tick):
    for cond_key in list(char.get("physical_health", [])):
        tmpl = ph_templates.get(cond_key, {})
        if not (tmpl.get("curable") and not tmpl.get("progressive")):
            continue
        state = char.setdefault("condition_state", {}).get(cond_key, {})
        days = state.get("days_elapsed", 0)
        duration = tmpl.get("typical_duration_days", 7)
        meds = char.get("health_state", {}).get("medications_taken", {})
        treated = any(m in meds for m in tmpl.get("medicine", []))
        # A weaker/older character (higher immune_modifier) takes longer to
        # shake off a condition even when treated.
        required = duration * (0.6 if treated else 1.0) * immune_modifier(char)
        if days >= required:
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
# Physical injury: blunt trauma
# ---------------------------------------------------------------------------

def apply_blunt_trauma(char, world, body_part, force_normalized, tick):
    injuries = char.setdefault("health_state", {}).setdefault("injuries", [])
    effects = {}

    if force_normalized >= BLUNT_BONE_BREAK_THRESHOLD:
        effects["broken_bone"] = True
        effects["bone_location"] = body_part
        _remember(char, f"Broke {body_part.replace('_', ' ')}.", 0.9,
                  ["health", "injury"], "health", tick)

    if force_normalized >= BLUNT_LUNG_DAMAGE_THRESHOLD and body_part in ("torso", "chest", "back"):
        effects["lung_damage"] = True
        char.setdefault("health_state", {}).setdefault("active_emergencies", {})["agonizing_pain"] = {
            "severity": 8, "source": "lung_damage"
        }

    if force_normalized >= BLUNT_UNCONSCIOUS_THRESHOLD:
        effects["unconscious"] = True
        char["health_state"]["active_emergencies"]["unconscious"] = {
            "severity": 7, "onset_tick": tick, "cause": "blunt_trauma"
        }

    if body_part in ("head", "skull", "face"):
        effects["head_impact"] = True
        if force_normalized >= BLUNT_HEAD_MENTAL_TRAIT_THRESHOLD:
            risk = min(0.90, (force_normalized - BLUNT_HEAD_MENTAL_TRAIT_THRESHOLD) * 2.5)
            effects["mental_trait_risk"] = risk
            if random.random() < risk:
                _apply_trauma_mental_trait(char, world, tick, "head_trauma")

    injury = {"type": "blunt", "body_part": body_part,
              "force": force_normalized, "tick": tick, "effects": effects}
    injuries.append(injury)
    add_pain(char, force_normalized * 40)
    return injury


# ---------------------------------------------------------------------------
# Physical injury: blade
# ---------------------------------------------------------------------------

def apply_blade_injury(char, world, body_part, sharpness, size, irregular_shape, tick):
    bleeding_base = sharpness * 0.5 + size * 0.5
    complexity_mult = 1.5 if irregular_shape else 1.0
    bleeding_severity = min(1.0, bleeding_base * complexity_mult)
    hard_to_close = irregular_shape and sharpness < 0.5

    injuries = char.setdefault("health_state", {}).setdefault("injuries", [])
    injury = {
        "type": "blade", "body_part": body_part, "tick": tick,
        "blade_sharpness": sharpness, "blade_size": size,
        "irregular_shape": irregular_shape,
        "bleeding_severity": round(bleeding_severity, 3),
        "hard_to_close": hard_to_close
    }
    injuries.append(injury)

    if bleeding_severity > 0.1:
        em = char.setdefault("health_state", {}).setdefault("active_emergencies", {})
        existing = em.get("bleeding", {})
        total_rate = existing.get("blood_loss_rate", 0.0) + bleeding_severity * 0.05
        em["bleeding"] = {
            "severity": int(bleeding_severity * 10),
            "location": body_part,
            "blood_loss_rate": round(min(1.0, total_rate), 4),
            "hard_to_close": hard_to_close
        }

    _remember(char, f"Sustained blade injury to {body_part.replace('_', ' ')}.", 0.85,
              ["health", "injury", "blade"], "health", tick)
    add_pain(char, bleeding_severity * 40)
    return injury


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
# Unified pain -- health_state["pain"], 0-100. Consolidates what were three
# disconnected trackers (c["body"]["pain"], never written by anything;
# c["health"]["pain"], written additively by domestic_control.py/
# impulse.py/rival_cascade.py, never decayed, never read anywhere; nothing
# in health_state at all). This is now the one real pain field -- fed by
# violence (below), redirected domestic-abuse/rivalry pain (see those
# files), and symptoms (tick_symptom_reactions below). Accidents are a
# documented future fourth source -- no accident-injury mechanic exists
# yet anywhere in this codebase; whatever adds one just calls add_pain()
# the same way.
# ---------------------------------------------------------------------------

PAIN_DECAY_PER_TICK = 0.15


def add_pain(char, amount):
    hs = char.setdefault("health_state", {})
    hs["pain"] = max(0.0, min(100.0, hs.get("pain", 0.0) + amount))


def _decay_pain(char):
    hs = char.get("health_state")
    if not hs or not hs.get("pain"):
        return
    hs["pain"] = max(0.0, hs["pain"] - PAIN_DECAY_PER_TICK)


def apply_body_neglect_pain(char, world):
    """Continuous pain contribution from severely neglected physical needs
    (starvation cramps, dehydration headache, exhaustion). Proportional to
    how far past threshold the need is; naturally self-corrects once the
    need is met, same as the symptom-reaction pain contribution."""
    b = char.get("body", {})
    hunger = b.get("hunger", 0)
    if hunger > 85:
        add_pain(char, (hunger - 85) / 15 * 3)
    hydration = b.get("hydration", 100)
    if hydration < 20:
        add_pain(char, (20 - hydration) / 20 * 4)
    sleep_debt = b.get("sleep_debt", 0)
    if sleep_debt > 75:
        add_pain(char, (sleep_debt - 75) / 25 * 2)


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


def compute_severity(char):
    """
    Returns (score, tier). score is 0-100, weighted toward the worst single
    signal rather than purely additive -- one severe emergency should
    dominate five mild ones, not average them away.
    """
    if not char.get("alive", True):
        return 100.0, "dead"

    hs = char.get("health_state", {})
    signals = []

    for em in hs.get("active_emergencies", {}).values():
        signals.append(min(100.0, em.get("severity", 0) * 10))

    for inj in hs.get("injuries", []):
        if inj.get("type") == "blade":
            signals.append(min(100.0, inj.get("bleeding_severity", 0) * 100))
        elif inj.get("type") == "blunt":
            signals.append(min(100.0, inj.get("force", 0) * 100))

    blood_lost = hs.get("total_blood_lost", 0.0)
    if blood_lost:
        signals.append(min(100.0, blood_lost * 100))

    pain = hs.get("pain", 0.0)
    if pain:
        signals.append(min(100.0, pain))

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


def apply_severity_consequences(char, world):
    from systems.posture import set_posture

    if not char.get("alive", True):
        set_posture(char, world, "incapacitated")
        return

    score, tier = compute_severity(char)
    em = char.get("health_state", {}).get("active_emergencies", {})

    if "unconscious" in em or "coma" in em:
        set_posture(char, world, "incapacitated")
    elif tier == "critical":
        set_posture(char, world, "crawling")
    elif char.get("posture") == "crawling":
        # Severity has receded below critical -- this posture was
        # severity-driven, not a deliberate choice (sitting/lying for
        # other reasons is untouched, since posture won't be "crawling"
        # in that case).
        set_posture(char, world, "standing")
    elif char.get("posture") == "incapacitated":
        # Recovered from unconscious/coma (still alive, since the alive
        # check above already returned for the dead case) -- there was
        # no revert path for this before "unconscious" and "dead" shared
        # no common posture to revert from.
        set_posture(char, world, "standing")

    if tier in _MEDICAL_INCIDENT_TIERS:
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

def process_health(char, world):
    apply_severity_consequences(char, world)
    if not char.get("alive", True):
                return
    _decay_pain(char)
    apply_body_neglect_pain(char, world)
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
