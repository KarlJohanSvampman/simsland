"""
systems/food_habits.py -- tastes and dinner habits (docs/food_system.md, sections 6 and 8).

  * Taste: every character has a liking for each ingredient (-1..1). It starts as a small, personal, fixed lean and drifts with what
    they eat: a meal that tasted better than they expected nudges every ingredient in it up, a bad one nudges them down, and mere
    exposure helps a little. Dishes are judged by their ingredients, so the same pasta bolognese is a better meal for the person who
    has come to like beef and tomato. What they like decides which ingredients they take out of the stock and which recipe they pick.
  * Craving: eating very unhealthy (addictive) food raises a craving that pulls choices towards the same kind of food and fades
    when they eat well.
  * Stress: `c["stress"]` now and its average over the last week decide how dinner goes -- cook, or take the easy way out. A person
    who keeps eating poorly while stressed builds a comfort-eating habit, which lowers the stress it takes to give up cooking.
"""

import hashlib
import random

from data.ingredients import INGREDIENTS

LIKE_STEP = 0.06            # how far one meal moves a liking, at most
EXPOSURE = 0.01             # being served the same thing again, and not hating it
BASE_LEAN = 0.25            # a character's fixed starting lean for an ingredient is within +-this
WEEK = 7                    # days of stress that make "the week's average"
DINNER_HOURS = (17, 20)     # dinner is started from the earliest of these until the latest


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ---- taste ---------------------------------------------------------------------------------------------------------------------------------
def tastes(c):
    return c.setdefault("food_taste", {})


def _lean(c, template_id):
    """A fixed personal starting lean for an ingredient: the same character always begins with the same likes and dislikes."""
    h = hashlib.md5(f"{c.get('id')}:{template_id}".encode()).digest()[0] / 255.0
    return round((h * 2 - 1) * BASE_LEAN, 3)


def liking(c, template_id):
    t = tastes(c)
    if template_id not in t:
        t[template_id] = _lean(c, template_id)
    return t[template_id]


def dish_liking(c, ingredients):
    """How much the character likes what is in a dish (-1..1): the mean liking of its ingredients, weighted by amount; spices don't count."""
    total, weight = 0.0, 0.0
    for ing in ingredients or []:
        tid = ing.get("template_id")
        if tid not in INGREDIENTS or INGREDIENTS[tid].get("spice"):
            continue
        n = ing.get("quantity", 1) or 1
        total += liking(c, tid) * n
        weight += n
    return total / weight if weight else 0.0


def rank_fn(c):
    """For cookware.pull_ingredients: a higher number is taken first."""
    return lambda tid: liking(c, tid)


def personal_taste(c, item):
    """How good THIS person finds a plate or snack: the dish's own taste, moved by their likes for what is in it (0..1)."""
    base = item.get("taste")
    if base is None:
        from systems import food_scoring as fs
        base = fs.taste_of(fs.dish_from_items([item])["health"])
    return _clamp(base + 0.3 * dish_liking(c, item.get("ingredients") or [_self_ingredient(item)]), 0.0, 1.0)


def _self_ingredient(item):
    return {"template_id": item.get("template_id"), "quantity": 1}


# ---- craving and comfort eating -----------------------------------------------------------------------------------------------------------
def habits(c):
    return c.setdefault("food_habits", {"craving": 0.0, "comfort": 0.0, "stress_days": []})


def craving(c):
    return habits(c).get("craving", 0.0)


def on_meal(c, world, item):
    """After a meal: the likes drift, the craving and the comfort-eating habit move. `item` = the plate or snack that was eaten."""
    if not item or not (item.get("calories") or item.get("taste") is not None):
        return
    h = habits(c)
    ingredients = item.get("ingredients") or [_self_ingredient(item)]
    health = item.get("health")
    if health is None:
        from systems import food_scoring as fs
        health = fs.dish_from_items([item])["health"]
    addictive = item.get("addictive", (1 - health) ** 2)
    enjoyed = personal_taste(c, item) - 0.45          # better than a middling meal pleases, worse disappoints
    t = tastes(c)
    for ing in ingredients:
        tid = ing.get("template_id")
        if tid not in INGREDIENTS or INGREDIENTS[tid].get("spice"):
            continue
        liking(c, tid)
        t[tid] = round(_clamp(t[tid] + LIKE_STEP * enjoyed + (EXPOSURE if enjoyed > -0.2 else 0.0), -1.0, 1.0), 3)

    # junk is moreish: it raises the craving, a good meal lets it fade
    h["craving"] = round(_clamp(h.get("craving", 0.0) + 0.12 * addictive - (0.05 if health > 0.55 else 0.0) - 0.01, 0.0, 1.0), 3)

    # eating badly under stress is how comfort eating starts; eating well when calm undoes it
    stress = c.get("stress", 0) or 0
    if stress >= 55 and health < 0.45:
        h["comfort"] = round(_clamp(h.get("comfort", 0.0) + 0.08 * (0.5 + addictive), 0.0, 1.0), 3)
    elif stress < 40 and health >= 0.5:
        h["comfort"] = round(max(0.0, h.get("comfort", 0.0) - 0.03), 3)


# ---- stress and the dinner decision ------------------------------------------------------------------------------------------------------
def note_day(c):
    """Once a day (the nutrition settle): the stress the day ended with joins the week's record."""
    days = habits(c).setdefault("stress_days", [])
    days.append(round(c.get("stress", 0) or 0, 1))
    del days[:-WEEK]


def week_stress(c):
    days = habits(c).get("stress_days") or []
    return sum(days) / len(days) if days else (c.get("stress", 0) or 0)


def pressure(c):
    """0..100: how much strain they are under at dinner time, from now and from the week they have had."""
    return 0.6 * (c.get("stress", 0) or 0) + 0.4 * week_stress(c)


STRAIN_SCALE = 60.0         # strain points that take the whole chance of cooking away (capped at 85%)
LATE_HOME_POINTS = 0.8      # per minute a shift ran over today (an hour late: +48)
SICK_FROM = 15              # body["sickness"] below this does not weigh on dinner
TIRED_BELOW = 45            # body["energy"] below this does (empty: +45)


def strain(c, world):
    """Beyond stress, what makes cooking dinner feel like too much tonight: (points to add to the pressure, why). Getting home late from
    work, feeling ill, and running on empty each push towards the easy way out."""
    from systems import lateness
    body = c.get("body") or {}
    parts = []
    late = lateness.late_home_today(c, world)
    if late:
        parts.append((late * LATE_HOME_POINTS, f"got home {late} minutes late from work"))
    sick = body.get("sickness", 0) or 0
    if sick >= SICK_FROM:
        parts.append((min(50.0, float(sick)), "feeling ill"))
    energy = body.get("energy", 70)
    if energy is not None and energy < TIRED_BELOW:
        parts.append((TIRED_BELOW - energy, "worn out"))
    return sum(p for p, _ in parts), [why for _, why in parts]


def can_cook(c):
    return c.get("age_group") not in ("child", "toddler", "infant", "baby") and (c.get("age") or 30) >= 13


def dinner_mode(c, world, household, rng=random):
    """"cook" or "easy" (a snack, leftovers, something ordered or bought). A calm person cooks. Stress, getting home late from work,
    being ill or worn out (`strain`), a comfort-eating habit and a craving each make the easy way likelier."""
    from systems import cookware
    if not cookware.feasible_recipes(household, 1):
        return "easy"
    p = pressure(c)
    h = habits(c)
    p += 25 * h.get("comfort", 0.0) + 15 * h.get("craving", 0.0)
    # chance of cooking: certain when calm, falling to ~15% when worn out ...
    chance = _clamp(1.0 - (p - 30) / 60.0, 0.15, 1.0)
    # ... and cut by what tonight has added (a late finish, being ill, running on empty), however calm the week has been
    chance = max(0.05, chance * (1.0 - min(0.85, strain(c, world)[0] / STRAIN_SCALE)))
    return "cook" if rng.random() < chance else "easy"


def easy_choice(c, world, household):
    """When not cooking: the ready meal in the freezer, a takeout (when they can afford it and are too worn out for the microwave to
    feel like enough), or just whatever there is to nibble."""
    from systems import ready_meals
    money = c.get("money", 0) or 0
    have = ready_meals.count(household) > 0
    if money >= 25 and (pressure(c) + strain(c, world)[0] >= 55 or not have):
        return "takeout"
    return "processed" if have else "snack"


# ---- choosing a recipe -------------------------------------------------------------------------------------------------------------------
def recipe_score(c, household, rid, people):
    """How much this person fancies a recipe, from the ingredients they would actually use; a craving favours the unhealthy ones."""
    from systems import cookware, food_scoring as fs
    rec = fs.DISH_RECIPES[rid]
    taken = []
    for group, n in fs.units_needed(rec, people).items():
        rows = sorted(cookware.stock(household, group), key=lambda r: -liking(c, cookware.row_template(r)))
        for row in rows:
            if n <= 0:
                break
            use = min(n, row["quantity"])
            n -= use
            taken.append({"template_id": cookware.row_template(row), "quantity": use})
    dish = fs.dish_from_items(taken, people, rec["name"])
    return dish_liking(c, taken) + craving(c) * dish["addictive"] * 0.8 + 0.15 * dish["taste"]


def choose_recipe(c, household, people, options, rng=random):
    """A weighted pick among the recipes that can be made: the ones they fancy more are likelier, never certain."""
    if not options:
        return None
    weights = [max(0.05, 1.0 + 2.0 * recipe_score(c, household, rid, people)) for rid in options]
    return rng.choices(options, weights=weights, k=1)[0]
