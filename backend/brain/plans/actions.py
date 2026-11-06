"""Plan steps that are a call, not an activity (ordering takeout is a phone call and a payment). fn(c, world, attempt)
-> True (done) / False (failed). A plan's action node names one of these; the checker refuses an unknown one."""

ACTIONS = {}


def action(name):
    def deco(fn):
        ACTIONS[name] = fn
        return fn
    return deco


@action("order_takeout")
def order_takeout(c, world, attempt):
    hh = (world.get("households") or {}).get(c.get("household_id"))
    if not hh:
        return False
    from systems import ready_meals
    order = ready_meals.order_takeout(c, world, hh)
    if order:
        attempt["vars"]["takeout_cost"] = order.get("cost")
    return bool(order)


@action("ask_caretaker_for_food")
def ask_caretaker_for_food(c, world, attempt):
    """A child tells a grown-up at home they are hungry: that grown-up gets the duty to feed them (systems/child_care.py's
    feed_child intention), and the child says so out loud."""
    hh = (world.get("households") or {}).get(c.get("household_id"))
    chars = world.get("characters") or {}
    adults = [chars[m] for m in (hh or {}).get("members") or [] if m in chars and m != c.get("id")
              and (chars[m].get("age") or 0) >= 18 and chars[m].get("building_id") == c.get("building_id")]
    if not adults:
        return False
    who = adults[0]
    from brain.intentions import add_intention
    add_intention(who, {"type": f"feed_child_{c['id']}", "category": "survival", "priority": 80, "child_id": c["id"],
                        "reason": f"{c.get('name', 'A child')} is hungry and asked for food"})
    from systems.action_router import apply_speech
    apply_speech(c, world, {"target": who["id"], "utterance": "I'm hungry. Can I have something to eat?", "speech_act": "request"})
    attempt["vars"]["asked"] = who["id"]
    return True


@action("check_kitchen")
def check_kitchen(c, world, attempt):
    """Scouting: look in the fridge, freezer and cupboards -- every food requirement becomes a known belief."""
    from brain.plans import runner
    for rid in ("food_served", "has_warm_ready_meal", "has_ready_meal", "has_stored_meal", "has_snack", "has_ingredients",
                "money_for_takeout", "phone_usable"):
        runner.observe(c, world, rid, how="looked")
    return True
