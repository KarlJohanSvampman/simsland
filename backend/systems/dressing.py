"""
systems/dressing.py

"get_dressed" -- a character walks to their wardrobe (prop_templates
["wardrobe"] already had a dormant "change_clothes" anchor; this is what
finally uses it) and picks an outfit from what's actually stored there,
one clothing slot at a time, via systems/choice.py's generic "pick from
options" utility -- not bespoke clothing-choosing logic. That utility is
built to be reused for any other "make the character pick something"
interaction (a restaurant, a time slot, ...), with clothing as its first
real caller.

Wardrobe ownership: prefers one personally owned by this character
(prop["owner_id"], set when a character assembles their own -- see
assembly.py) -- falls back to any wardrobe accessible in their
household's building(s) (a shared family wardrobe), same fallback shape
as every other household-storage lookup in this codebase.
"""

WARDROBE_TEMPLATE = "wardrobe"


def _find_wardrobe(c, world):
    household = world.get("households", {}).get(c.get("household_id"))
    building_ids = set(household.get("building_ids", [])) if household else set()
    candidates = [
        p for p in world.get("props", [])
        if p.get("template") == WARDROBE_TEMPLATE and p.get("building_id") in building_ids
    ]
    if not candidates:
        return None
    return next((p for p in candidates if p.get("owner_id") == c["id"]), candidates[0])


def resolve_get_dressed(c, world, act):
    """Called from activities.py::complete_activity() for
    activity_type=="get_dressed". occasion (optional -- see
    systems/choice.py::choose()) can be stashed on
    act["state"]["occasion"] by whatever triggered this activity (e.g. a
    future "character realizes they have a job interview today" hook);
    None today just means the LLM uses its own judgment from the
    character's traits and the available items, no occasion narrowing."""
    from systems.containers import ensure_prop_storage, remove_from_container
    from systems.clothing import CLOTHING_SLOTS, put_on_clothing
    from systems.choice import choose
    from systems.validation import queue_choice_for_validation
    from systems.personal_items import add_item

    wardrobe = _find_wardrobe(c, world)
    if not wardrobe:
        return
    container = ensure_prop_storage(wardrobe, world)
    if not container:
        return

    occasion = (act.get("state") or {}).get("occasion")

    by_slot = {}
    for item in container.get("items", []):
        slot = item.get("slot")
        if slot in CLOTHING_SLOTS:
            by_slot.setdefault(slot, []).append(item)

    picked_labels = []
    for slot, items in by_slot.items():
        options = [
            {"id": it["id"], "label": it.get("name", it["id"]), "tags": it.get("tags", [])}
            for it in items
        ]
        picked = choose(c, world, "clothing item", options, occasion=occasion)
        if not picked:
            continue
        removed = remove_from_container(container, picked["id"])
        if not removed.get("success"):
            continue
        add_item(c, removed["item"])
        put_on_clothing(c, world, removed["item"]["id"])
        picked_labels.append(picked.get("label", picked["id"]))

    if picked_labels:
        queue_choice_for_validation(c, world, "outfit", " + ".join(picked_labels), occasion=occasion)
