"""
Procurement system.

Characters buy things from the market catalog:
  - consumable resource items (groceries, hygiene) → household storage
  - discrete items (clothing, electronics, dishware) → make_item() → c["inventory"]
  - props requiring assembly → make_assembly_box() → c["inventory"]
  - props not requiring assembly → scheduled delivery → placed in world
"""

import random

from systems.market import browse_catalog, get_price
from systems.household_storage import add_household_resource
from systems.resource_runtime import create_resource
from systems.personal_items import add_item, make_item


# =========================================================
# PROCUREMENT METHODS
# =========================================================

PROCUREMENT_METHODS = ["in_person", "online"]


def create_procurement_request(c, category, priority=0.5, budget=None, quantity=1):
    return {
        "category":   category,
        "priority":   priority,
        "budget":     budget,
        "quantity":   quantity,
        "created_by": c["id"],
    }


# =========================================================
# CHOOSE METHOD
# =========================================================

def choose_procurement_method(c, request):
    traits    = c.get("traits", [])
    energy    = c.get("needs", {}).get("energy", 1)
    category  = request.get("category")

    if category in ("furniture", "appliances"):
        return "online"
    if energy < 0.25:
        return "online"
    if "lazy" in traits and random.random() < 0.7:
        return "online"
    return random.choice(["in_person", "online"])


# =========================================================
# CHOOSE FROM CATALOG
# =========================================================

def choose_from_catalog(c, world, category, budget=None, item_type=None):
    """
    Pick the best catalog entry within budget, scored by character traits.
    Returns the full catalog entry dict (with 'id' key), or None.
    """
    money = c.get("money", 0)
    if budget is None:
        budget = money

    candidates = browse_catalog(world, category=category, budget=budget, item_type=item_type)
    if not candidates:
        return None

    traits = c.get("traits", [])
    scored = []

    for entry in candidates:
        score   = 1.0
        price   = entry["current_price"]
        quality = 0.5  # catalog entries don't have quality; use price as proxy

        if "frugal" in traits:
            score += 100.0 / max(1.0, price)
        if "materialistic" in traits:
            score += price / 500.0

        score += random.uniform(-0.3, 0.3)
        scored.append((entry, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0]


# =========================================================
# PURCHASE FROM CATALOG
# =========================================================

def purchase_from_catalog(c, household, world, catalog_id, method="in_person"):
    """
    Buy one unit of catalog_id.

    Outcome depends on entry type:
      resource_type set → deposits resource into household storage
      type == "item" (no resource_type) → make_item() → c["inventory"]
      type == "prop" + requires_assembly → make_assembly_box() → c["inventory"]
      type == "prop" + not requires_assembly → schedule_delivery_prop()
    """
    from systems.assembly import make_assembly_box, make_tile_box

    catalog = world.get("market", {}).get("catalog", {})
    entry   = catalog.get(catalog_id)
    if not entry:
        return False

    price = entry["current_price"]
    if c.get("money", 0) < price:
        return False

    c["money"] = round(c["money"] - price, 2)

    # --- Resource consumable (groceries, hygiene, bulk drinks) ---
    if entry.get("resource_type"):
        resource = create_resource(
            entry["resource_type"],
            quantity=entry.get("quantity", 1),
            quality=0.6,
            container=entry.get("storage_container", "storage"),
        )
        add_household_resource(household, resource)
        return True

    # --- Floor tile material → stackable tile assembly box ---
    if entry["type"] == "tile":
        quantity = entry.get("quantity", 1)
        box = make_tile_box(entry["material_template"], world, quantity=quantity)
        add_item(c, box)
        return True

    # --- Prop ---
    if entry["type"] == "prop":
        if entry.get("requires_assembly"):
            box = make_assembly_box(catalog_id, world)
            add_item(c, box)
        else:
            schedule_delivery_prop(household, catalog_id, world)
        return True

    # --- Discrete item ---
    if method == "online":
        schedule_delivery_item(household, catalog_id, world)
    else:
        item = make_item(catalog_id)
        add_item(c, item)

    return True


# =========================================================
# DELIVERY SCHEDULING
# =========================================================

def schedule_delivery_item(household, catalog_id, world):
    world.setdefault("deliveries", []).append({
        "household_id": household["id"],
        "type":         "item",
        "catalog_id":   catalog_id,
        "arrival_tick": world["tick"] + random.randint(12, 48) * 3600,
        "status":       "in_transit",
    })


def schedule_delivery_prop(household, catalog_id, world):
    world.setdefault("deliveries", []).append({
        "household_id": household["id"],
        "type":         "prop",
        "catalog_id":   catalog_id,
        "arrival_tick": world["tick"] + random.randint(24, 72) * 3600,
        "status":       "in_transit",
    })


# =========================================================
# DELIVERY PROCESSING  (called each SLOW tick)
# =========================================================

def process_deliveries(world):
    tick      = world.get("tick", 0)
    pending   = world.get("deliveries", [])
    remaining = []

    for delivery in pending:
        if delivery.get("arrival_tick", 0) > tick:
            remaining.append(delivery)
            continue

        hid   = delivery.get("household_id")
        h     = world.get("households", {}).get(hid)
        if not h:
            continue

        cid   = delivery.get("catalog_id")
        dtype = delivery.get("type")

        if dtype == "item":
            _deliver_item(h, cid, world)
        elif dtype == "prop":
            _deliver_prop(h, cid, world)

    world["deliveries"] = remaining


def _deliver_item(household, catalog_id, world):
    """Deposit delivered item into the household owner's inventory."""
    from systems.personal_items import add_item, make_item
    members = household.get("members", [])
    if not members:
        return
    # Give to first available member
    chars = world.get("characters", {})
    for cid in members:
        c = chars.get(cid)
        if c:
            item = make_item(catalog_id)
            add_item(c, item)
            return


def _deliver_prop(household, catalog_id, world):
    """Place delivered prop in the household's home building."""
    home_id = household.get("home_id")
    if not home_id:
        return

    prop_templates = (
        world.get("definitions", {})
             .get("prop_templates", {})
    )
    template = prop_templates.get(catalog_id)
    if not template:
        return

    import uuid
    world.setdefault("props", []).append({
        "id":          f"prop_{catalog_id}_{uuid.uuid4().hex[:6]}",
        "template":    catalog_id,
        "building_id": home_id,
        "x":           0,
        "y":           0,
        "rotation":    0,
        "state":       {"reserved_by": [], "dirty": False},
    })


# =========================================================
# LEGACY COMPAT — determine_container still used internally
# =========================================================

def determine_container(resource_type):
    if resource_type in ("FOOD_PROTEIN", "FOOD_VEGETABLE", "MEAL",
                         "STORED_MEAL", "PROCESSED_MEAL", "DRINK_MILK"):
        return "fridge"
    if resource_type in ("FO