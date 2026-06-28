"""
Generic container system.

A container is an item (lives in a character's inventory or placed in the world)
that holds other items in its own "items" array. Items inside a container have
no world position and no graphical representation.

Slot accounting:
  Each item has a "size" field (default 1) representing the slot cost per unit.
  Stacks multiply: a stack of 10 apples (size=1 each) uses 10 slots, not 1.
  Formula: slots_used_by_item = item["size"] * item.get("quantity", 1)

Nesting: one level only.
  A container may sit in a character's top-level inventory or be placed in the world,
  but containers may NOT be placed inside other containers.

Container schema:
{
    "id":         "container_box_abc123",
    "type":       "container",
    "sub_type":   "cardboard_box",    # "cardboard_box" | "bucket" | "backpack" | "toolbox" | ...
    "name":       "Cardboard Box",
    "category":   "container",
    "capacity":   20,                  # total slots
    "items":      [],                  # item instances (same schema as inventory items)
    "size":       4,                   # slots this container itself takes in a parent inventory
    "stackable":  False,
    "material":   None,                # used by buckets: the material_template id of the liquid
}

Bucket sub-type:
  "sub_type": "bucket"
  "material": "red_gloss"   # or "wallpaper_floral_01" etc.
  "capacity": 10            # litres (effectively 10 uses of paint)
  "items": []               # empty — bucket stores liquid as "material" field, not item instances

  A bucket is consumed by paint_wall actions. Each use decrements "uses" by 1.
  When uses reaches 0 the bucket is removed from inventory.
"""

import uuid


# =========================================================
# CONTAINER TEMPLATES
# Defaults per sub_type; overridable at creation time.
# =========================================================

CONTAINER_TEMPLATES = {
    "cardboard_box": {"capacity": 20, "size": 4,  "name": "Cardboard Box"},
    "backpack":      {"capacity": 15, "size": 2,  "name": "Backpack"},
    "toolbox":       {"capacity": 10, "size": 3,  "name": "Toolbox"},
    "chest":         {"capacity": 50, "size": 10, "name": "Storage Chest"},
    "bucket":        {"capacity": 10, "size": 2,  "name": "Bucket"},
}


# =========================================================
# CREATION
# =========================================================

def create_container(sub_type="cardboard_box", name=None, capacity=None, size=None):
    """
    Create a generic container item (non-bucket).
    Returns the container dict suitable for placement in an inventory.
    """
    tmpl = CONTAINER_TEMPLATES.get(sub_type, CONTAINER_TEMPLATES["cardboard_box"])
    return {
        "id":        f"container_{sub_type}_{uuid.uuid4().hex[:6]}",
        "type":      "container",
        "sub_type":  sub_type,
        "name":      name or tmpl["name"],
        "category":  "container",
        "capacity":  capacity if capacity is not None else tmpl["capacity"],
        "items":     [],
        "size":      size if size is not None else tmpl["size"],
        "stackable": False,
        "material":  None,
    }


def create_bucket(material_id, world, uses=None):
    """
    Create a paint/wallpaper bucket.

    material_id: key in world["definitions"]["material_templates"]
                 with category "paint" or "wallpaper".
    uses: number of wall applications (default: capacity of the bucket template).

    Returns the bucket item dict, or None if material_id is not a valid wall material.
    """
    mt = (
        world.get("definitions", {})
             .get("material_templates", {})
             .get(material_id, {})
    )
    cat = mt.get("category")
    if cat not in ("paint", "wallpaper"):
        return None

    tmpl     = CONTAINER_TEMPLATES["bucket"]
    max_uses = tmpl["capacity"]
    u        = uses if uses is not None else max_uses

    return {
        "id":        f"bucket_{material_id}_{uuid.uuid4().hex[:6]}",
        "type":      "container",
        "sub_type":  "bucket",
        "name":      f"{mt.get('name', material_id)} (Bucket)",
        "category":  "container",
        "capacity":  max_uses,
        "items":     [],           # buckets don't hold item instances
        "size":      tmpl["size"],
        "stackable": False,
        "material":  material_id,  # the paint/wallpaper material inside
        "uses":      u,
        "quantity":  1,
        "consumable": True,
    }


# =========================================================
# SLOT ACCOUNTING
# =========================================================

def slots_used(container):
    """Total slots occupied by items inside the container."""
    total = 0
    for item in container.get("items", []):
        total += item.get("size", 1) * item.get("quantity", 1)
    return total


def slots_available(container):
    return container.get("capacity", 0) - slots_used(container)


def can_fit(container, item, quantity=1):
    """
    Return True if `quantity` units of item fit in container.
    Does not allow containers inside containers.
    """
    if item.get("type") == "container":
        return False  # no nesting
    needed = item.get("size", 1) * quantity
    return slots_available(container) >= needed


# =========================================================
# ADD / REMOVE ITEMS
# =========================================================

def add_to_container(container, item, quantity=None):
    """
    Add item (or N units of it) to container.

    If quantity is None, uses item["quantity"] (default 1).
    Returns {"success": bool, "reason": str}.
    Containers-within-containers are rejected.
    """
    if item.get("type") == "container":
        return {"success": False, "reason": "no_nesting"}

    qty = quantity if quantity is not None else item.get("quantity", 1)
    if not can_fit(container, item, qty):
        return {"success": False, "reason": "no_space"}

    # Check if same item already exists in container (stackable merge)
    if item.get("stackable"):
        tid = item.get("template_id") or item.get("id")
        for existing in container["items"]:
            if (existing.get("template_id") or existing.get("id")) == tid:
                existing_qty = existing.get("quantity", 1)
                max_stack    = existing.get("max_stack", 99)
                add_qty      = min(qty, max_stack - existing_qty)
                existing["quantity"] = existing_qty + add_qty
                existing.setdefault("uses", existing["quantity"])
                return {"success": True, "reason": "stacked"}

    # New entry — clone with adjusted quantity
    import copy
    entry = copy.deepcopy(item)
    entry["quantity"] = qty
    container["items"].append(entry)
    return {"success": True, "reason": "added"}


def remove_from_container(container, item_id, quantity=None):
    """
    Remove item_id from container.

    If quantity is None, removes all.
    Returns {"success": bool, "item": dict | None, "reason": str}.
    """
    for i, item in enumerate(container["items"]):
        if item["id"] == item_id:
            if quantity is None or quantity >= item.get("quantity", 1):
                removed = container["items"].pop(i)
                return {"success": True, "item": removed, "reason": "ok"}
            else:
                item["quantity"] -= quantity
                import copy
                partial = copy.deepcopy(item)
                partial["quantity"] = quantity
                return {"success": True, "item": partial, "reason": "partial"}
    return {"success": False, "item": None, "reason": "not_found"}


# =========================================================
# CONSUME BUCKET USE
# =========================================================

def use_bucket(bucket):
    """
    Decrement bucket uses by 1. Returns True if bucket is now empty.
    Caller should remove the bucket from inventory when this returns True.
    """
    bucket["uses"] = bucket.get("uses", 1) - 1
    return bucket["uses"] <= 0


# =========================================================
# QUERIES
# =========================================================

def find_bucket_for_material(c, material_id):
    """
    Find the first paint/wallpaper bucket in character's inventory
    that matches material_id and has uses remaining.
    """
    for item in c.get("inventory", []):
        if (
            item.get("type") == "container"
            and item.get("sub_type") == "bucket"
            and item.get("material") == material_id
            and item.get("uses", 0) > 0
        ):
            return item
    return None


def containers_in_inventory(c):
    """Return all container items in character's top-level inventory."""
    return [i for i in c.get("inventory", []) if i.get("type") == "container"]


def container_summary(container):
    """Compact summary for LLM context."""
    used = slots_used(container)
    cap  = container.get("capacity", 0)
    if container.get("sub_type") == "bucket":
        return {
            "id":       container["id"],
            "name":     container["name"],
            "sub_type": "bucket",
            "material": container.get("material"),
            "uses":     container.get("uses", 0),
        }
    return {
        "id":       container["id"],
        "name":     container["name"],
        "sub_type": container.get("sub_type"),
        "slots":    f"{used}/{cap}",
        "items":    [
            {"name": i.get("name"), "qty": i.get("quantity", 1)}
            for i in container.get("items", [])
        ],
    }
