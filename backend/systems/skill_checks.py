"""
systems/skill_checks.py

A d100 roll-under-difficulty skill-check engine -- deliberately separate
from systems/contested_checks.py, which keeps its own continuous
roll+threshold math for force/influence/manipulation checks untouched.
This engine is for skill/ability-gated actions and competitive
performances (singing karaoke to an audience, cooking a meal, ...).

Difficulty semantics (stated explicitly -- contested_checks.py's own
sign-convention bug is exactly the mistake this is trying to avoid
repeating): `difficulty` IS the target number you want to roll AT OR
UNDER out of 100 -- higher difficulty means EASIER (it doubles as an
effective success percentage). A skill-level bonus therefore RAISES the
difficulty number; a trait penalty LOWERS it. Final difficulty is always
clamped to [1, 99] so nothing is a guaranteed success or a mathematical
impossibility.

A "skill_check" spec lives directly on the action's own
action_registry.py::ACTION_SPECS entry or the activity's own
activities.py::ACTIVITIES entry (whichever declares that action/activity
id -- the two registries are mutually exclusive today), shaped:

    "skill_check": {
        "requiresSkill": True,        # False = no skill at all; difficulty
                                       # is just base + trait modifiers
        "skill": "juggling",          # ability_templates id (only if requiresSkill)
        "minProficiencyLevel": None,  # optional hard gate -- reuses
                                       # abilities.py::meets_requirement()
        "baseDifficulty": 40,         # 1-99, the challenge's own baseline
        "competitive": False,         # True = one or more targets also roll
        "targetBaseDifficulty": 50,   # optional, competitive only (default 50)
    }

Trait modifiers (both on the ability_templates entry itself, e.g.
`"trait_modifiers": [{"trait": "clumsy", "modifier": -15}]`) apply
against the UNION of c["traits"], c["personality_traits"], AND
c["physical_traits"] -- the last one is the "physical" half of
"physical or cognitive" traits; the first two already cover "cognitive"
(personality/mental) ones.
"""

import random

DIFFICULTY_FLOOR = 1
DIFFICULTY_CEIL = 99
DEFAULT_TARGET_BASE_DIFFICULTY = 50

# Mirrors reading_process.py::MAX_DEBATE_PARTICIPANTS's exact role --
# bounds how many simultaneous per-target rolls/reactions a single
# competitive check can fan out to, same reasoning as that existing cap
# (a shout in a crowded room shouldn't stampede everyone).
MAX_SKILL_CHECK_AUDIENCE = 4


def _ability_templates(world):
    return (world.get("definitions", {}) or {}).get("ability_templates", {})


def _character_traits(c):
    """Union of physical AND cognitive/personality traits -- the
    concrete meaning of the user's "physical or cognitive" framing.
    c["physical_traits"] is a real, separate array from c["traits"]/
    c["personality_traits"] (confirmed via api/editor.py's spawn-
    override handling)."""
    return set(
        c.get("traits", [])
        + c.get("personality_traits", [])
        + c.get("physical_traits", [])
    )


def _trait_modifier_sum(c, trait_modifiers):
    """trait_modifiers: [{"trait": <id>, "modifier": <signed int>}, ...]"""
    if not trait_modifiers:
        return 0
    traits = _character_traits(c)
    return sum(
        entry.get("modifier", 0)
        for entry in trait_modifiers
        if entry.get("trait") in traits
    )


def get_skill_check_spec(action_type, world):
    """Looks up the "skill_check" sub-object from whichever registry
    declares this action/activity type. action_registry.py's
    ACTION_SPECS and activities.py's ACTIVITIES are mutually exclusive
    today (confirmed: cook_meal exists only in the latter,
    practice_juggling only in the former), so checking both in sequence
    is safe -- neither currently defines the same id as the other."""
    from systems.action_registry import ACTION_SPECS
    from systems.activities import ACTIVITIES

    spec = ACTION_SPECS.get(action_type) or ACTIVITIES.get(action_type) or {}
    return spec.get("skill_check")


def roll_d100():
    return random.randint(1, 100)


def compute_difficulty(actor, spec, world, extra_modifier=0):
    """Assembles the actor's own effective difficulty: base (from the
    action/activity's own spec) + current skill-level bonus (only if
    this check requires a skill) + trait modifier sum (from that
    skill's own ability_templates entry) + any one-off situational
    adjustment the caller supplies."""
    base = spec.get("baseDifficulty", 50)
    level_bonus = 0
    trait_bonus = 0

    if spec.get("requiresSkill"):
        skill_id = spec.get("skill")
        tmpl = _ability_templates(world).get(skill_id, {})
        levels = tmpl.get("proficiency_levels", [])
        if levels:
            from systems.abilities import get_level_index
            idx = get_level_index(actor, skill_id, world)
            level_bonus = levels[idx].get("bonus", 0)
        trait_bonus = _trait_modifier_sum(actor, tmpl.get("trait_modifiers"))

    difficulty = base + level_bonus + trait_bonus + extra_modifier
    return max(DIFFICULTY_FLOOR, min(DIFFICULTY_CEIL, difficulty))


def resolve_skill_check(action_type, actor, world, targets=None,
                         extra_actor_modifier=0, extra_target_modifier=0):
    """Runs the check described in the module docstring. Returns
    {"success", "difficulty", "roll", "actor_margin", "competitive",
    "target_results": [...]} -- target_results is empty for a solo
    check. Returns {"blocked": True, "reason": "insufficient_proficiency"}
    if a minProficiencyLevel gate fails (the character never even
    attempts it). Returns None if action_type has no skill_check spec
    at all.

    actor_margin = actor's difficulty - actor's roll (always >= 0 on a
    success, since success means roll <= difficulty) -- callers pass
    this into abilities.py::record_attempt()'s `margin=` parameter so a
    spectacular success trains the skill faster than a razor-thin one."""
    spec = get_skill_check_spec(action_type, world)
    if not spec:
        return None

    if spec.get("requiresSkill") and spec.get("minProficiencyLevel"):
        from systems.abilities import meets_requirement
        if not meets_requirement(actor, spec["skill"], spec["minProficiencyLevel"], world):
            return {"blocked": True, "reason": "insufficient_proficiency"}

    actor_difficulty = compute_difficulty(actor, spec, world, extra_actor_modifier)
    actor_roll = roll_d100()
    actor_success = actor_roll <= actor_difficulty
    actor_margin = max(0, actor_difficulty - actor_roll)

    result = {
        "success": actor_success,
        "difficulty": actor_difficulty,
        "roll": actor_roll,
        "actor_margin": actor_margin,
        "competitive": bool(spec.get("competitive")),
        "target_results": [],
    }

    if not spec.get("competitive") or not targets:
        return result

    target_base = spec.get("targetBaseDifficulty", DEFAULT_TARGET_BASE_DIFFICULTY)
    for target in targets:
        tmpl = _ability_templates(world).get(spec.get("skill"), {}) if spec.get("requiresSkill") else {}
        target_trait_bonus = _trait_modifier_sum(target, tmpl.get("trait_modifiers"))
        target_difficulty = max(DIFFICULTY_FLOOR, min(DIFFICULTY_CEIL,
            target_base + actor_margin + target_trait_bonus + extra_target_modifier))
        target_roll = roll_d100()
        result["target_results"].append({
            "target_id": target.get("id"),
            "success": target_roll <= target_difficulty,
            "difficulty": target_difficulty,
            "roll": target_roll,
        })

    return result
