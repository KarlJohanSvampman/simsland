"""
Market system.

world["market"]["catalog"] = {
    template_id: {
        "type":              "item" | "prop",
        "name":              str,
        "category":          str,
        "base_price":        float,
        "current_price":     float,   # base_price * category_multiplier
        "requires_assembly": bool,    # props only
        "resource_type":     str,     # items only — bulk consumable
        "storage_container": str,     # items only
        "quantity":          int,     # items only
    }
}

world["market"]["category_multipliers"] = {
    "groceries": 1.0,
    "clothing":  1.0,
    ...
}
"""

import random
import math
from data.item_templates import ITEM_TEMPLATES

# =========================================================
# CATEGORY DRIFT CONFIG
# =========================================================

CATEGORY_VOLATILITY = {
    "groceries":   0.004,
    "hygiene":     0.002,
    "cleaning":    0.002,
    "appliances":  0.006,
    "furniture":   0.005,
    "clothing":    0.005,
    "electronics": 0.008,
    "dishware":    0.002,
    "linen":       0.003,
    "drink":       0.003,
    "food":        0.004,
}

REVERSION_STRENGTH = 0.005


# =========================================================
# INIT MARKET CATALOG
# Called once on world creation (and on load if missing)
# =========================================================

def init_market_catalog(world):
    """
    Populate world["market"]["catalog"] from:
      - ITEM_TEMPLATES entries that have a base_price
      - world["definitions"]["prop_templates"] entries that have a base_price
    """
    market = world.setdefault("market", {})
    catalog = market.setdefault("catalog", {})
    mults   = market.setdefault("category_multipliers", {})

    # Seed category multipliers
    all_categories = set(CATEGORY_VOLATILITY.keys())
    for cat in all_categories:
        mults.setdefault(cat, 1.0)

    # Item templates
    for tid, t in ITEM_TEMPLATES.items():
        if "base_price" not in t:
            continue
        if tid in catalog:
            continue
        cat = t.get("category", "misc")
        bp  = float(t["base_price"])
        catalog[tid] = {
            "type":              "item",
            "name":              t["name"],
            "category":          cat,
            "base_price":        bp,
            "current_price":     round(bp * mults.get(cat, 1.0), 2),
            "requires_assembly": False,
            "resource_type":     t.get("resource_type"),
            "storage_container": t.get("storage_container"),
            "quantity":          t.get("quantity", 1),
        }

    # Prop templates
    prop_templates = (
        world.get("definitions", {})
             .get("prop_templates", {})
    )
    for pid, pt in prop_templates.items():
        if "base_price" not in pt:
            continue
        if pid in catalog:
            continue
        cat = pt.get("category", "furniture")
        bp  = float(pt["base_price"])
        catalog[pid] = {
            "type":              "prop",
            "name":              pt.get("name", pid),
            "category":          cat,
            "base_price":        bp,
            "current_price":     round(bp * mults.get(cat, 1.0), 2),
            "requires_assembly": pt.get("requires_assembly", False),
            "resource_type":     None,
            "storage_container": None,
            "quantity":          1,
        }


# =========================================================
# ENSURE DEFAULTS (called from schema_defaults)
# =========================================================

def ensure_market_defaults(market):
    mults = market.setdefault("category_multipliers", {})
    for cat in CATEGORY_VOLATILITY:
        mults.setdefault(cat, 1.0)

    # Legacy cost-of-living anchor
    food_entry = market.setdefault("food", {"price": 10.0, "supply": 1.0, "demand": 1.0})
    food_entry.setdefault("price", 10.0)


# =========================================================
# PRICE HELPERS
# =========================================================

def get_price(world, template_id):
    """Current market price for a template_id (item or prop)."""
    entry = world.get("market", {}).get("catalog", {}).get(template_id)
    return entry["current_price"] if entry else None


def get_item_price(world, template_id):
    """Alias kept for compatibility."""
    return get_price(world, template_id)


# =========================================================
# BROWSE CATALOG
# =========================================================

def browse_catalog(world, category=None, budget=None, item_type=None):
    """
    Return list of catalog entries the character can afford.

    item_type: "item" | "prop" | None (both)
    """
    catalog = world.get("market", {}).get("catalog", {})
    results = []
    for tid, entry in catalog.items():
        if item_type and entry["type"] != item_type:
            continue
        if category and entry["category"] != category:
            continue
        if budget is not None and entry["current_price"] > budget:
            continue
        results.append({"id": tid, **entry})
    return results


# =========================================================
# UPDATE MARKET (called each MEDIUM tick)
# =========================================================

def update_market(world):
    market = world.setdefault("market", {})
    ensure_market_defaults(market)
    mults   = market["category_multipliers"]
    catalog = market.get("catalog", {})

    # Drift category multipliers
    for cat in CATEGORY_VOLATILITY:
        if cat not in mults:
            mults[cat] = 1.0
        vol  = CATEGORY_VOLATILITY.get(cat, 0.004)
        step = random.gauss(0, vol)
        step -= REVERSION_STRENGTH * (mults[cat] - 1.0)
        mults[cat] = round(max(0.5, min(2.5, mults[cat] + step)), 4)

    # Refresh current_price in catalog
    for entry in catalog.values():
        cat  = entry.get("category", "misc")
        mult = mults.get(cat, 1.0)
        entry["current_price"] = round(entry["base_price"] * mult, 2)

    # Update cost_of_living_index via groceries multiplier
    grocery_mult = mults.get("groceries", 1.0)
    market["food"]["price"] = round(10.0 * grocery_mult, 2)
    world["environment"]["cost_of_living_index"] = max(
        0.5, min(2.0, grocery_mult)
    )


# =========================================================
# NEWS → MARKET REACTION
# =========================================================

NEWS_TAG_TO_CATEGORY = {
    "consumer":       ["groceries", "clothing"],
    "trade":          ["electronics", "appliances"],
    "economy":        ["furniture", "appliances", "electronics"],
    "environment":    ["appliances"],
    "technology":     ["electronics"],
    "infrastructure": ["appliances", "furniture"],
    "labor":          ["appliances", "furniture", "clothing"],
}

def apply_news_to_market(world, news_tags, sentiment):
    mults  = world.get("market", {}).get("category_multipliers", {})
    direction = 1 if sentiment == "positive" else -1 if sentiment == "negative" else 0
    if direction == 0:
        return
    for tag in news_tags:
        for cat in NEWS_TAG_TO_CATEGORY.get(tag, []):
            if cat in mults:
                mults[cat] = round(
                    max(0.5, min(2.5, mults[cat] + direction * random.uniform(0.01, 0.04))),
                    4
                )


# =========================================================
# LEGACY STUBS
# =========================================================

def produce(world):
    pass

def consume_households(world):
    pass
