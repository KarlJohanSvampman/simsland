"""
systems/food_scoring.py -- what a dish is made of and how it scores (docs/food_system.md).

    units_needed(recipe, people)          {"protein": 2, "carb": 2, ...}   what to take from storage
    cook_minutes(recipe, people)          how long the cookware needs
    group_of(item)                        protein | carb | vitamin | dairy | bread | none | spice
    dish_from_items(items, people)        the finished dish: totals, per-portion numbers, health, taste, addictive
    reaction(taste)                       the honest word they would say about it

health 0..1 runs from unhealthy to nutritional. For simplicity the less nutritional a dish is, the better it tastes and the more
addictive it is; the more nutritional, the worse the taste. Spices only add taste.
"""

import math

from data.dishes import DISH_RECIPES

SPICE_BONUS_CAP = 0.15
IDEAL_VITAMIN_SHARE = 0.4
IDEAL_FAT_SHARE = 0.25
IDEAL_PORTION_KCAL = 600


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _template(item):
    from data.item_templates import get_template
    return get_template(item.get("template_id") or item.get("id")) or {}


def _field(item, key, default=0):
    v = item.get(key)
    return v if v is not None else _template(item).get(key, default)


def group_of(item):
    """The recipe group an item counts as: fruit and vegetables are both 'vitamin'."""
    if _field(item, "spice", False):
        return "spice"
    g = _field(item, "food_group", "none")
    return "vitamin" if g in ("fruit", "vegetable") else g


def recipe(recipe_id):
    return DISH_RECIPES.get(recipe_id)


def units_needed(rec, people):
    return {g: math.ceil(per * max(1, people)) for g, per in rec["per_person"].items()}


def cook_minutes(rec, people):
    return rec["minutes"] + rec.get("per_extra", 0) * (max(1, people) - 1)


def health_of(groups, calories, fat_cal, portions):
    """0 (unhealthy) .. 1 (nutritional) from the spread of groups, the vitamins, the fat share and the size of a portion."""
    units = sum(n for g, n in groups.items() if g != "spice")
    if not units:
        return 0.0
    covered = sum(1 for have in (groups.get("protein", 0) + groups.get("dairy", 0), groups.get("carb", 0) + groups.get("bread", 0),
                                 groups.get("vitamin", 0)) if have > 0)
    variety = covered / 3
    vitamin = _clamp((groups.get("vitamin", 0) / units) / IDEAL_VITAMIN_SHARE)
    fat_share = fat_cal / calories if calories else 0.0
    fat = 1 - _clamp((fat_share - IDEAL_FAT_SHARE) / 0.5)
    size = 1 - _clamp((calories / max(1, portions) - IDEAL_PORTION_KCAL) / IDEAL_PORTION_KCAL)
    return round(0.35 * variety + 0.30 * vitamin + 0.20 * fat + 0.15 * size, 3)


def taste_of(health, spice_taste=0.0, portions=1):
    """Worse the more nutritional it is; spices lift it, capped."""
    bonus = min(SPICE_BONUS_CAP, 2 * spice_taste / max(1, portions))
    return round(_clamp(1 - 0.6 * health ** 2 + bonus), 3)


def addictive_of(health):
    return round((1 - health) ** 2, 3)


def reaction(taste):
    """What they honestly say: unhealthy food is great, medium is good or great, very nutritional food is bland."""
    if taste >= 0.85:
        return "great"
    if taste >= 0.65:
        return "good"
    if taste >= 0.45:
        return "fine"
    if taste >= 0.3:
        return "bland"
    return "not good"


def dish_from_items(items, people=1, name=None):
    """The finished dish from what went into the cookware (or onto the bread). `people` = portions it makes."""
    portions = max(1, people)
    groups, calories, fat_cal, spice_taste, ingredients = {}, 0.0, 0.0, 0.0, []
    group_kcal, group_fat = {}, {}
    for item in items:
        n = item.get("quantity", 1) or 1
        g = group_of(item)
        groups[g] = groups.get(g, 0) + n
        kcal = _field(item, "calories", 0) * n
        calories += kcal
        fat_cal += kcal * _field(item, "fat_pct", 0)
        group_kcal[g] = group_kcal.get(g, 0) + kcal
        group_fat[g] = group_fat.get(g, 0) + kcal * _field(item, "fat_pct", 0)
        spice_taste += _field(item, "spice_taste", 0) * n
        ingredients.append({"template_id": item.get("template_id") or item.get("id"), "quantity": n, "group": g})
    health = health_of(groups, calories, fat_cal, portions)
    taste = taste_of(health, spice_taste, portions)
    return {
        "name": name or "Dish", "portions": portions, "groups": groups, "ingredients": ingredients,
        "calories": round(calories), "fat_cal": round(fat_cal), "fat_pct": round(fat_cal / calories, 3) if calories else 0.0,
        "calories_per_portion": round(calories / portions), "fat_cal_per_portion": round(fat_cal / portions),
        "health": health, "taste": taste, "addictive": addictive_of(health), "spice_taste": round(spice_taste, 3),
        "group_kcal": {g: round(k, 1) for g, k in group_kcal.items()}, "group_fat": {g: round(f, 1) for g, f in group_fat.items()},
    }


def plate_from_dish(dish, weakness=None):
    """What ONE person actually puts on the plate. Carbs are often cooked apart, so the eater may take more meat and less carb;
    `weakness` = {"meat", "fat", "calories"} each -1..1 (a weakness for meat, for fat, for a big helping). The plate's calories stay
    near one portion unless the calories weakness is on; health and taste are scored on the mix actually eaten."""
    w = weakness or {}
    n = max(1, dish.get("portions", 1))
    kcal = {g: k / n for g, k in dish.get("group_kcal", {}).items()}
    fat = {g: f / n for g, f in dish.get("group_fat", {}).items()}
    units = {g: u / n for g, u in dish.get("groups", {}).items()}
    fat_share = {g: (fat.get(g, 0) / k if k else 0.0) for g, k in kcal.items()}

    meat = _clamp(w.get("meat", 0.0), -1.0, 1.0)
    src, dst = ("carb", "protein") if meat > 0 else ("protein", "carb")
    if abs(meat) > 0 and kcal.get(src) and dst in kcal:
        moved = kcal[src] * 0.4 * abs(meat)
        scale_src = (kcal[src] - moved) / kcal[src]
        scale_dst = (kcal[dst] + moved) / kcal[dst] if kcal[dst] else 1.0
        kcal[src], kcal[dst] = kcal[src] - moved, kcal[dst] + moved
        units[src] *= scale_src
        units[dst] *= scale_dst
    helping = _clamp(1 + 0.4 * _clamp(w.get("calories", 0.0), -1.0, 1.0), 0.6, 1.4)
    kcal = {g: k * helping for g, k in kcal.items()}
    units = {g: u * helping for g, u in units.items()}
    fat = {g: kcal[g] * fat_share[g] for g in kcal}
    calories = sum(kcal.values())
    fat_cal = sum(fat.values()) * (1 + 0.3 * _clamp(w.get("fat", 0.0), -1.0, 1.0))
    fat_cal = min(fat_cal, calories)
    health = health_of(units, calories, fat_cal, 1)
    taste = taste_of(health, dish.get("spice_taste", 0.0) / n)
    return {"calories": round(calories), "fat_cal": round(fat_cal), "fat_pct": round(fat_cal / calories, 3) if calories else 0.0,
            "health": health, "taste": taste, "addictive": addictive_of(health), "groups": {g: round(u, 2) for g, u in units.items()}}
