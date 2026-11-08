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
    # the grown-up's feed_child duty is only acted on while the child is marked as waiting (systems/child_care.py::tend_child,
    # the Feed the Kids plans): without this mark the request was dropped as "already seen to", and every ask timed out
    c.setdefault("_awaiting_caregiver", {"need": "hunger", "tick": world.get("tick", 0), "asked": who["id"]})
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
    from brain.actionplans import runner
    for rid in ("food_served", "has_warm_ready_meal", "has_ready_meal", "has_stored_meal", "has_snack", "has_ingredients",
                "money_for_takeout", "phone_usable"):
        runner.observe(c, world, rid, how="looked")
    return True


@action("ask_partner")
def ask_partner(c, world, attempt):
    """Suggest it to their partner (systems/sexual_release.py: the partner decides, and the scene starts if they say yes)."""
    from systems.sexual_release import _try_partner
    ok = bool(_try_partner(c, world))
    attempt["vars"]["partner_said"] = "yes" if ok else "no"
    return ok


@action("booty_call")
def booty_call(c, world, attempt):
    """Text someone they have been with before; if they come over and are willing, the scene starts."""
    from systems.sexual_release import _try_booty_call
    return bool(_try_booty_call(c, world))


@action("go_grocery_shopping")
def go_grocery_shopping(c, world, attempt):
    """Out to the shops (systems/offgrid.py's grocery errand): the shopper decides the coming dinners before leaving
    (systems/grocery.py::make_plan) and comes home with them. The plan waits for the ingredients."""
    hh = (world.get("households") or {}).get(c.get("household_id"))
    if not hh or (c.get("age") or 0) < 18:
        return False
    from systems import offgrid, grocery
    if offgrid.same_as_last_trip_today(c, world, "shopping"):
        attempt["vars"]["why"] = "already went shopping today"
        return False
    if offgrid.repeat_blocked(c, world, "shopping"):
        attempt["vars"]["why"] = "only just got back from the shops"
        return False
    if c.get("travel_state") or c.get("off_grid"):
        attempt["vars"]["why"] = "out already"
        return False
    if not offgrid.send_offgrid(c, world, "shopping", offgrid.GROCERY_TRIP_MINUTES):
        attempt["vars"]["why"] = "couldn't get out to the shops"
        return False
    hh["_shopping_until"] = c.get("return_tick")
    grocery.make_plan(world, hh, c)
    return True


def _waiting_children(c, world):
    chars = world.get("characters") or {}
    hh = (world.get("households") or {}).get(c.get("household_id")) or {}
    return [chars[m] for m in hh.get("members") or [] if m in chars and m != c.get("id") and chars[m].get("_awaiting_caregiver")
            and not chars[m].get("off_grid") and chars[m].get("building_id") == c.get("building_id")]


@action("call_children_to_eat")
def call_children_to_eat(c, world, attempt):
    """Food is ready: call the hungry children to come and eat. Their own Reduce Hunger takes it from there (they know the
    food is there now); the grown-up's duty is done."""
    kids = _waiting_children(c, world)
    if not kids:
        return False
    from brain.actionplans import runner
    from brain.intentions import add_intention
    from systems.child_care import _drop_for_parents
    for k in kids:
        k.pop("_awaiting_caregiver", None)
        for rid in ("food_served", "has_warm_ready_meal", "food_ready"):
            runner.observe(k, world, rid, how="told")
        add_intention(k, {"type": "eat_food", "category": "survival", "priority": 85, "reason": f"{c.get('first_name') or c.get('name', 'a grown-up')} called them to eat"})
        _drop_for_parents(world, k, f"feed_child_{k['id']}")
    try:
        from systems.action_router import apply_speech
        names = " and ".join(k.get("first_name") or k.get("name", "") for k in kids)
        apply_speech(c, world, {"target": kids[0]["id"], "utterance": f"{names}, food's ready -- come and eat!", "speech_act": "statement"})
    except Exception:                                  # noqa: BLE001 -- the call is said or not; the food is there either way
        pass
    attempt["vars"]["fed"] = [k["id"] for k in kids]
    return True


@action("feed_children_quickly")
def feed_children_quickly(c, world, attempt):
    """The last resort: nothing ready, nothing to cook, no takeout -- they rustle something up (systems/action_router.py's
    feed_child: the child is fed at once) so no child goes hungry for want of a plan."""
    kids = _waiting_children(c, world)
    if not kids:
        return False
    from systems.action_router import _route_feed_child
    for k in kids:
        _route_feed_child(c, world, {"type": "feed_child", "target_id": k["id"]})
    from systems.child_care import _drop_for_parents
    for k in kids:
        _drop_for_parents(world, k, f"feed_child_{k['id']}")
    attempt["vars"]["fed"] = [k["id"] for k in kids]
    return True
