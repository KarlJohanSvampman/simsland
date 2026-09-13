"""
systems/abilities.py

Special Skills & Abilities -- cooking, juggling, a language, or anything
else -- defined once as a definitions.json "ability_templates" entry
rather than hardcoded per skill:

    "cooking": {
        "name": "Cooking",
        "trains_via": ["cook_meal", "bake"],        -- which actions
            practicing this ability actually trains it (attempting one
            of these counts as a real training attempt, win or lose).
        "proficiency_levels": [
            {"level": "novice", "title": "Initiate", "successes_to_next": 3, "bonus": 5},
            {"level": "beginner", "title": "Average", "successes_to_next": 6, "bonus": 15},
            ...
            {"level": "expert", "title": "Master", "successes_to_next": null, "bonus": 60}
                -- null successes_to_next = the top level, nothing
                further to level into. "title" is the player-facing
                name; "bonus" is this level's authored contribution to
                a d100 skill-check difficulty (see systems/
                skill_checks.py -- higher difficulty = easier to
                succeed, so a higher-level bonus makes success MORE
                likely, not less).
        ],
        "trait_modifiers": [{"trait": "clumsy", "modifier": -15}]
            -- signed difficulty-point bonus/penalty per owned trait
            (checked against traits + personality_traits +
            physical_traits), applied by systems/skill_checks.py's own
            difficulty calculation, not by this module.
    }

A character's own progress lives in c["abilities"][ability_id] =
{"level", "successes", "attempts"}, created lazily on first attempt.
This module owns proficiency TRACKING only (level-up bookkeeping via
record_attempt(), requirement gating via meets_requirement()) -- the
actual pass/fail ROLL for a skill/ability-gated action is
systems/skill_checks.py's job (a real d100 roll-under-difficulty check,
separate from systems/contested_checks.py's own continuous roll+
threshold math for force/influence/manipulation checks). A route calls
skill_checks.resolve_skill_check(...) first, then feeds its "success"
and "actor_margin" straight into this module's record_attempt() to
update progression.

ability_characteristic_value() is kept as a 0-1 proficiency readout
still consumed by contested_checks.py's generic "ability:<id>"
characteristic hook (for any FORCE/INFLUENCE/MANIPULATION check that
wants to weight in a skill) -- that's a different consumer than the
skill_checks.py path above and is unrelated to it.
"""


def _ability_templates(world):
    return (world.get("definitions", {}) or {}).get("ability_templates", {})


def ensure_abilities(c):
    return c.setdefault("abilities", {})


def get_ability_entry(c, ability_id):
    return c.get("abilities", {}).get(ability_id)


def _levels(ability_id, world):
    return _ability_templates(world).get(ability_id, {}).get("proficiency_levels", [])


def get_level_index(c, ability_id, world):
    """0-based index into the ability's own proficiency_levels list --
    0 (the first/lowest level) for a character who's never attempted it."""
    levels = _levels(ability_id, world)
    if not levels:
        return 0
    entry = get_ability_entry(c, ability_id)
    current = entry.get("level") if entry else levels[0]["level"]
    for i, lvl in enumerate(levels):
        if lvl["level"] == current:
            return i
    return 0


def get_level_name(c, ability_id, world):
    levels = _levels(ability_id, world)
    if not levels:
        return None
    return levels[get_level_index(c, ability_id, world)]["level"]


def ability_characteristic_value(c, ability_id, world):
    """0-1 value representing how proficient c is at this ability,
    scaled by its position in the template's OWN proficiency_levels
    list -- data-driven, not a hardcoded tier count, so a 3-level
    ability and a 6-level one both span the same 0-1 range. Used as the
    "ability:<id>" characteristic in systems/contested_checks.py."""
    levels = _levels(ability_id, world)
    if not levels:
        return 0.0
    return get_level_index(c, ability_id, world) / max(1, len(levels) - 1)


def meets_requirement(c, ability_id, min_level, world):
    """True if c's current proficiency in ability_id is at or above
    min_level (per that ability's own level ordering). Fails OPEN (True)
    if the ability or level isn't recognized -- a misconfigured
    requirement shouldn't silently hard-block an action forever."""
    levels = [lvl["level"] for lvl in _levels(ability_id, world)]
    if min_level not in levels:
        return True
    return get_level_index(c, ability_id, world) >= levels.index(min_level)


DEFAULT_MARGIN_PER_BONUS_SUCCESS = 10


def record_attempt(c, ability_id, world, success, margin=0):
    """Call once per genuine training attempt (an action listed in the
    ability's own trains_via was actually performed) -- tracks attempts/
    successes and levels up once the CURRENT level's own
    successes_to_next threshold is reached (each level can require a
    different number of successes, per the template).

    `margin` (systems/skill_checks.py::resolve_skill_check()'s own
    "actor_margin" -- how much room to spare the roll succeeded by, 0 for
    a plain non-margin-aware caller) scales how many successes a single
    outstanding attempt counts as: 1 + (margin // margin_per_bonus_success)
    -- a razor-thin success still counts as exactly 1 (unchanged from
    before this existed), but a spectacular one trains the skill several
    "occasions" at once, per the ability template's own (optional,
    defaults to 10) margin_per_bonus_success field."""
    levels = _levels(ability_id, world)
    if not levels:
        return None

    abilities = ensure_abilities(c)
    entry = abilities.setdefault(ability_id, {
        "level": levels[0]["level"], "successes": 0, "attempts": 0,
    })
    entry["attempts"] += 1
    if not success:
        return entry

    tmpl = _ability_templates(world).get(ability_id, {})
    divisor = tmpl.get("margin_per_bonus_success", DEFAULT_MARGIN_PER_BONUS_SUCCESS)
    bonus_successes = int(margin // divisor) if margin and divisor else 0
    entry["successes"] += 1 + max(0, bonus_successes)

    # Carry any overflow across a level-up (and allow cascading through
    # more than one level in a single outstanding attempt) instead of
    # discarding it -- a big margin's whole point is to reward an
    # exceptional attempt, so resetting straight to 0 on level-up would
    # waste exactly the credit this feature exists to grant.
    while True:
        idx = get_level_index(c, ability_id, world)
        needed = levels[idx].get("successes_to_next")
        if needed is None or entry["successes"] < needed or idx + 1 >= len(levels):
            break
        entry["successes"] -= needed
        entry["level"] = levels[idx + 1]["level"]
        entry["leveled_up_tick"] = world.get("tick", 0)
    return entry


def find_ability_for_action(action_type, world):
    """Which ability (if any) does performing this action type train?
    Linear scan over the small ability_templates table -- fine at this
    scale, and keeps trains_via as the single source of truth rather
    than needing a second reverse-index kept in sync by hand."""
    for ability_id, tmpl in _ability_templates(world).items():
        if action_type in (tmpl.get("trains_via") or []):
            return ability_id
    return None


