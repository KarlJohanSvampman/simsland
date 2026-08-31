"""
systems/marketplace.py

Second-hand marketplace: sims sell/buy household furniture props to and
from each other (e.g. after redecorating). Reuses market.py's real
base-price lookup for valuation and procurement.py's real prop-delivery
shape for the buy side -- no new pricing or placement model.
"""

import uuid

RESALE_FACTOR = 0.45  # flat discount off retail -- real-world used-furniture economics


def estimate_avg_sell_value(world, template_id):
    """Read-only appraisal -- no listing side-effect. Used by a
    character to decide what to actually list at."""
    from systems.market import get_price
    price = get_price(world, template_id)
    if not price:
        return 0.0
    return round(price * RESALE_FACTOR, 2)


def list_prop_for_sale(c, world, prop_id, asking_price=None):
    """Removes prop_id from world["props"] (must belong to c's own
    household) and creates a real listing. Returns the listing dict, or
    None if the prop isn't found/owned."""
    props = world.get("props", [])
    prop = next((p for p in props if p.get("id") == prop_id), None)
    if not prop or prop.get("household_id") != c.get("household_id"):
        return None

    props.remove(prop)

    template_id = prop.get("template")
    if asking_price is None:
        asking_price = estimate_avg_sell_value(world, template_id)

    listing = {
        "id":                  f"listing_{uuid.uuid4().hex[:8]}",
        "template_id":         template_id,
        "seller_household_id": c.get("household_id"),
        "seller_id":           c["id"],
        "asking_price":        asking_price,
        "posted_tick":         world.get("tick", 0),
        "condition_note":      prop.get("state", {}),
    }
    world.setdefault("marketplace_listings", []).append(listing)
    return listing


def buy_marketplace_listing(c, world, listing_id):
    """Pays the seller, removes the listing, and schedules real prop
    delivery into the buyer's household -- same shape as buying new
    furniture (procurement.py::schedule_delivery_prop)."""
    listings = world.get("marketplace_listings", [])
    listing = next((l for l in listings if l["id"] == listing_id), None)
    if not listing:
        return {"ok": False, "reason": "not_found"}

    if listing.get("seller_household_id") == c.get("household_id"):
        return {"ok": False, "reason": "own_listing"}

    from systems.personal_items import pay_from_wallet
    price = listing.get("asking_price", 0.0)
    if not pay_from_wallet(c, world, price):
        return {"ok": False, "reason": "cant_afford"}

    seller_household = world.get("households", {}).get(listing["seller_household_id"])
    if seller_household:
        seller_household["wealth"] = seller_household.get("wealth", 0) + price

    listings.remove(listing)

    buyer_household = world.get("households", {}).get(c.get("household_id"))
    if buyer_household:
        from systems.procurement import schedule_delivery_prop
        schedule_delivery_prop(buyer_household, listing["template_id"], world)

    return {"ok": True, "price": price, "template_id": listing["template_id"]}


def browse_listings(world, exclude_household_id=None, limit=10):
    listings = world.get("marketplace_listings", [])
    if exclude_household_id:
        listings = [l for l in listings if l.get("seller_household_id") != exclude_household_id]
    return sorted(listings, key=lambda l: -l["posted_tick"])[:limit]
