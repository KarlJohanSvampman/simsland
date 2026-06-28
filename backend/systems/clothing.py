"""
Clothing system.

c["worn"] = {
    "head":       item_dict | None,
    "hair":       item_dict | None,
    "neck":       item_dict | None,
    "outerwear":  item_dict | None,
    "torso":      item_dict | None,
    "undershirt": item_dict | None,
    "legs":       item_dict | None,
    "underwear":  item_dict | None,
    "socks":      item_dict | None,
    "feet":       item_dict | None,
    "hands":      item_dict | None,
    "wrist_l":    item_dict | None,
    "wrist_r":    item_dict | None,
    "accessory":  item_dict | None,
}

Stacking: clothing items in inventory with the same template_id AND same
dirty state can be combined into a single item with quantity > 1.
When worn items come off they are always quantity=1.
"""

from data.item_templates import ITEM_TEMPLATES, get_template

# =========================================================
# SLOT REGISTRY
# slot_id → bone name (Three.js SkinnedMesh attachment)
# =========================================================

CLOTHING_SLOTS = {
    "head":       {"bone": "Head",         "label": "Head"},
    "hair":       {"bone": "Head",         "label": "Hair"},
    "neck":       {"bone": "Neck",         "label": "Neck"},
    "outerwear":  {"bone": "Spine2",       "label": "Jacket / Coat"},
    "torso":      {"bone": "Spine1",       "label": "Top / Shirt"},
    "undershirt": {"bone": "Spine1",       "label": "Undershirt"},
    "legs":       {"bone": "Hips",         "label": "Pants / Skirt"},
    "underwear":  {"bone": "Hips",         "label": "Underwear"},
    "socks":      {"bone": "LeftFoot",     "label": "Socks",   "bilateral": True},
    "feet":       {"bone": "LeftFoot",     "label": "Shoes",   "bilateral": True},
    "hands":      {"bone": "LeftHand",     "label": "Gloves",  "bilateral": True},
    "wrist_l":    {"bone": "LeftForeArm",  "label": "Wrist L"},
    "wrist_r":    {"bone": "RightForeArm", "label": "Wrist R"},
    "accessory":  {"bone": "Spine2",       "label": "Accessory"},
}

ALL_SLOTS = list(CLOTHING_SLOTS.keys())


# =========================================================
# WORN STATE INIT
# =========================================================

def ensure_worn(c):
    worn = c.setdefault("worn", {})
    for slot in ALL_SLOTS:
        worn.setdefault(slot, None)
    return worn


# =========================================================
# QUERY HELPERS
# =========================================================

def worn_in_slot(c, slot):
    return c.get("worn", {}).get(slot)


def is_wearing(c, template_id):
    return any(
        item and item.get("template_id") == template_id
        for item in c.get("worn", {}).values()
    )


def worn_summary(c):
    """Return {slot: {template_id, name, dirty}} for occupied slots only."""
    result = {}
    for slot, item in c.get("worn", {}).items():
        if item:
            result[slot] = {
                "template_id": item.get("template_id"),
                "name":        item.get("name"),
                "dirty":       item.get("dirty", False),
                "model":       item.get("model"),
                "bone":        item.get("bone"),
            }
    return result


# =========================================================
# INVENTORY STACK HELPERS
# =========================================================

def _find_stack(inventory, template_id, dirty):
    """Find an existing stackable stack for this template+dirty combo."""
    for item in inventory:
        if (
            item.get("template_id") == template_id
            and item.get("dirty", False) == dirty
            and item.get("stackable", False)
            and item.get("quantity", 1) < item.get("max_stack", 99)
        ):
            return item
    return None


def _add_to_inventory(c, item):
    """
    Add item back to c["inventory"], merging into an existing stack if possible.
    """
    inv = c.setdefault("inventory", [])
    tid   = item.get("template_id")
    dirty = item.get("dirty", False)

    if item.get("stackable", False) and tid:
        stack = _find_stack(inv, tid, dirty)
        if stack:
            stack["quantity"] = stack.get("quantity", 1) + item.get("quantity", 1)
            return

    # Add as new item (ensure quantity field)
    if "quantity" not in item:
        item["quantity"] = 1
    inv.append(item)


def _take_one_from_inventory(c, item_id):
    """
    Remove and return one instance of an item from inventory.
    If quantity > 1, decrements and returns a single-quantity clone.
    """
    inv = c.get("inventory", [])
    for i, item in enumerate(inv):
        if item.get("id") == item_id:
            qty = item.get("quantity", 1)
            if qty > 1:
                item["quantity"] -= 1
                # Return a single-unit clone
                clone = {**item, "quantity": 1}
                import uuid
                clone["id"] = f"item_{item.get('template_id', 'x')}_{uuid.uuid4().hex[:6]}"
                return clone
            else:
                inv.pop(i)
                return item
    return None


# =========================================================
# PUT ON CLOTHING
# =========================================================

def put_on_clothing(c, world, item_id):
    """
    Equip an item from inventory to its clothing slot.

    - If slot is empty: wear it.
    - If slot is occupied: swap — old item goes back to inventory.

    Returns {"success": bool, "swapped_off": item | None, "reason": str}
    """
    ensure_worn(c)

    item = _take_one_from_inventory(c, item_id)
    if not item:
        return {"success": False, "swapped_off": None, "reason": "item_not_in_inventory"}

    slot = item.get("slot")
    if not slot or slot not in CLOTHING_SLOTS:
        # Not a wearable — put it back
        _add_to_inventory(c, item)
        return {"success": False, "swapped_off": None, "reason": "not_wearable"}

    worn = c["worn"]
    displaced = worn.get(slot)

    # Wear the new item
    worn[slot] = item

    # Return displaced item to inventory
    if displaced:
        _add_to_inventory(c, displaced)

    return {
        "success":     True,
        "slot":        slot,
        "worn":        item,
        "swapped_off": displaced,
        "reason":      "ok",
    }


# =========================================================
# TAKE OFF CLOTHING
# =========================================================

def take_off_clothing(c, world, slot):
    """
    Remove worn item from slot, return it to inventory.
    Returns the item that was removed, or None.
    """
    ensure_worn(c)
    worn = c["worn"]
    item = worn.get(slot)
    if not item:
        return None

    worn[slot] = None
    _add_to_inventory(c, item)
    return item


def undress_all(c, world):
    """Strip all worn clothing back into inventory."""
    ensure_worn(c)
    removed = []
    for slot in ALL_SLOTS:
        item = take_off_clothing(c, world, slot)
        if item:
            removed.append(item)
    return removed


# =========================================================
# DIRTY STATE
# =========================================================

def mark_item_dirty(item):
    """Mark any item (worn or in inventory) as dirty."""
    if item and "dirty" in item:
        item["dirty"] = True


def launder_item(item):
    """Clean an item."""
    if item:
        item["dirty"] = False


def launder_inventory(c, category=None):
    """Clean all items in inventory (optionally filtered by category)."""
    for item in c.get("inventory", []):
        if category and item.get("category") != category:
            continue
        if "dirty" in item:
            item["dirty"] = False


def launder_worn(c):
    """Clean all currently worn clothing."""
    for item in c.get("worn", {}).values():
        if item:
            launder_item(item)


def tick_clothing_dirty(c, world):
    """
    Called periodically: worn clothes accumulate dirt over time.
    Each worn item has a small chance of becoming dirty per tick.
    """
    import random
    for item in c.get("worn", {}).values():
        if item and not item.get("dirty", True):
            # ~1% chance per slow tick (≈ every 30s sim time)
            if random.random() < 0.01:
                item["dirty"] = True


# =========================================================
# OUTFIT STYLE SCORE
# =========================================================

def outfit_style_score(c):
    """
    Average style score across all worn clothing pieces.
    Dirty items reduce the effective style.
    """
    worn_items = [v for v in c.get("worn", {}).values() if v]
    if not worn_items:
        return 0.0
    scores = []
    for item in worn_items:
        base  = item.get("style", 0.5)
        dirty = item.get("dirty", False)
        scores.append(base * 0.4 if dirty else base)
    return round(sum(scores) / len(scores), 3)
