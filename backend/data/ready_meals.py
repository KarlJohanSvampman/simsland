"""
Ready-made complete dishes (docs/food_system.md, section 7): what a shop sells in the freezer and chiller aisles, and what a takeout
delivers. Cheaper than cooking the same thing, lower on the health scale, so they taste better and are more moreish.

  calories       one portion
  fat_pct        share of those calories that is fat, 0..1
  health         0..1 on the same scale as a cooked dish (systems/food_scoring.py)
  spice_taste    what the seasoning adds to the taste
  store_price    on a shelf (cold: needs the microwave)          takeout_price  delivered (warm, for a while)
"""

READY_MEALS = {
    "frozen_lasagna":    {"name": "Frozen lasagna",       "calories": 520, "fat_pct": 0.42, "health": 0.30, "spice_taste": 0.06, "store_price": 2.8, "takeout_price": None},
    "ready_curry":       {"name": "Ready curry and rice", "calories": 560, "fat_pct": 0.36, "health": 0.38, "spice_taste": 0.08, "store_price": 2.6, "takeout_price": None},
    "instant_noodles":   {"name": "Instant noodle cup",   "calories": 380, "fat_pct": 0.38, "health": 0.15, "spice_taste": 0.10, "store_price": 0.9, "takeout_price": None},
    "frozen_pizza":      {"name": "Frozen pizza",         "calories": 780, "fat_pct": 0.45, "health": 0.18, "spice_taste": 0.06, "store_price": 3.2, "takeout_price": None},
    "ready_soup":        {"name": "Ready soup",           "calories": 240, "fat_pct": 0.25, "health": 0.52, "spice_taste": 0.04, "store_price": 1.8, "takeout_price": None},
    "chicken_ready":     {"name": "Ready chicken and veg", "calories": 460, "fat_pct": 0.30, "health": 0.45, "spice_taste": 0.05, "store_price": 3.4, "takeout_price": None},
    "takeout_burger":    {"name": "Burger and fries",     "calories": 1050, "fat_pct": 0.48, "health": 0.06, "spice_taste": 0.08, "store_price": None, "takeout_price": 11.0},
    "takeout_pizza":     {"name": "Takeout pizza",        "calories": 900, "fat_pct": 0.42, "health": 0.12, "spice_taste": 0.07, "store_price": None, "takeout_price": 12.0},
    "takeout_curry":     {"name": "Takeout curry",        "calories": 820, "fat_pct": 0.40, "health": 0.25, "spice_taste": 0.10, "store_price": None, "takeout_price": 13.0},
    "takeout_sushi":     {"name": "Takeout sushi",        "calories": 560, "fat_pct": 0.22, "health": 0.62, "spice_taste": 0.04, "store_price": None, "takeout_price": 15.0},
}

STORE_MEALS = [tid for tid, m in READY_MEALS.items() if m["store_price"]]
TAKEOUT_MEALS = [tid for tid, m in READY_MEALS.items() if m["takeout_price"]]
