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
    from systems.body import body_energy
    energy    = body_energy(c)
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

def choose_from_catalog(c, world, category, budget=None, item_type=None, occasion=None):
    """
    Pick a catalog entry within budget via systems/choice.py -- the
    character's own traits already ride along in that call's prompt, so
    a "frugal" or "materialistic" character reasons about price the same
    way the old hand-rolled scoring approximated, without a separate
    heuristic to keep in sync. budget_friendly/premium tags (relative to
    this candidate pool's own price spread) let an occasion like
    "frugal" or "splurge" narrow the pool if a caller passes one.
    Returns the full catalog entry dict (with 'id' key), or None.
    """
    money = c.get("money", 0)
    if budget is None:
        budget = money

    candidates = browse_catalog(world, category=category, budget=budget, item_type=item_type,
                                 body_model=c.get("model"))
    if not candidates:
        return None

    prices = [e["current_price"] for e in candidates]
    lo, hi = min(prices), max(prices)
    options = []
    for entry in candidates:
        tags = []
        if hi > lo:
            frac = (entry["current_price"] - lo) / (hi - lo)
            tags.append("budget_friendly" if frac < 0.34 else "premium" if frac > 0.66 else "midrange")
        options.append({"id": entry["id"], "label": entry.get("name", entry["id"]), "tags": tags,
                          "_entry": entry})

    from systems.choice import choose
    picked = choose(c, world, category or "item", options, occasion=occasion)
    if not picked:
        return None
    return picked["_entry"]


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
    from systems.containers import create_bucket, create_container

    catalog = world.get("market", {}).get("catalog", {})
    entry   = catalog.get(catalog_id)
    if not entry:
        return False

    price = entry["current_price"]
    # Plain c["money"] stays the first-preference cash pool (unchanged
    # behavior for the common case) -- only when that alone can't cover
    # it do we fall back to the wallet's real cash/bank card/credit card
    # (systems/personal_items.py::pay_from_wallet(), same fallback order
    # systems/convenience_store.py's register checkout uses). Previously
    # this branch just failed the whole purchase outright whenever
    # c["money"] was short, even if the character was carrying a card
    # with plenty of room.
    if c.get("money", 0) >= price:
        c["money"] = round(c["money"] - price, 2)
    else:
        from systems.personal_items import pay_from_wallet
        if not pay_from_wallet(c, world, price):
            return False

    # --- Container (paint bucket, generic box, backpack, etc.) ---
    if entry["type"] == "container":
        sub_type = entry.get("sub_type", "cardboard_box")
        if sub_type == "bucket":
            item = create_bucket(entry["material_id"], world, uses=entry.get("bucket_uses", 10))
        else:
            item = create_container(sub_type=sub_type)
        if item:
            add_item(c, item)
        return True

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
        schedule_delivery_item(household, catalog_id, world, buyer_id=c["id"], price=price)
    else:
        # create_generated_item() is a superset of make_item() -- it only
        # makes an LLM call when the template has a "content_category"
        # (book/magazine/dvd/music_disc), so this is safe for every item.
        from systems.personal_items import create_generated_item
        item = create_generated_item(catalog_id, world, c=c, owner_id=c["id"])
        from systems.personal_items import record_item_history
        record_item_history(item, world, "purchased", by=c["id"], from_source="market_in_person",
                             price=price)
        add_item(c, item)

    return True


# =========================================================
# DELIVERY SCHEDULING
# =========================================================

def schedule_delivery_item(household, catalog_id, world, buyer_id=None, price=None):
    world.setdefault("deliveries", []).append({
        "household_id": household["id"],
        "type":         "item",
        "catalog_id":   catalog_id,
        "arrival_tick": world["tick"] + random.randint(12, 48) * 3600,
        "status":       "in_transit",
        # Carried through to _deliver_item()'s history entry -- who
        # actually placed the order, not just which household it lands in.
        "buyer_id":     buyer_id,
        "price":        price,
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
            _deliver_item(h, cid, world, buyer_id=delivery.get("buyer_id"), price=delivery.get("price"))
        elif dtype == "prop":
            _deliver_prop(h, cid, world)

    world["deliveries"] = remaining


def _deliver_item(household, catalog_id, world, buyer_id=None, price=None):
    """Deposit delivered item into the buyer's inventory (falling back to
    the first available member if the buyer is no longer in this
    household -- moved out, died, etc. -- since this fires much later
    than the original order)."""
    from systems.personal_items import add_item, create_generated_item, record_item_history
    members = household.get("members", [])
    if not members:
        return
    chars = world.get("characters", {})
    recipient = chars.get(buyer_id) if buyer_id in members else None
    if not recipient:
        recipient = next((chars[cid] for cid in members if cid in chars), None)
    if recipient:
        item = create_generated_item(catalog_id, world, c=recipient, owner_id=recipient["id"])
        record_item_history(item, world, "purchased", by=buyer_id or recipient["id"],
                             from_source="market_online", price=price)
        add_item(recipient, item)


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
        "household_id": household["id"],
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
    if resource_type in ("FOOD_CARB", "FOOD_SNACK", "FOOD_SPICE",
                         "DRINK_COFFEE", "DRINK_TEA", "DRINK_SOFT",
                         "DRINK_ALCOHOL"):
        return "pantry"
    if resource_type in ("HYGIENE", "TOILET_PAPER", "CLEANING"):
        return "bathroom"
    return "storage"
