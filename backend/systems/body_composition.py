"""
systems/body_composition.py

Dynamic weight/body-fat state, driven by a simple daily calorie-balance
model: food eaten (body.py::on_eat_complete) vs. a baseline daily burn
plus whatever exercise.py::complete_exercise_session() burned that day.

body_fat_level (0-1, "how slim" trait) is the one new piece of state.
"How fit/strong" deliberately reuses the pre-existing
fitness_stats.fitness_level (systems/exercise.py) rather than adding a
parallel field -- it already leans toward strength via strength_sessions
and already drives attractiveness.

The daily tick doesn't invent new health/attractiveness machinery -- it
dynamically adds/removes the same obese/underweight/high_stamina/
low_stamina physical_traits that character_gen.py already rolls once,
statically, at creation. health.py's _TRAIT_IMMUNE_DELTAS already reads
those exact trait strings, so making them live (instead of a one-time
random roll) is what actually wires weight into the immune system --
zero changes needed in health.py.
"""

BODY_FAT_DEFAULT       = 0.35
BODY_FAT_MIN           = 0.05
BODY_FAT_MAX           = 0.95

OBESE_THRESHOLD         = 0.70
UNDERWEIGHT_THRESHOLD   = 0.15
HIGH_STAMINA_THRESHOLD  = 0.70   # fitness_stats.fitness_level
LOW_STAMINA_THRESHOLD   = 0.15

BASELINE_DAILY_BURN     = 100.0  # abstract calorie units, not real kcal
CALORIE_SCALE           = 60.0   # nutrition (0-1) -> calories_in per meal
EXERCISE_BURN_PER_INTENSITY = 20.0
NET_THRESHOLD           = 20.0   # surplus/deficit must exceed this to matter
DAILY_STEP              = 0.02   # max body_fat_level change per day


def ensure_body_composition(c):
    """Lazy default, same pattern as body.py::ensure_body. Seeds
    body_fat_level from the character's existing static obese/
    underweight physical_traits (character_gen.py's one-time random
    roll) so the new dynamic system starts in agreement with whatever
    was already rolled, instead of fighting it."""
    if "body_composition" in c:
        return c["body_composition"]

    traits = c.get("physical_traits", [])
    if "obese" in traits:
        start = 0.75
    elif "underweight" in traits:
        start = 0.15
    else:
        start = BODY_FAT_DEFAULT

    c["body_composition"] = {
        "body_fat_level":       start,
        "calories_in_today":    0.0,
        "calories_burned_today": 0.0,
    }
    return c["body_composition"]


def record_calories_in(c, nutrition):
    bc = ensure_body_composition(c)
    bc["calories_in_today"] += max(0.0, nutrition) * CALORIE_SCALE


def record_calories_burned(c, amount):
    bc = ensure_body_composition(c)
    bc["calories_burned_today"] += max(0.0, amount)


def _sync_dynamic_trait(c, trait, should_have):
    traits = c.setdefault("physical_traits", [])
    has = trait in traits
    if should_have and not has:
        traits.append(trait)
    elif not should_have and has:
        traits.remove(trait)


def tick_body_composition(world):
    """Daily cadence (see CADENCE['body_composition'], sim_loop.py)."""
    for c in world.get("characters", {}).values():
        bc = ensure_body_composition(c)

        net = bc["calories_in_today"] - BASELINE_DAILY_BURN - bc["calories_burned_today"]
        if net > NET_THRESHOLD:
            bc["body_fat_level"] = min(BODY_FAT_MAX, bc["body_fat_level"] + DAILY_STEP)
        elif net < -NET_THRESHOLD:
            bc["body_fat_level"] = max(BODY_FAT_MIN, bc["body_fat_level"] - DAILY_STEP)

        bc["calories_in_today"] = 0.0
        bc["calories_burned_today"] = 0.0

        _sync_dynamic_trait(c, "obese", bc["body_fat_level"] >= OBESE_THRESHOLD)
        _sync_dynamic_trait(c, "underweight", bc["body_fat_level"] <= UNDERWEIGHT_THRESHOLD)

        fitness_level = c.get("fitness_stats", {}).get("fitness_level", 0.30)
        _sync_dynamic_trait(c, "high_stamina", fitness_level >= HIGH_STAMINA_THRESHOLD)
        _sync_dynamic_trait(c, "low_stamina", fitness_level <= LOW_STAMINA_THRESHOLD)


def get_body_composition_context(c):
    """LLM-facing summary -- self-conscious framing at the extremes,
    mirroring exercise.py::get_exercise_context()'s shape."""
    bc = c.get("body_composition")
    if not bc:
        return {}

    lines = []
    level = bc["body_fat_level"]
    if level >= OBESE_THRESHOLD:
        lines.append(
            "You've noticed you've put on a lot of weight lately and feel "
            "low on energy and unmotivated to be active."
        )
    elif level >= 0.55:
        lines.append("You've been gaining a bit of weight lately.")
    elif level <= UNDERWEIGHT_THRESHOLD:
        lines.append("You're noticeably underweight and feel physically weak.")
    elif level <= 0.25:
        lines.append("You're quite slim.")

    return {"body_composition": lines} if lines else {}
