"""
systems/exercise.py

Exercise system — fitness tracking, body adaptation, injury, personality archetypes.

Personality archetypes (trait):
  exercise_overdoer      — high gain, high injury risk, long recovery gaps
  exercise_consistent    — steady gain, low injury, streak bonuses
  exercise_social_only   — full benefit only with a companion; solo = 35% gain

Fitness model:
  fitness_level (0-1):   cumulative fitness, decays slowly without exercise
  cardio/strength/flexibility_sessions: running totals

Effect on attractiveness (applied in attraction.py):
  General:  fitness_level adds up to +0.12 attractiveness (both sexes)
  Female:   cardio+flexibility → toned body features (thigh, hip nudge)
  Male:     strength → build upgrade toward athletic/stocky-to-athletic path

Injury:
  Base injury chance per session by intensity (1-3):
    intensity 1: 2%, intensity 2: 5%, intensity 3: 10%
  exercise_overdoer triples this.
  Injury cooldown: 3-10 game days (expressed in ticks).
  While injured, complete_exercise_session() returns "injured" with no benefit.

Called from:
  lt_needs.satisfy_lt_need() — passes hobby_id
  sim_loop.tick() via tick_exercise() weekly
"""

import random

from systems.grievances import add_grievance  # noqa — unused here, kept for consistency

# ── Constants ─────────────────────────────────────────────────────────────
TICKS_PER_GAME_HOUR  = 60 * 60          # 1 tick = 1 sec
TICKS_PER_GAME_DAY   = TICKS_PER_GAME_HOUR * 24

FITNESS_GAIN_BASE    = 0.015            # per session, before modifiers
FITNESS_DECAY_DAILY  = 0.003            # per game day without exercise
FITNESS_CAP          = 1.0

ATTRACTIVENESS_FITNESS_BONUS = 0.12     # max bonus at fitness_level = 1.0

# Injury base chance by exercise intensity (1=low, 2=mid, 3=high)
INJURY_CHANCE = {1: 0.02, 2: 0.05, 3: 0.10}
INJURY_COOLDOWN_DAYS_RANGE = (3, 10)    # random game days out


# ── Core API ──────────────────────────────────────────────────────────────

def complete_exercise_session(c, hobby_id, world, has_companion=False):
    """
    Call when a character finishes an exercise hobby session.

    Returns a result dict:
      status: "ok" | "injured" | "skipped_solo"
      fitness_delta: float
      injury_days: int (if injured)
    """
    # Load exercise type from definitions
    try:
        from core.definitions import load_definitions
        defs = load_definitions(world.get("sim_id", "default"))
    except Exception:
        defs = {}

    ex_reg   = defs.get("exercise_type_registry", {})
    ex_entry = ex_reg.get(hobby_id, {"type": "cardio", "intensity": 2, "social": False})
    ex_type  = ex_entry["type"]          # "cardio" | "strength" | "flexibility" |
                                          # ("cardio", "strength") -- a balanced
                                          # calisthenics exercise (sit_ups/chin_ups)
                                          # credits both at half rate, see below.
    ex_types  = list(ex_type) if isinstance(ex_type, (list, tuple)) else [ex_type]
    intensity = ex_entry.get("intensity", 2)
    is_social = ex_entry.get("social", False)

    # Personality trait
    traits = set(c.get("traits", []) + c.get("personality_traits", []))
    is_overdoer    = "exercise_overdoer"    in traits
    is_consistent  = "exercise_consistent"  in traits
    is_social_only = "exercise_social_only" in traits

    fs = c.setdefault("fitness_stats", {
        "fitness_level": 0.30, "cardio_sessions": 0,
        "strength_sessions": 0, "flexibility_sessions": 0,
        "sessions_this_week": 0, "streak_weeks": 0,
        "injury_cooldown": 0, "last_session_tick": 0,
    })

    # Injured check
    if fs.get("injury_cooldown", 0) > 0:
        return {"status": "injured", "fitness_delta": 0.0}

    # Social-only: skip if alone (unless they really have no choice — low chance they go anyway)
    if is_social_only and not has_companion:
        if random.random() > 0.25:   # 75% chance they bail when alone
            return {"status": "skipped_solo", "fitness_delta": 0.0}

    # Gain multiplier
    gain = FITNESS_GAIN_BASE
    if is_overdoer:
        gain *= 1.4
    if is_consistent:
        gain *= 1.1
        if fs.get("streak_weeks", 0) >= 2:
            gain *= (1.0 + 0.05 * min(fs["streak_weeks"], 8))   # streak bonus
    if is_social_only:
        gain *= 1.20 if has_companion else 0.35

    # Apply gain
    old_level = fs.get("fitness_level", 0.30)
    fs["fitness_level"] = round(min(FITNESS_CAP, old_level + gain), 4)
    # Balanced (sit_ups/chin_ups) sessions credit both cardio and strength
    # counters at half rate each rather than one counter at full rate --
    # "more balanced between strength and stamina" per the exercise round.
    credit = 1.0 / len(ex_types)
    for t in ex_types:
        fs[f"{t}_sessions"] = round(fs.get(f"{t}_sessions", 0) + credit, 4)
    fs["sessions_this_week"]  = fs.get("sessions_this_week", 0) + 1
    fs["last_session_tick"]   = world.get("tick", 0)
    delta = round(fs["fitness_level"] - old_level, 4)

    # Apply body feature drift
    _apply_body_adaptation(c, ex_types[0], fs)

    # Apply attractiveness update
    _update_attractiveness(c)

    # Calories burned -- feeds systems/body_composition.py's daily
    # weight-balance model. Scaled by intensity, not by type -- a hard
    # session burns more regardless of what it's building.
    from systems.body_composition import record_calories_burned, EXERCISE_BURN_PER_INTENSITY
    record_calories_burned(c, intensity * EXERCISE_BURN_PER_INTENSITY)

    # Injury check
    inj_chance = INJURY_CHANCE.get(intensity, 0.05)
    if is_overdoer:
        inj_chance *= 3.0
    if is_consistent:
        inj_chance *= 0.3

    result = {"status": "ok", "fitness_delta": delta}
    if random.random() < inj_chance:
        inj_days = random.randint(*INJURY_COOLDOWN_DAYS_RANGE)
        if is_overdoer:
            inj_days = int(inj_days * 2.0)   # overdoers take longer to recover
        fs["injury_cooldown"] = inj_days * TICKS_PER_GAME_DAY
        result["status"]      = "injured"
        result["injury_days"] = inj_days
        # Real injury, not just an activity-blocking cooldown -- always a
        # sprain/strain, never a broken bone or a knockout, matching the
        # "strained_muscle" injury_template exactly (low severity, its own
        # possible_body_parts pool of the 4 limbs -- see health.py::
        # apply_injury, Round 3 of the damage-system rework).
        try:
            from systems.health import apply_injury
            apply_injury(c, world, "strained_muscle", "exercise", tick=world.get("tick", 0))
        except ImportError:
            pass
        # Emit event so simulation can narrate / react
        try:
            from core.event_bus import emit
            emit("character_exercise_injury", {
                "character_id": c["id"],
                "hobby_id":     hobby_id,
                "days_out":     inj_days,
                "tick":         world.get("tick", 0),
            })
        except Exception:
            pass

    return result


def tick_exercise(world):
    """
    Weekly pass: decay fitness, roll over session counters, reduce injury cooldown.
    Call once per game week (from sim_loop weekly bucket).
    """
    chars = world.get("characters", {})
    if isinstance(chars, list):
        chars = {c["id"]: c for c in chars}

    for c in chars.values():
        if c.get("is_offscreen"):
            continue

        fs = c.get("fitness_stats")
        if not fs:
            continue

        # Injury cooldown — tick down by one week's worth
        cooldown = fs.get("injury_cooldown", 0)
        if cooldown > 0:
            fs["injury_cooldown"] = max(0, cooldown - TICKS_PER_GAME_DAY * 7)

        # Fitness decay — proportional to missed sessions
        sessions = fs.get("sessions_this_week", 0)
        if sessions == 0:
            # No exercise this week — decay
            fs["fitness_level"] = round(
                max(0.05, fs.get("fitness_level", 0.30) - FITNESS_DECAY_DAILY * 7), 4
            )
            fs["streak_weeks"] = 0
        else:
            # Had at least one session — maintain or increment streak
            fs["streak_weeks"] = fs.get("streak_weeks", 0) + 1

        # Reset weekly counter
        fs["sessions_this_week"] = 0

        # Re-apply attractiveness (fitness may have decayed)
        _update_attractiveness(c)


# ── Internal helpers ──────────────────────────────────────────────────────

def _apply_body_adaptation(c, ex_type, fs):
    """
    Gradually update body_features based on accumulated exercise type.
    Effects are discrete tier progressions, require significant cumulative sessions.
    """
    sex = c.get("sex", "male")
    bf  = c.setdefault("body_features", {})

    total_cardio      = fs.get("cardio_sessions", 0)
    total_strength    = fs.get("strength_sessions", 0)
    total_flexibility = fs.get("flexibility_sessions", 0)

    if sex == "female":
        # Cardio + flexibility → thigh tones up, hip ratio improves
        combined_tone = total_cardio + total_flexibility
        if combined_tone >= 60 and bf.get("thigh_build") == "full":
            bf["thigh_build"] = "thick"
        elif combined_tone >= 30 and bf.get("thigh_build") == "slim":
            bf["thigh_build"] = "toned"
        elif combined_tone >= 50 and bf.get("thigh_build") in ("slim", "toned"):
            bf["thigh_build"] = "toned"

        # Heavy cardio + yoga combo can shift hip perception (very gradual)
        if total_flexibility >= 40 and bf.get("hip_ratio") == "narrow":
            bf["hip_ratio"] = "average"

    else:
        # Male: strength → build upgrade
        if total_strength >= 80 and bf.get("build") == "slim":
            bf["build"] = "average"
        elif total_strength >= 60 and bf.get("build") == "average":
            bf["build"] = "athletic"
        elif total_strength >= 100 and bf.get("build") == "athletic":
            bf["build"] = "athletic"  # stays athletic, not stocky from fitness
        # Heavy cardio prevents build drifting heavy
        if total_cardio >= 40 and bf.get("build") == "heavy":
            bf["build"] = "stocky"
        if total_cardio >= 80 and bf.get("build") == "stocky":
            bf["build"] = "average"


def _update_attractiveness(c):
    """
    Recalculate the fitness component of attractiveness.
    Stores a fitness_attractiveness_bonus field used by _appearance_score.
    """
    fs = c.get("fitness_stats", {})
    level = fs.get("fitness_level", 0.30)
    # Bonus is sub-linear — early sessions matter most
    bonus = round(ATTRACTIVENESS_FITNESS_BONUS * (level ** 0.7), 4)
    c["fitness_attractiveness_bonus"] = bonus


# ── Context helper ────────────────────────────────────────────────────────

def get_exercise_context(c):
    """LLM-facing summary of fitness state."""
    fs = c.get("fitness_stats", {})
    if not fs:
        return {}

    lines = []
    level = fs.get("fitness_level", 0.30)
    if level >= 0.75:
        lines.append(f"very fit (fitness_level={level:.2f})")
    elif level >= 0.50:
        lines.append(f"moderately fit (fitness_level={level:.2f})")
    elif level < 0.20:
        lines.append(f"unfit / sedentary (fitness_level={level:.2f})")

    if fs.get("injury_cooldown", 0) > 0:
        days = round(fs["injury_cooldown"] / (60 * 60 * 24))
        lines.append(f"currently injured — {days} days until recovered")

    streak = fs.get("streak_weeks", 0)
    if streak >= 4:
        lines.append(f"on a {streak}-week exercise streak")

    return {"fitness": lines} if lines else {}
