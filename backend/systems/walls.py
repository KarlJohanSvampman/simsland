"""
Wall system.

Walls are first-class world entities stored in world["walls"], keyed by wall_id.
They are distinct from floor tiles (world["tiles"]) and props.

Wall schema:
{
    "id":           "wall_house_1_3_2_h",
    "building_id":  "house_1",
    "x":            3,
    "y":            2,
    "orientation":  "h",        # "h" horizontal (runs east-west) or "v" vertical (runs north-south)
    "load_bearing": False,       # if True, cannot be removed
    "material":     "default_wall",  # material_template id — governs paint/wallpaper appearance
    "walkable":     False,
    "interior":     True,
}

Paint/wallpaper materials (material_templates with category "paint" or "wallpaper"):
  paint:     {name, category:"paint",     color:"#hex",    finish, price_per_liter}
  wallpaper: {name, category:"wallpaper", pattern:"url",   repeat, price_per_roll}

Both are applied to a wall via paint_wall(). The character must have a matching
paint_bucket or wallpaper_roll in their inventory containing the right material_id.
"""

import uuid
import math


# =========================================================
# CREATION
# =========================================================

def create_wall(world, x, y, orientation, building_id,
                load_bearing=False, material="default_wall", interior=True):
    """
    Add a new wall to world["walls"].

    orientation: "h" (horizontal, runs east-west) | "v" (vertical, runs north-south)

    Returns the created wall dict, or existing wall if one already occupies x,y,orientation.
    """
    existing = get_wall(world, x, y, orientation)
    if existing:
        return existing

    wid = f"wall_{building_id}_{x}_{y}_{orientation}"
    wall = {
        "id":           wid,
        "building_id":  building_id,
        "x":            x,
        "y":            y,
        "orientation":  orientation,
        "load_bearing": load_bearing,
        "material":     material,
        "walkable":     False,
        "interior":     interior,
    }
    world.setdefault("walls", {})[wid] = wall
    return wall


# =========================================================
# REMOVAL
# =========================================================

def remove_wall(world, wall_id):
    """
    Remove a wall by id.

    Returns {"success": bool, "reason": str}.
    Load-bearing walls are rejected.
    """
    wall = world.get("walls", {}).get(wall_id)
    if not wall:
        return {"success": False, "reason": "wall_not_found"}
    if wall.get("load_bearing"):
        return {"success": False, "reason": "load_bearing"}
    world["walls"].pop(wall_id)
    return {"success": True, "reason": "ok"}


# =========================================================
# PAINTING / WALLPAPER
# =========================================================

def paint_wall(world, wall_id, material_id):
    """
    Apply a paint color or wallpaper pattern to a wall.

    material_id must exist in world["definitions"]["material_templates"]
    with category "paint" or "wallpaper".

    Returns {"success": bool, "reason": str}.
    The caller is responsible for consuming the paint bucket / wallpaper roll.
    """
    wall = world.get("walls", {}).get(wall_id)
    if not wall:
        return {"success": False, "reason": "wall_not_found"}

    material_templates = (
        world.get("definitions", {})
             .get("material_templates", {})
    )
    mt = material_templates.get(material_id)
    if not mt:
        return {"success": False, "reason": "material_not_found"}
    if mt.get("category") not in ("paint", "wallpaper"):
        return {"success": False, "reason": "not_a_wall_material"}

    wall["material"] = material_id
    return {"success": True, "reason": "ok"}


# =========================================================
# QUERIES
# =========================================================

def get_wall(world, x, y, orientation):
    """Return the wall at (x, y, orientation), or None."""
    wid = _wall_id_at(x, y, orientation)
    return world.get("walls", {}).get(wid)


def get_wall_by_id(world, wall_id):
    return world.get("walls", {}).get(wall_id)


def walls_in_building(world, building_id):
    """Return all walls belonging to building_id."""
    return [
        w for w in world.get("walls", {}).values()
        if w.get("building_id") == building_id
    ]


def walls_near(world, x, y, radius=1):
    """Return walls within manhattan radius of (x, y)."""
    return [
        w for w in world.get("walls", {}).values()
        if abs(w["x"] - x) + abs(w["y"] - y) <= radius
    ]


def is_load_bearing(world, wall_id):
    wall = world.get("walls", {}).get(wall_id)
    return bool(wall and wall.get("load_bearing"))


def find_leanable_wall(c, world):
    """
    Find a wall the character can lean against.

    Returns {"wall_id": str, "x": int, "y": int, "virtual": bool}, or None
    if the character is outdoors with no boundary in reach.

    Priority:
      1. Real wall entity within manhattan radius 1 in the same building.
      2. Virtual wall — a synthetic id derived from the character's position,
         used when room boundaries haven't been placed as explicit entities.
         Virtual walls work fine for posture bookkeeping; they just have no
         paint/material data.
    """
    cx, cy = int(c.get("x", 0)), int(c.get("y", 0))
    bid    = c.get("building_id")

    # 1. Real wall entities
    nearby = walls_near(world, cx, cy, radius=1)
    if bid:
        nearby = [w for w in nearby if w.get("building_id") == bid]
    if nearby:
        w = nearby[0]
        return {"wall_id": w["id"], "x": w["x"], "y": w["y"], "virtual": False}

    # 2. Virtual fallback — only inside a building
    if not bid:
        return None

    # Snap to nearest grid boundary on the X axis as a simple heuristic
    wx = math.floor(cx) if (cx % 2 < 1) else math.ceil(cx)
    virtual_id = f"vwall_{bid}_{wx}_{cy}"
    return {"wall_id": virtual_id, "x": wx, "y": cy, "virtual": True}


# =========================================================
# INTERNAL
# =========================================================

def _wall_id_at(x, y, orientation):
    return f"wall__{x}_{y}_{orientation}"
