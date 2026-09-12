"""
systems/contested_checks.py

A general, data-driven check engine for any action that tries to
influence/impress someone, infringe on their freedom by force, or
manipulate them -- replaces nervosity.py's solo-only difficulty model
(kept as a thin compatibility wrapper below) with a real two-sided
test wherever a target exists.

The algebra (exactly as specified):

    actor_score   = roll() + sum(actor_characteristic[i].value * weight[i])
                            + sum(actor_trait_bonus[tag] for tag the actor has)
    actor_margin  = actor_score - threshold

A SOLO check (no real target, or the action's own definition has no
"defender_characteristics"/"defender_trait_bonuses" entries) stops here:
    success = actor_margin >= 0

An OPPOSED check (a real target exists) turns that margin into the
target's own difficulty, which the target's own characteristics/traits
can further raise or lower, then the target rolls against it -- a real
test on BOTH sides, not just the actor's:

    defender_difficulty = clamp(actor_margin
                               + sum(defender_characteristic[i].value * weight[i])
                               + sum(defender_trait_bonus[tag] for tag the defender has),
                               0.05, 0.95)
    defender_roll = roll()
    resisted      = defender_roll >= defender_difficulty
    landed        = not resisted

CHECK_DEFINITIONS is the "flexible format" this was asked for -- one
entry per action (or shared action family) declares which
characteristics feed each side's roll (with a weight/sign -- positive
helps, negative hurts) and which trait tags grant a flat bonus/penalty
to each side. Adding a new checkable action is pure data, no new code,
as long as it can be expressed with the existing CHARACTERISTIC_FNS
vocabulary below (extend that table first if a new action needs a
genuinely new stat).
"""

import random

DIFFICULTY_FLOOR = 0.05
DIFFICULTY_CEIL = 0.95


def _traits(c):
    return set(c.get("traits", []) + c.get("personality_traits", []))


def _rel(c, other):
    if not other:
        return {}
    return c.get("relationships", {}).get(other.get("id"), {})


# Continuous, roughly-0-1 stats a check can weight -- each fn takes
# (self_char, other_char_or_None, world_or_None) so relationship-scoped
# characteristics (familiarity, standing hostility, ...) work the same
# way as purely-self ones (stress, fitness, ...).
CHARACTERISTIC_FNS = {
    "stress":       lambda c, other, world: c.get("stress", 0) / 100.0,
    "fitness":      lambda c, other, world: c.get("fitness_stats", {}).get("fitness_level", 0.3),
    "familiarity":  lambda c, other, world: _rel(c, other).get("familiarity", 0) / 100.0,
    "trust":        lambda c, other, world: _rel(c, other).get("trust", 0) / 100.0,
    "jealousy":     lambda c, other, world: _rel(c, other).get("jealousy", 0) / 100.0,
}


def _characteristic_value(name, char, other, world):
    # "ability:<id>" is resolved dynamically against whatever
    # ability_templates the current definitions actually declare
    # (systems/abilities.py) rather than needing a hardcoded entry per
    # ability here -- a new ability template is usable in a
    # CHECK_DEFINITIONS weighting immediately, no code change.
    if name.startswith("ability:") and world is not None:
        from systems.abilities import ability_characteristic_value
        return ability_characteristic_value(char, name.split(":", 1)[1], world)
    fn = CHARACTERISTIC_FNS.get(name)
    return fn(char, other, world) if fn else 0.0


def _weighted_sum(char, other, world, characteristics):
    total = 0.0
    for name, weight in (characteristics or {}).items():
        total += _characteristic_value(name, char, other, world) * weight
    return total


def _trait_sum(char, trait_bonuses):
    traits = _traits(char)
    return sum(bonus for tag, bonus in (trait_bonuses or {}).items() if tag in traits)


# One entry per checkable action -- see module docstring for the shape.
# Weights/bonuses deliberately modest (~0.1-0.3) so no single stat or
# trait dominates the roll; threshold sets the action's own baseline
# difficulty before any modifiers.
#
# Sign convention (easy to get backwards -- confirmed live, fixed once
# already): defender_difficulty feeds `resisted = defender_roll >=
# defender_difficulty` with defender_roll ~ Uniform(0,1). LOWER
# difficulty means a wider range of rolls clear it, so P(resisted) is
# HIGHER -- good for the defender. That means any characteristic/trait
# that HELPS the defender resist (confident, stubborn, resilient, fit,
# suspicious of manipulation, ...) must be a NEGATIVE contribution, and
# anything that makes them MORE vulnerable (nervous, trusting the
# manipulator, familiar with the guilt-tripper, ...) must be POSITIVE.
CHECK_DEFINITIONS = {
    # ---- influence / impress (formerly nervosity.py's solo checks) ----
    "make_argument": {
        "threshold": 0.35,
        "actor_characteristics":    {"stress": -0.35},
        "actor_trait_bonuses":      {"confident": 0.15, "charismatic": 0.15, "manipulative": 0.10, "nervous": -0.20},
        "defender_characteristics": {"trust": 0.15},    # trusting the arguer makes you easier to move
        "defender_trait_bonuses":  {"stubborn": -0.20, "confident": -0.15, "suspicious": -0.10},
    },
    "guilt_trip": {
        "threshold": 0.45,
        "actor_characteristics":    {"stress": -0.30},
        "actor_trait_bonuses":      {"manipulative": 0.25, "charismatic": 0.10, "nervous": -0.15},
        "defender_characteristics": {"familiarity": 0.10},  # closer people can guilt you more easily
        "defender_trait_bonuses":  {"confident": -0.20, "stubborn": -0.15, "forgiving": -0.10, "suspicious": -0.15},
    },
    "compliment": {
        "threshold": 0.25,
        "actor_characteristics":    {"stress": -0.25},
        "actor_trait_bonuses":      {"confident": 0.15, "charismatic": 0.20, "nervous": -0.20},
        "defender_characteristics": {},
        "defender_trait_bonuses":  {"suspicious": -0.20, "confident": -0.10},
    },
    "flirt": {
        "threshold": 0.30,
        "actor_characteristics":    {"stress": -0.30},
        "actor_trait_bonuses":      {"confident": 0.20, "charismatic": 0.20, "nervous": -0.25},
        "defender_characteristics": {},
        "defender_trait_bonuses":  {"suspicious": -0.15},
    },
    "joke": {
        "threshold": 0.20,
        "actor_characteristics":    {"stress": -0.20},
        "actor_trait_bonuses":      {"confident": 0.10, "charismatic": 0.15, "nervous": -0.15},
        "defender_characteristics": {},
        "defender_trait_bonuses":  {},
    },

    # ---- force / infringing on another sim's freedom ----
    "punch":       {"threshold": 0.45, "actor_characteristics": {"fitness": 0.30}, "actor_trait_bonuses": {"aggressive": 0.15},
                     "defender_characteristics": {"fitness": -0.30}, "defender_trait_bonuses": {"resilient": -0.15, "nervous": 0.15}},
    "kick":        {"threshold": 0.45, "actor_characteristics": {"fitness": 0.30}, "actor_trait_bonuses": {"aggressive": 0.15},
                     "defender_characteristics": {"fitness": -0.30}, "defender_trait_bonuses": {"resilient": -0.15, "nervous": 0.15}},
    "shove":       {"threshold": 0.35, "actor_characteristics": {"fitness": 0.25}, "actor_trait_bonuses": {"aggressive": 0.15},
                     "defender_characteristics": {"fitness": -0.25}, "defender_trait_bonuses": {"resilient": -0.10}},
    "grab_offensive": {"threshold": 0.40, "actor_characteristics": {"fitness": 0.25}, "actor_trait_bonuses": {"aggressive": 0.15},
                     "defender_characteristics": {"fitness": -0.25}, "defender_trait_bonuses": {"resilient": -0.10}},
    "hold":        {"threshold": 0.45, "actor_characteristics": {"fitness": 0.30}, "actor_trait_bonuses": {"aggressive": 0.15},
                     "defender_characteristics": {"fitness": -0.30}, "defender_trait_bonuses": {"resilient": -0.15}},
    "wrestle":     {"threshold": 0.45, "actor_characteristics": {"fitness": 0.30}, "actor_trait_bonuses": {"aggressive": 0.10},
                     "defender_characteristics": {"fitness": -0.30}, "defender_trait_bonuses": {"resilient": -0.15}},
    "threaten": {
        "threshold": 0.40,
        "actor_characteristics":    {"stress": -0.15, "fitness": 0.15},
        "actor_trait_bonuses":      {"aggressive": 0.20, "manipulative": 0.10},
        "defender_characteristics": {},
        "defender_trait_bonuses":  {"confident": -0.20, "resilient": -0.15, "nervous": 0.25},
    },

    # ---- ability-trained actions (systems/abilities.py) -- solo checks,
    # no target. "ability:<id>" is resolved dynamically against whatever
    # ability_templates declare that id, not hardcoded per ability here.
    "practice_juggling": {
        "threshold": 0.40,
        "actor_characteristics": {"ability:juggling": 0.6, "stress": -0.10},
        "actor_trait_bonuses":   {},
    },
    "cook_meal": {
        "threshold": 0.35,
        "actor_characteristics": {"ability:cooking": 0.6, "stress": -0.10},
        "actor_trait_bonuses":   {},
    },
}


def resolve_check(action_type, actor, defender=None, world=None,
                   extra_actor_mod=0.0, extra_defender_mod=0.0):
    """Runs the check described in the module docstring. Returns
    {"success", "opposed", "actor_margin", "defender_difficulty"} --
    defender_difficulty is None for a solo check. `success` means "the
    actor's action lands"/"the actor's check passes"; for an opposed
    check that's the inverse of the defender resisting.

    extra_actor_mod/extra_defender_mod: one-off situational adjustments
    a caller can pass (e.g. a held weapon, a surprise bonus) without
    needing a whole new CHECK_DEFINITIONS entry for that combination."""
    cfg = CHECK_DEFINITIONS.get(action_type)
    if not cfg:
        return None

    actor_score = (
        random.random()
        + _weighted_sum(actor, defender, world, cfg.get("actor_characteristics"))
        + _trait_sum(actor, cfg.get("actor_trait_bonuses"))
        + extra_actor_mod
    )
    actor_margin = actor_score - cfg.get("threshold", 0.5)

    is_opposed = defender is not None and (
        cfg.get("defender_characteristics") is not None or cfg.get("defender_trait_bonuses") is not None
    )
    if not is_opposed:
        return {"success": actor_margin >= 0, "opposed": False, "actor_margin": actor_margin, "defender_difficulty": None}

    defender_difficulty = (
        actor_margin
        + _weighted_sum(defender, actor, world, cfg.get("defender_characteristics"))
        + _trait_sum(defender, cfg.get("defender_trait_bonuses"))
        + extra_defender_mod
    )
    defender_difficulty = max(DIFFICULTY_FLOOR, min(DIFFICULTY_CEIL, defender_difficulty))

    defender_roll = random.random()
    resisted = defender_roll >= defender_difficulty
    return {
        "success": not resisted,
        "opposed": True,
        "actor_margin": actor_margin,
        "defender_difficulty": defender_difficulty,
        "resisted": resisted,
    }
