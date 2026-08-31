"""
systems/darknet.py

One shared darknet listing board, reachable from both phone and
computer (see action_router.py's routes + personal_items.py's
darknet_market phone app). Real sellers (drug_producer/drug_dealer_mid,
hacker, fraudster, hitman/torpedo, private_investigator) post real
listings. Drugs ship by real mail (procurement.py::schedule_delivery_
item) -- every other category resolves as a real, synchronous trade,
the same "resolve now, real consequences" precedent commission_crime()
already established in systems/crime.py.
"""

import random
import uuid

LISTING_POST_CHANCE = 0.05  # per eligible seller, per daily tick
MAX_LISTINGS_PER_SELLER = 3
DRUG_RETAIL_MARKUP = 1.4

_SELLER_CATEGORY = {
    "drug_producer":        "drugs",
    "drug_dealer_mid":      "drugs",
    "hacker":                "hacking_service",   # rolls stolen_data sometimes
    "fraudster":             "fake_id",           # rolls counterfeit_money sometimes
    "hitman":                "hitman_service",
    "torpedo":               "hitman_service",
    "private_investigator":  "private_investigation",
}


# =========================================================
# LISTING GENERATION (daily cadence)
# =========================================================

def generate_darknet_listings(world):
    listings = world.setdefault("darknet_listings", [])
    for c in world.get("characters", {}).values():
        job_tid = c.get("job_template_id") or (c.get("job") or {}).get("id")
        category = _SELLER_CATEGORY.get(job_tid)
        if not category:
            continue
        if sum(1 for l in listings if l["seller_id"] == c["id"]) >= MAX_LISTINGS_PER_SELLER:
            continue
        if random.random() > LISTING_POST_CHANCE:
            continue
        listing = _build_listing(c, job_tid, category, world)
        if listing:
            listings.append(listing)


def _build_listing(c, job_tid, category, world):
    tick = world.get("tick", 0)
    base = {"id": f"dl_{uuid.uuid4().hex[:8]}", "seller_id": c["id"],
            "category": category, "posted_tick": tick}

    if category == "drugs":
        drug_type = c.get("production_drug_type") or random.choice(["amphetamine", "heroin", "weed"])
        from systems.crime import CRIME_PROFILES
        lo, hi = CRIME_PROFILES.get(job_tid, {}).get("cash_range", (100, 400))
        base.update({
            "item_template_id": drug_type,
            "price": round(random.uniform(lo, hi) / 8 * DRUG_RETAIL_MARKUP, 2),
            "title": f"{drug_type.title()} -- bulk available",
        })
        return base

    if category == "hitman_service":
        base.update({
            "kind":  job_tid,
            "price": {"torpedo": 300.0, "hitman": 5000.0}.get(job_tid, 1000.0),
            "title": "Wet work -- discreet" if job_tid == "hitman" else "Muscle for hire -- discreet",
        })
        return base

    if category == "private_investigation":
        base.update({"price": 400.0, "title": "Surveillance services -- discreet, thorough"})
        return base

    if category == "hacking_service" and random.random() < 0.4:
        base.update({"category": "stolen_data", "price": 150.0,
                     "title": "Stolen accounts & personal data"})
        return base
    if category == "hacking_service":
        base.update({"price": 350.0, "title": "Hacking-as-a-service -- name your target"})
        return base

    if category == "fake_id" and random.random() < 0.4:
        base.update({"category": "counterfeit_money", "price": 200.0, "face_value": 500.0,
                     "title": "Counterfeit cash bundle"})
        return base
    if category == "fake_id":
        others = [oc for oc in world.get("characters", {}).values() if oc["id"] != c["id"]]
        if not others:
            return None
        target = random.choice(others)
        base.update({"price": 250.0, "target_id": target["id"],
                     "title": f"Fake ID -- {target.get('name', 'unknown')}"})
        return base

    return None


# =========================================================
# ORDERING
# =========================================================

def order_darknet_listing(buyer, world, listing_id, target_id=None):
    """Single entry point. target_id is required for hitman_service/
    private_investigation listings (both need a real target); ignored
    for every other category."""
    listings = world.get("darknet_listings", [])
    listing = next((l for l in listings if l["id"] == listing_id), None)
    if not listing:
        return {"ok": False, "reason": "not_found"}
    if listing["seller_id"] == buyer["id"]:
        return {"ok": False, "reason": "own_listing"}

    if listing["category"] in ("hitman_service", "private_investigation"):
        return _order_targeted_service(buyer, world, listing, target_id)

    from systems.personal_items import pay_from_wallet, add_cash
    price = listing.get("price", 0.0)
    if not pay_from_wallet(buyer, world, price):
        return {"ok": False, "reason": "cant_afford"}

    seller = world.get("characters", {}).get(listing["seller_id"])
    if seller:
        add_cash(seller, price)
        seller["criminal_standing"] = seller.get("criminal_standing", 0.0) + 3.0

    result = _fulfill_listing(buyer, seller, listing, world)
    listings.remove(listing)
    return {"ok": True, "category": listing["category"], "result": result}


def _order_targeted_service(buyer, world, listing, target_id):
    if not target_id:
        return {"ok": False, "reason": "target_required"}
    seller = world.get("characters", {}).get(listing["seller_id"])
    target = world.get("characters", {}).get(target_id)
    if not seller or not target:
        return {"ok": False, "reason": "not_found"}

    if listing["category"] == "hitman_service":
        from systems.crime import commission_crime
        return commission_crime(buyer, target, seller, world, kind=listing["kind"])

    # private_investigation -- real infiltration/stakeout mechanic lands
    # in systems/stealth.py; this records a real, tracked assignment
    # (world["pi_assignments"]) rather than a silent stub, so it's not a
    # dead end even before that mechanic exists.
    from systems.personal_items import pay_from_wallet, add_cash
    price = listing.get("price", 0.0)
    if not pay_from_wallet(buyer, world, price):
        return {"ok": False, "reason": "cant_afford"}
    add_cash(seller, price)
    world.setdefault("pi_assignments", []).append({
        "id":              f"pi_{uuid.uuid4().hex[:8]}",
        "investigator_id": seller["id"],
        "client_id":       buyer["id"],
        "target_id":       target_id,
        "posted_tick":     world.get("tick", 0),
        "status":          "pending",
    })
    return {"ok": True, "outcome": "assigned"}


def _fulfill_listing(buyer, seller, listing, world):
    category = listing["category"]
    tick = world.get("tick", 0)

    if category == "drugs":
        household = world.get("households", {}).get(buyer.get("household_id"))
        if household:
            from systems.procurement import schedule_delivery_item
            schedule_delivery_item(household, listing["item_template_id"], world,
                                    buyer_id=buyer["id"], price=listing["price"])
        return "delivery_scheduled"

    if category == "stolen_data":
        target_pool = [c for c in world.get("characters", {}).values()
                        if c["id"] not in (buyer["id"], seller["id"] if seller else None)
                        and c.get("secrets")]
        if not target_pool:
            return "no_data_available"
        target = random.choice(target_pool)
        secret = random.choice(target["secrets"])
        from systems.secrets import reveal_secret
        reveal_secret(secret, buyer["id"], world, method="hacked")
        return {"target_id": target["id"], "secret_id": secret["id"]}

    if category == "fake_id":
        target_id = listing.get("target_id")
        target = world.get("characters", {}).get(target_id)
        from systems.personal_items import make_item, add_item
        fake = make_item("fake_id", world=world)
        fake["impersonates_id"] = target_id
        fake["impersonates_name"] = target.get("name") if target else "Unknown"
        add_item(buyer, fake)
        return {"target_id": target_id}

    if category == "counterfeit_money":
        from systems.personal_items import add_cash
        face_value = listing.get("face_value", 0.0)
        add_cash(buyer, face_value)
        world.setdefault("incidents", []).append({
            "id": f"inc_{uuid.uuid4().hex[:8]}", "type": "counterfeit_money",
            "tick": tick, "participants": [buyer["id"]], "arrest_checked": False,
        })
        return {"face_value": face_value}

    return None


def browse_darknet_listings(world, category=None, limit=15):
    listings = world.get("darknet_listings", [])
    if category:
        listings = [l for l in listings if l["category"] == category]
    return sorted(listings, key=lambda l: -l["posted_tick"])[:limit]
