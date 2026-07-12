"""
Assembly system.

Props that have requires_assembly:True in their template are bought
as an assembly box item. The character carries it home and uses the
assemble_prop action to convert it into a placed world prop.

Floor tile materials (material_templates with category "floor") are
bought as a stackable tile box. Each assemble_tile use places one
1-sqm tile at the character's current position and decrements the box
quantity. The box is removed when quantity hits zero.

Prop assembly box schema:
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

Tile assembly box schema:
{
    "id":                "item_box_wood_floor_01_abc123",
    "template_id":       "box_wood_floor_01",
    "type":              "assembly_box",
    "tile_type":         "tile",
    "name":              "Wood Floor (Tiles)",
    "category":          "assembly_box",
    "material_template": "wood_floor_01",
    "stackable":         True,
    "max_stack":         100,
    "consumable":        True,
    "uses":              N,
    "quantity":          N,
}
"""

import copy
import uuid


# =========================================================
# MAKE PROP ASSEMBLY BOX
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

    if item.get("type") != "assembly_box" or item.get("tile_type") == "tile":
        return {"success": False, "prop_id": None, "reason": "not_a_prop_assembly_box"}

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
        # Deep-copied from the template so anchor-based systems
        # (occupancy's find_free_anchor/reserve_anchor, props.get_anchor/
        # find_nearest_anchor) — which all read anchors off the placed
        # instance, not the template — actually have something to find.
        # Must be a copy, not the same list/dicts as the template: reserve_
        # anchor() mutates an anchor's occupied_by/queue in place, and
        # every prop assembled from this template shares one `template`
        # object read from world["definitions"] — a shallow reference here
        # would let one sofa's occupancy leak into every other sofa.
        "anchors":     copy.deepcopy(template.get("anchors", [])),
        "state": {
            "reserved_by":  [],
            "dirty":        False,
            "assembled_by": c["id"],
        },
    })

    return {"success": True, "prop_id": prop_id, "reason": "ok"}


# =========================================================
# MAKE TILE BOX
# =========================================================

def make_tile_box(material_id, world, quantity=1):
    """
    Create a stackable assembly box for floor tile material.
    Each assemble_tile use places one 1-sqm tile and decrements quantity.

    material_id: key in world["definitions"]["material_templates"]
    quantity:    number of tiles in this box
    """
    material_templates = (
        world.get("definitions", {})
             .get("material_templates", {})
    )
    mt   = material_templates.get(material_id, {})
    name = mt.get("name", material_id)

    return {
        "id":                f"item_box_{material_id}_{uuid.uuid4().hex[:6]}",
        "template_id":       f"box_{material_id}",
        "type":              "assembly_box",
        "tile_type":         "tile",
        "name":              f"{name} (Tiles)",
        "category":          "assembly_box",
        "material_template": material_id,
        "stackable":         True,
        "max_stack":         100,
        "consumable":        True,
        "uses":              quantity,
        "quantity":          quantity,
    }


# =========================================================
# ASSEMBLE TILE
# =========================================================

def assemble_tile(c, world, item_id):
    """
    Place one floor tile at the character's current position from a tile box.
    Decrements quantity by 1; removes the box when quantity reaches 0.

    Returns {"success": bool, "tile_key": str | None, "reason": str}
    """
    from systems.personal_items import get_item_by_id, remove_item

    item = get_item_by_id(c, item_id)
    if not item:
        return {"success": False, "tile_key": None, "reason": "item_not_found"}

    if item.get("type") != "assembly_box" or item.get("tile_type") != "tile":
        return {"success": False, "tile_key": None, "reason": "not_a_tile_box"}

    material_id = item.get("material_template")
    if not material_id:
        return {"success": False, "tile_key": None, "reason": "no_material_template"}

    material_templates = (
        world.get("definitions", {})
             .get("material_templates", {})
    )
    mt = material_templates.get(material_id, {})

    x = int(c.get("x", 0))
    y = int(c.get("y", 0))
    tile_key = f"{x},{y}"

    # Place (or overwrite) tile in world["tiles"]
    world.setdefault("tiles", {})[tile_key] = {
        "x":           x,
        "y":           y,
        "type":        "floor",
        "interior":    mt.get("interior", True),
        "floor":       mt.get("floor", True),
        "material":    material_id,
        "placed_by":   c["id"],
        "building_id": c.get("building_id"),
        "walkable":    True,
    }

    # Decrement; remove box when exhausted
    qty = item.get("quantity", 1) - 1
    if qty <= 0:
        remove_item(c, item_id)
    else:
        item["quantity"] = qty
        item["uses"]     = qty

    return {"success": True, "tile_key": tile_key, "reason": "ok"}


# =========================================================
# INVENTORY QUERIES
# =========================================================

def assembly_boxes_in_inventory(c):
    """Return all assembly box items (prop boxes + tile boxes)."""
    return [
        i for i in c.get("inventory", [])
        if i.get("type") == "assembly_box"
    ]


def tile_boxes_in_inventory(c):
    """Return only tile assembly boxes."""
    return [
        i for i in c.get("inventory", [])
        if i.get("type") == "assembly_box" and i.get("tile_type") == "tile"
    ]
