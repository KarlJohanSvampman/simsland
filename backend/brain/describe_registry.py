"""
brain/describe_registry.py

Content source for the "describe" action (Round 8) — the action that
costs no in-world time and yields only more description, never a real
game-state change. A {(target_kind, aspect): source_fn} table, deliberately
small in v1 (systems/action_router.py::_route_describe falls back to the
target's "default" aspect for anything unrecognized); rows are pure
additions later (describe $person $trait, self-aspects secrets/crushes/
reputation/calendar/hobbies/factions/pregnancy/etc. — see brain/
context_builder.py's NARRATIVE_SECTIONS table and its inventory of
dormant _build_X_context() functions for where that content already
lives).

Each source_fn(c, world, target_id=None) -> str | None. target_id is None
for room/self/activity (no target needed); set for character/prop/item.
"""


def _describe_room(c, world, target_id=None):
    from brain.context_builder import build_scene_description
    # Untruncated — the full scene description, not the tiered "brief"
    # mode's abbreviated version (see brain/context_builder.py's
    # NARRATIVE_SECTIONS / TIER_SETS).
    return build_scene_description(c, world)


def _describe_character_default(c, world, target_id):
    from systems.perception.descriptions import build_visible_person_description
    target = world.get("characters", {}).get(target_id)
    if not target:
        return None
    return build_visible_person_description(c, target, world.get("definitions", {}))


def _describe_character_personality(c, world, target_id):
    target = world.get("characters", {}).get(target_id)
    if not target:
        return None
    rel = c.get("relationships", {}).get(target_id, {})
    familiarity = rel.get("familiarity", 0)
    # Personality is only something you'd actually know about someone once
    # you've spent real time around them — gated the same way build_
    # relationship_context() gates whether a relationship shows up at all
    # (familiarity or interaction_count > 0), just at a higher bar.
    if familiarity < 20:
        return f"You don't know {target.get('name', 'them')} well enough to say what they're like."
    traits = target.get("traits", [])
    if not traits:
        return f"You don't have a strong read on {target.get('name', 'their')} personality."
    return f"{target.get('name', 'They')}'s personality: {', '.join(traits)}."


def _describe_character_equipped(c, world, target_id):
    target = world.get("characters", {}).get(target_id)
    if not target:
        return None
    worn = [item.get("name") for item in (target.get("worn") or {}).values() if item]
    held = next(
        (i.get("name") for i in target.get("inventory", []) if i.get("location") == "held"),
        None,
    )
    bits = []
    if worn:
        bits.append(f"wearing {', '.join(worn)}")
    if held:
        bits.append(f"holding {held}")
    if not bits:
        return f"{target.get('name', 'They')} isn't carrying or wearing anything notable."
    return f"{target.get('name', 'They')} is {' and '.join(bits)}."


def _describe_character_relationship(c, world, target_id):
    from brain.context_builder import build_relationship_context
    for entry in build_relationship_context(c, world, limit=50):
        if entry.get("id") == target_id:
            return entry["summary"]
    target = world.get("characters", {}).get(target_id)
    name = target.get("name", "them") if target else "them"
    return f"You don't really know {name}."


def _describe_character_doing(c, world, target_id):
    from brain.perception import perceived_activity
    target = world.get("characters", {}).get(target_id)
    if not target:
        return None
    activity = perceived_activity(target)
    name = target.get("name", "They")
    return f"{name} appears to be {activity}." if activity else f"{name} doesn't seem to be doing anything in particular."


def _describe_prop_default(c, world, target_id):
    from systems.props import get_prop_by_id
    prop = get_prop_by_id(world, target_id)
    if not prop:
        return None
    template = prop.get("template", "something")
    tags = prop.get("tags", [])
    bits = [f"It's a {template}."]
    if tags:
        bits.append(f"Tags: {', '.join(tags)}.")
    return " ".join(bits)


def _describe_prop_contents(c, world, target_id):
    from systems.props import get_prop_by_id
    prop = get_prop_by_id(world, target_id)
    if not prop:
        return None
    items = prop.get("items") or []
    if not items:
        return "It's empty."
    names = ", ".join(i.get("name", "something") for i in items[:8])
    return f"Inside: {names}."


def _describe_item_default(c, world, target_id):
    for pool in (c.get("inventory", []), c.get("held_stack", [])):
        for item in pool:
            if item.get("id") == target_id:
                bits = [item.get("name", "an item")]
                if item.get("items"):
                    inner = ", ".join(i.get("name", "something") for i in item["items"][:8])
                    bits.append(f"containing {inner}")
                return " ".join(bits) + "."
    return None


def _describe_self_inventory(c, world, target_id=None):
    from brain.context_builder import _build_inventory_context
    lines = _build_inventory_context(c)
    return " ".join(lines) if lines else "You aren't carrying anything."


def _describe_self_equipped(c, world, target_id=None):
    from brain.context_builder import _build_worn_context
    lines = _build_worn_context(c)
    return " ".join(lines) if lines else "You aren't wearing anything notable."


def _describe_self_body(c, world, target_id=None):
    from brain.context_builder import build_body_context
    lines = build_body_context(c)
    return " ".join(lines) if lines else "You feel physically fine."


def _describe_self_feelings(c, world, target_id=None):
    emotion = c.get("emotion", "neutral")
    stress = c.get("stress", 0)
    bits = [f"Right now you feel {emotion}."]
    if stress > 60:
        bits.append("You're under real stress.")
    return " ".join(bits)


def _describe_activity_default(c, world, target_id=None):
    activity = c.get("activity")
    if not activity:
        return "You aren't in the middle of anything in particular right now."
    activity_type = (activity.get("type") or "something").replace("_", " ")
    phase = activity.get("phase")
    if phase:
        return f"You're in the middle of {activity_type} ({phase} phase)."
    return f"You're in the middle of {activity_type}."


DESCRIBE_REGISTRY = {
    ("room", "default"): _describe_room,

    ("character", "default"): _describe_character_default,
    ("character", "personality"): _describe_character_personality,
    ("character", "equipped"): _describe_character_equipped,
    ("character", "holding"): _describe_character_equipped,
    ("character", "relationship"): _describe_character_relationship,
    ("character", "doing"): _describe_character_doing,

    ("prop", "default"): _describe_prop_default,
    ("prop", "contents"): _describe_prop_contents,

    ("item", "default"): _describe_item_default,

    ("self", "inventory"): _describe_self_inventory,
    ("self", "equipped"): _describe_self_equipped,
    ("self", "body"): _describe_self_body,
    ("self", "feelings"): _describe_self_feelings,

    ("activity", "default"): _describe_activity_default,
}


def produce_description(c, world, target_kind, aspect, target_id=None):
    """Look up and run the matching source_fn, falling back to that
    target_kind's "default" row if the requested aspect isn't registered.
    Returns a non-empty string in every case — an unresolvable request
    still needs SOME text to stage, or the character would loop asking
    the same unanswerable question."""
    fn = DESCRIBE_REGISTRY.get((target_kind, aspect)) or DESCRIBE_REGISTRY.get((target_kind, "default"))
    if not fn:
        return "There's nothing more to say about that."
    try:
        result = fn(c, world, target_id)
    except Exception:
        result = None
    return result or "There's nothing more to say about that."
