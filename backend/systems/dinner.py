"""
systems/dinner.py -- dinner time at home.

Once an evening each household decides who makes dinner and whether they will (systems/food_habits.py::dinner_mode): the rota's cook
if there is one and they are home, otherwise whichever adult at home is under the least strain. A calm cook gets a `cook_dinner`
intention; a strained one takes the easy way out and the household falls back on what the hunger strategy finds. Run about once a minute
from the cookware job.
"""

import random

from systems import cookware, dinner_rota, food_habits, ready_meals

LATE_FOR_ROTA = 18.5      # the rota's cook is given until half past six to be home before somebody else steps in


def _day_key(world):
    cal = world.get("calendar", {})
    return (cal.get("year"), cal.get("month"), cal.get("day"))


def _hour(world):
    cal = world.get("calendar", {})
    return (cal.get("hour") or 0) + (cal.get("minute") or 0) / 60.0


def _at_home(c, household):
    return c.get("building_id") in (household.get("building_ids") or [c.get("building_id")]) and \
        (c.get("activity") or {}).get("type") not in ("sleep", "nap")


def plan(world, rng=random):
    """For every household: at dinner time decide who cooks and whether they do. Also the rota's proposal, when it is time."""
    hour = _hour(world)
    in_window = food_habits.DINNER_HOURS[0] <= hour < food_habits.DINNER_HOURS[1]
    weekday = (world.get("calendar", {}).get("weekday") or "").lower()
    chars = world.get("characters", {})
    for household in world.get("households", {}).values():
        if hour < 5:
            _clear_stale(world, household, rng)
        if not in_window or household.get("dinner_day") == _day_key(world):
            continue
        if any(v["state"] in ("cooking", "ready") for v in household.get("cookware", [])):
            household["dinner_day"] = _day_key(world)
            continue
        home = [chars[m] for m in household.get("members", []) if m in chars and food_habits.can_cook(chars[m]) and _at_home(chars[m], household)]
        if not home:
            continue
        scheduled = chars.get(dinner_rota.cook_for(household, weekday))
        if scheduled is not None and scheduled in home:
            cook = scheduled
        elif scheduled is not None and hour < LATE_FOR_ROTA:
            continue                                            # the rota's cook has until half past six to come home
        else:
            cook = min(home, key=lambda x: (food_habits.pressure(x), rng.random()))
        household["dinner_day"] = _day_key(world)
        mode = food_habits.dinner_mode(cook, world, household, rng)
        household["dinner_mode"] = {"mode": mode, "cook": cook["id"], "tick": world.get("tick", 0)}
        from brain.intentions import add_intention
        if mode == "cook":
            add_intention(cook, {"type": "cook_dinner", "category": "schedule", "priority": 52, "reason": "it is dinner time and it is my turn"
                                 if scheduled is cook else "it is dinner time"})
        else:
            how = food_habits.easy_choice(cook, world, household)
            if how == "takeout" and not ready_meals.order_takeout(cook, world, household, rng):
                how = "processed" if ready_meals.count(household) else "snack"
            household["dinner_mode"]["how"] = how
            if how == "processed":
                for who in home:
                    add_intention(who, {"type": "eat_food", "category": "survival", "priority": 55, "reason": "dinner from the freezer"})
        dinner_rota.maybe_propose(world, household, rng)


def _clear_stale(world, household, rng):
    """Overnight: a dinner nobody got round to is dropped rather than carried into the next day."""
    from brain.intentions import remove_intention
    for mid in household.get("members", []):
        c = world.get("characters", {}).get(mid)
        if c and any(i.get("type") == "cook_dinner" for i in c.get("active_intentions", [])):
            remove_intention(c, "cook_dinner")
