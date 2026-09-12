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
            {"level": "novice", "successes_to_next": 3},
            {"level": "beginner", "successes_to_next": 6},
            ...
            {"level": "expert", "successes_to_next": null}   -- null =
                the top level, nothing further to level into.
        ],
        "trait_modifiers": {"clumsy": -0.15}   -- flat bonus/penalty to
            every check involving this ability, per owned trait tag.
    }

A character's own progress lives in c["abilities"][ability_id] =
{"level", "successes", "attempts"}, created lazily on first attempt.

Reuses systems/contested_checks.py's engine for the actual pass/fail
roll on a training attempt -- current proficiency feeds back INTO that
roll as a real characteristic ("ability:<id>", resolved dynamically by
contested_checks.py rather than hardcoded per ability), so a more
practiced character is more likely to succeed at the very thing that
keeps training them further, and CHECK_DEFINITIONS entries for
ability-trained actions can weight "ability:<id>" like any other
characteristic.
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


def trait_modifier(c, ability_id, world):
    """Flat bonus/penalty from the ability template's own trait_modifiers
    table -- e.g. "clumsy" hurting juggling/cooking checks."""
    tmpl = _ability_templates(world).get(ability_id, {})
    mods = tmpl.get("trait_modifiers", {})
    if not mods:
        return 0.0
    traits = set(c.get("traits", []) + c.get("personality_traits", []))
    return sum(v for tag, v in mods.items() if tag in traits)


def meets_requirement(c, ability_id, min_level, world):
    """True if c's current proficiency in ability_id is at or above
    min_level (per that ability's own level ordering). Fails OPEN (True)
    if the ability or level isn't recognized -- a misconfigured
    requirement shouldn't silently hard-block an action forever."""
    levels = [lvl["level"] for lvl in _levels(ability_id, world)]
    if min_level not in levels:
        return True
    return get_level_index(c, ability_id, world) >= levels.index(min_level)


def record_attempt(c, ability_id, world, success):
    """Call once per genuine training attempt (an action listed in the
    ability's own trains_via was actually performed) -- tracks attempts/
    successes and levels up once the CURRENT level's own
    successes_to_next threshold is reached (each level can require a
    different number of successes, per the template)."""
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

    entry["successes"] += 1
    idx = get_level_index(c, ability_id, world)
    needed = levels[idx].get("successes_to_next")
    if needed is not None and entry["successes"] >= needed and idx + 1 < len(levels):
        entry["successes"] = 0
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


def attempt_ability_action(c, ability_id, action_type, world, target=None):
    """The real entry point a route calls when a character performs an
    action that trains (and/or requires) an ability: resolves a check
    (systems/contested_checks.py, if action_type has its own
    CHECK_DEFINITIONS entry weighting "ability:<id>"; otherwise a plain
    proficiency-vs-a-flat-threshold roll) and records the attempt.
    Returns (success: bool, ability_entry)."""
    from systems.contested_checks import CHECK_DEFINITIONS, resolve_check
    import random

    extra = trait_modifier(c, ability_id, world)
    if action_type in CHECK_DEFINITIONS:
        check = resolve_check(action_type, c, target, world, extra_actor_mod=extra)
        success = bool(check and check["success"])
    else:
        # No bespoke check config for this action -- fall back to a
        # simple solo roll weighted by proficiency alone.
        proficiency = ability_characteristic_value(c, ability_id, world)
        success = random.random() < (0.35 + proficiency * 0.5 + extra)

    entry = record_attempt(c, ability_id, world, success)
    return success, entry
