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

# A stored PROP (not an item -- see store_prop_in_container below, e.g. a
# vehicle's trunk holding a spare tire or a toolbox) always costs this
# many slots, flat, regardless of its own footprint -- props are bulkier
# than a typical item and never stack, unlike items (size * quantity,
# some stackable). Distinguished from an item entry by the "template"
# key -- props use "template", items use "template_id" (this codebase's
# existing, consistent naming split), so no new discriminator field is
# needed.
PROP_SLOT_COST = 6


def _is_prop_entry(entry):
    return "template" in entry


def _entry_slot_cost(entry, quantity=None):
    if _is_prop_entry(entry):
        return PROP_SLOT_COST
    qty = quantity if quantity is not None else entry.get("quantity", 1)
    return entry.get("size", 1) * qty


def slots_used(container):
    """Total slots occupied by items (and any stored props) inside the
    container."""
    return sum(_entry_slot_cost(entry) for entry in container.get("items", []))


def slots_available(container):
    return container.get("capacity", 0) - slots_used(container)


def can_fit(container, item, quantity=1):
    """
    Return True if `quantity` units of item fit in container. (For a
    prop entry, quantity is meaningless -- props never stack -- and is
    ignored.) Does not allow containers inside containers. accepted_categories,
    when present on the container (storage furniture / bag items --
    see ensure_prop_storage/ensure_item_container below), restricts what
    category of item may enter; accepted_templates is the narrower,
    single-(or few-)item-type version of the same idea -- a plant's fruit
    container only ever accepts its own yield_item (see systems/
    plants.py), regardless of category. Both are absent on the
    pre-existing container types (cardboard_box, backpack, toolbox,
    chest, bucket), so this is a no-op for all of those and behavior
    there is unchanged.
    """
    if item.get("type") == "container":
        return False  # no nesting (container-type items)
    if _is_prop_entry(item) and "capacity" in item:
        return False  # no nesting (a storage-capable prop, e.g. another trunk)
    accepted_categories = container.get("accepted_categories")
    if accepted_categories is not None and item.get("category") not in accepted_categories:
        return False
    accepted_templates = container.get("accepted_templates")
    if accepted_templates is not None and item.get("template_id") not in accepted_templates:
        return False
    needed = _entry_slot_cost(item, quantity)
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
# STORE / RETRIEVE A PROP (not an item)
# A prop being stored (e.g. a spare tire, a toolbox) stops being a
# world-positioned object -- add_to_container/remove_from_container
# above already handle a prop-shaped entry correctly once inside a
# container (see PROP_SLOT_COST/_is_prop_entry), but getting it in and
# out of world["props"] is a level these two wrappers handle.
# =========================================================

def store_prop_in_container(world, container, prop):
    """Removes `prop` from world["props"] and adds it to `container`.
    Strips x/y/room_id (no longer a world position while stored -- see
    retrieve_prop_from_container for restoring them). Returns
    add_to_container()'s result dict; on failure (no space / rejected),
    the prop is left untouched in world["props"]."""
    result = add_to_container(container, prop)
    if not result.get("success"):
        return result

    props = world.get("props", [])
    world["props"] = [p for p in props if p.get("id") != prop.get("id")]

    stored = container["items"][-1]
    stored["x"] = None
    stored["y"] = None
    stored["room_id"] = None
    return result


def retrieve_prop_from_container(world, container, prop_id, x, y, building_id=None):
    """Pops prop_id out of `container` and places it back into
    world["props"] at (x, y). Returns the restored prop dict, or None if
    prop_id wasn't found in this container."""
    removed = remove_from_container(container, prop_id)
    if not removed.get("success"):
        return None
    prop = removed["item"]
    prop["x"] = x
    prop["y"] = y
    if building_id is not None:
        prop["building_id"] = building_id
    world.setdefault("props", []).append(prop)
    return prop


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


# =========================================================
# LIQUID CAPACITY -- a watering can (or, in principle, any future
# glass/barrel/bucket-shaped container) filled at a Tap-tagged prop (see
# systems/chores.py::find_watering_can + action_router.py's
# use_tap-anchored fill activities). Reuses the same material/uses shape
# create_bucket() already established for paint -- a "how many
# applications/uses are left" countdown -- rather than a parallel field.
# The one real difference: a liquid container isn't consumed/removed
# from inventory when it hits 0 (see use_bucket() above); it just needs
# refilling.
# =========================================================

WATER_CAPACITY = {
    "watering_can": 10,
    "bucket": 10,
}


def fill_with_water(item, capacity=None):
    cap = capacity if capacity is not None else WATER_CAPACITY.get(item.get("template_id"), 1)
    item["material"] = "water"
    item["uses"] = cap
    return item


def use_water(item, amount=1):
    """Decrement uses by amount, floor at 0. Unlike use_bucket() (paint),
    the item stays in inventory when empty -- caller doesn't remove it,
    it just needs refilling at a tap again."""
    item["uses"] = max(0, item.get("uses", 0) - amount)
    return item["uses"]


def water_uses_remaining(item):
    return item.get("uses", 0) if item.get("material") == "water" else 0


def containers_in_inventory(c):
    """Return all container items in character's top-level inventory."""
    return [i for i in c.get("inventory", []) if i.get("type") == "container"]


# =========================================================
# STORAGE FURNITURE / BAG ITEMS / WORN CONTAINERS
# Extends the container model above (same "items"/"capacity" contract,
# so add_to_container/remove_from_container/can_fit/slots_used all work
# unmodified) to objects that aren't themselves container-type items:
# storage props (drawers, wardrobes, closets -- prop_templates' existing
# "storage" field) and container-capable regular items (a worn backpack,
# a carried basket -- item_templates' new "container" field). Lazily
# stamps "items"/"capacity"/"accepted_categories" onto the instance the
# first time it's touched, same pattern systems/plants.py uses for
# plant_state.
# =========================================================

def ensure_prop_storage(prop, world):
    """Prop instance (world["props"]) whose template has a `storage`
    field. Returns the prop (now container-shaped) or None if its
    template isn't storage-capable."""
    if "items" in prop and "capacity" in prop:
        return prop
    storage = (
        world.get("definitions", {})
        .get("prop_templates", {})
        .get(prop.get("template"), {})
        .get("storage")
    )
    if not storage:
        return None
    prop["items"] = prop.get("items", [])
    prop["capacity"] = storage.get("slots", 0)
    prop["accepted_categories"] = storage.get("accepted_categories")
    return prop


def ensure_item_container(item, world):
    """Item instance (inventory/held_stack/worn/placed) whose template
    has a `container` field -- e.g. a worn backpack. Returns the item
    (now container-shaped) or None if its template isn't container-
    capable."""
    if "items" in item and "capacity" in item:
        return item
    meta = (
        world.get("definitions", {})
        .get("item_templates", {})
        .get(item.get("template_id"), {})
        .get("container")
    )
    if not meta:
        return None
    item["items"] = item.get("items", [])
    item["capacity"] = meta.get("slots", 0)
    item["accepted_categories"] = meta.get("accepted_categories")
    return item


def resolve_container(c, world, container_id):
    """Finds a container by id across world props/placed_items and the
    given character's inventory/held_stack/worn -- covers pre-existing
    container-type items (cardboard_box/backpack/toolbox/chest/bucket,
    already container-shaped) as well as storage props and container-
    capable regular items (lazily equipped via ensure_prop_storage /
    ensure_item_container above). Returns None if container_id doesn't
    resolve to anything, or resolves to something that isn't actually a
    container."""
    if not container_id:
        return None

    for prop in world.get("props", []):
        if prop.get("id") == container_id:
            return ensure_prop_storage(prop, world)

    placed = world.get("placed_items", {})
    if container_id in placed:
        item = placed[container_id]
        return item if "items" in item else ensure_item_container(item, world)

    if c is not None:
        pools = [c.get("inventory", []), c.get("held_stack", [])]
        for item in [i for pool in pools for i in pool] + list(c.get("worn", {}).values()):
            if item and item.get("id") == container_id:
                return item if "items" in item else ensure_item_container(item, world)

    return None


def collect_item(c, world, source, item_id=None, dest_id=None):
    """Orchestrates the "collect"/"harvest" actions (action_router.py):
    pop one item out of `source`'s contents, then either deposit it into
    a resolved dest container (`dest_id`) or -- absent a dest -- into the
    character's held_stack (systems/item_stack.py's existing "stack in
    hand" mechanic). If the dest rejects the item (full / wrong
    category), it's put back in source rather than lost. Returns True on
    success."""
    if item_id is None:
        items = source.get("items", [])
        if not items:
            return False
        item_id = items[0]["id"]

    removed = remove_from_container(source, item_id)
    if not removed.get("success"):
        return False
    item = removed["item"]

    if dest_id:
        dest = resolve_container(c, world, dest_id)
        if dest:
            result = add_to_container(dest, item)
            if result.get("success"):
                return True
        # Dest missing or rejected the item -- put it back in source.
        source.setdefault("items", []).append(item)
        return False

    from systems.item_stack import add_to_held_stack
    add_to_held_stack(c, item)
    return True


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
