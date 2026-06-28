"""
Assembly system.

Props that have requires_assembly:True in their template are bought
as an assembly box item. The character carries it home and uses the
assemble_prop action to convert it into a placed world prop.

Assembly box item schema:
{
    "id":            "item_box_modern_sofa_abc123",
    "template_id":   "box_modern_sofa",
    "type":          "assembly_box",
    "name":          "Sofa (Parts)",
    "category":      "assembly_box",
    "prop_template": "modern_sofa",
    "prop_category": "furniture",
    "stackable":     False,
    "consumable":    True,
    "uses":          1,
}
"""

import uuid


# =========================================================
# MAKE ASSEMBLY BOX
# =========================================================

def make_assembly_box(prop_template_id, world):
    """
    Create an item representing a flat-pack / parts box for a prop.
    prop_template_id: key in world["definitions"]["prop_templates"]
    """
    prop_templates = (
        world.get("definitions", {})
             .get("prop_templates", {})
    )
    pt   = prop_templates.get(prop_template_id, {})
    name = pt.get("name", prop_template_id)
    cat  = pt.get("category", "furniture")

    return {
        "id":            f"item_box_{prop_template_id}_{uuid.uuid4().hex[:6]}",
        "template_id":   f"box_{prop_template_id}",
        "type":          "assembly_box",
        "name":          f"{name} (Parts)",
        "category":      "assembly_box",
        "prop_template": prop_template_id,
        "prop_category": cat,
        "stackable":     False,
        "consumable":    True,
        "uses":          1,
        "quantity":      1,
    }


# =========================================================
# ASSEMBLE PROP
# =========================================================

def assemble_prop(c, world, item_id):
    """
    Convert an assembly_box item in the character's inventory into a
    placed world prop at the character's current position.

    Returns {"success": bool, "prop_id": str | None, "reason": str}
    """
    from systems.personal_items import get_item_by_id, remove_item

    item = get_item_by_id(c, item_id)
    if not item:
        return {"success": False, "prop_id": None, "reason": "item_not_found"}

    if item.get("type") != "assembly_box":
        return {"success": False, "prop_id": None, "reason": "not_an_assembly_box"}

    prop_template_id = item.get("prop_template")
    prop_templates   = (
        world.get("definitions", {})
             .get("prop_templates", {})
    )
    template = prop_templates.get(prop_template_id)
    if not template:
        return {"success": False, "prop_id": None, "reason": "prop_template_not_found"}

    # Remove box from inventory
    remove_item(c, item_id)

    # Place prop in the world at the character's position
    prop_id = f"prop_{prop_template_id}_{uuid.uuid4().hex[:6]}"
    world.setdefault("props", []).append({
        "id":          prop_id,
        "template":    prop_template_id,
        "building_id": c.get("building_id"),
        "x":           int(c.get("x", 0)),
        "y":           int(c.get("y", 0)),
        "rotation":    0,
        "state": {
            "reserved_by": [],
            "dirty":       False,
            "assembled_by": c["id"],
        },
    })

    return {"success": True, "prop_id": prop_id, "reason": "ok"}


# =========================================================
# CHECK — character has assembly boxes
# =========================================================

def assembly_boxes_in_inventory(c):
    """Return list of assembly box items the character is carrying."""
    return [
        i for i in c.get("inventory", [])
        if i.get("type") == "assembly_box"
    ]
