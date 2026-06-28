import random
from data.products import PRODUCTS, tradeable_products

# =========================================================
# CATEGORY PRICE MULTIPLIERS
# Stored in world["market"]["category_multipliers"]
# Each drifts independently each tick.
# =========================================================

CATEGORY_DEFAULTS = {
    "groceries":   1.0,
    "hygiene":     1.0,
    "cleaning":    1.0,
    "appliances":  1.0,
    "furniture":   1.0,
    "clothing":    1.0,
    "electronics": 1.0,
}

# How fast each category drifts per update (std dev of random walk step)
CATEGORY_VOLATILITY = {
    "groceries":   0.004,
    "hygiene":     0.002,
    "cleaning":    0.002,
    "appliances":  0.006,
    "furniture":   0.005,
    "clothing":    0.005,
    "electronics": 0.008,
}

# Slow mean-reversion strength (pulls multiplier back toward 1.0)
REVERSION_STRENGTH = 0.005


# =========================================================
# ENSURE DEFAULTS
# =========================================================

def ensure_market_defaults(market):
    mults = market.setdefault("category_multipliers", {})
    for cat, default in CATEGORY_DEFAULTS.items():
        mults.setdefault(cat, default)

    # Legacy compatibility: keep top-level food/medicine/etc for cost_of_living
    market.setdefault("food",        {"price": 10.0, "supply": 1.0, "demand": 1.0})
    market.setdefault("medicine",    {"price": 25.0, "supply": 1.0, "demand": 1.0})
    market.setdefault("housing",     {"price": 1000.0, "supply": 1.0, "demand": 1.0})
    market.setdefault("fuel",        {"price": 5.0, "supply": 1.0, "demand": 1.0})
    market.setdefault("utilities",   {"price": 100.0, "supply": 1.0, "demand": 1.0})


# =========================================================
# GET LIVE ITEM PRICE
# Returns base_price * category_multiplier for any product
# =========================================================

def get_item_price(world, product_id):
    product = PRODUCTS.get(product_id)
    if not product:
        return None
    base = product.get("price", 0)
    cat  = product.get("category", "")
    mult = (
        world.get("market", {})
             .get("category_multipliers", {})
             .get(cat, 1.0)
    )
    return round(base * mult, 2)


# =========================================================
# UPDATE MARKET — called each MEDIUM tick
# =========================================================

def update_market(world):
    market = world.setdefault("market", {})
    ensure_market_defaults(market)
    mults = market["category_multipliers"]

    for cat in CATEGORY_DEFAULTS:
        vol  = CATEGORY_VOLATILITY.get(cat, 0.004)
        step = random.gauss(0, vol)
        # Mean reversion
        step -= REVERSION_STRENGTH * (mults[cat] - 1.0)
        mults[cat] = round(max(0.5, min(2.5, mults[cat] + step)), 4)

    # Nudge legacy food price to stay consistent with groceries multiplier
    market["food"]["price"] = round(10.0 * mults["groceries"], 2)

    # Update cost_of_living_index
    world["environment"]["cost_of_living_index"] = max(
        0.5, min(2.0, market["food"]["price"] / 10.0)
    )


# =========================================================
# APPLY NEWS SPIKE TO CATEGORY
# Called by stock_market when news tags match categories
# =========================================================

NEWS_TAG_TO_CATEGORY = {
    "consumer":      ["groceries", "clothing"],
    "trade":         ["electronics", "appliances"],
    "economy":       ["furniture", "appliances", "electronics"],
    "environment":   ["appliances"],
    "technology":    ["electronics"],
    "infrastructure":["appliances", "furniture"],
    "labor":         ["appliances", "furniture", "clothing"],
}

def apply_news_to_market(world, news_tags, sentiment):
    market = world.setdefault("market", {})
    mults  = market.get("category_multipliers", {})
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
# LEGACY STUBS (keep sim_loop import working)
# =========================================================

def produce(world):
    pass  # supply/demand model removed

def consume_households(world):
    pass  # demand tracking removed; expenses handled by economy.apply_expenses
