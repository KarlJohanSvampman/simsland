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
    apply_speech(c, world, {"target": who["id"], "utterance": "I'm hungry. Can I have something to eat?", "speech_act": "request",
                            "scripted": True})
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
        apply_speech(c, world, {"target": kids[0]["id"], "utterance": f"{names}, food's ready -- come and eat!", "speech_act": "statement",
                                "volume": "high", "scripted": True})      # called out through the house
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


@action("dinner_is_made")
def dinner_is_made(c, world, attempt):
    """Dinner is made (cooked, heated, ordered, or someone else got there first): Make Dinner is met -- for every grown-up
    of the household who had it to do, not only the one who cooked."""
    from systems.expectations import satisfy_expectation
    chars = world.get("characters") or {}
    hh = (world.get("households") or {}).get(c.get("household_id")) or {}
    done = []
    for m in [c.get("id")] + [x for x in hh.get("members") or [] if x != c.get("id")]:
        p = chars.get(m)
        nd = ((p or {}).get("expectations") or {}).get("make_dinner")
        if nd and nd.get("status") != "satisfied":
            satisfy_expectation(p, "make_dinner", world)
            done.append(m)
    attempt["vars"]["dinner_for"] = done
    return bool(done)


@action("call_family_to_table")
def call_family_to_table(c, world, attempt):
    """Dinner's on the table: everyone at home is called to come and eat (each one's own hunger plan does the eating)."""
    chars = world.get("characters") or {}
    hh = (world.get("households") or {}).get(c.get("household_id")) or {}
    here = [chars[m] for m in hh.get("members") or [] if m in chars and m != c.get("id")
            and chars[m].get("building_id") == c.get("building_id") and not chars[m].get("off_grid")]
    if not here:
        return False
    from brain.actionplans import runner
    from brain.intentions import add_intention
    from systems.activities import ACTIVITIES, start_activity
    from systems.occupancy import interrupt_activity
    seated = []
    for o in here:
        runner.observe(o, world, "food_served", how="told")
        runner.observe(o, world, "food_ready", how="told")
        # called to the table means coming to sit down with the family, hungry or not (2026-11-08: a child who wasn't
        # hungry stayed in their room, and dinner together was never met). Whatever they are doing gives way if it can.
        act = o.get("activity") or {}
        if act.get("type") == "eat_meal":
            seated.append(o["id"])
            continue
        if act and not (ACTIVITIES.get(act.get("type")) or {}).get("interruptible") or o.get("conversation"):
            add_intention(o, {"type": "eat_food", "category": "survival", "priority": 80,
                              "reason": "dinner is on the table -- the family is eating together"})
            continue
        if act:
            interrupt_activity(o, world, reason="called to dinner")
        if start_activity(o, world, "eat_meal"):
            seated.append(o["id"])
    attempt["vars"]["seated"] = seated
    try:
        from systems.action_router import apply_speech
        apply_speech(c, world, {"target": here[0]["id"], "utterance": "Dinner's ready, everyone -- come and sit down!", "speech_act": "statement",
                                "volume": "high", "scripted": True})
    except Exception:                                  # noqa: BLE001
        pass
    attempt["vars"]["called"] = [o["id"] for o in here]
    return True


@action("dinner_together_done")
def dinner_together_done(c, world, attempt):
    """After eating: if the whole household was there, Family Dinner Together is met for every grown-up who had it;
    if not, who was missing is noted (systems/expectations.py's miss blames them) and it is not met."""
    from systems.expectation_planner import _missing_household_members
    chars = world.get("characters") or {}
    seated = set((attempt.get("vars") or {}).get("seated") or [])
    # someone who sat down to the meal and finished first (off for a glass of water) was still at dinner
    missing = [m for m in _missing_household_members(c, world)
               if not (m in seated and (chars.get(m) or {}).get("building_id") == c.get("building_id"))]
    if missing:
        nd = (c.get("expectations") or {}).get("family_dinner_together")
        if nd is not None:
            nd["last_missed_blame"] = missing
        attempt["vars"]["why"] = " and ".join((chars.get(m) or {}).get("first_name") or m for m in missing) + " wasn't at the table"
        return False
    from systems.expectations import satisfy_expectation
    hh = (world.get("households") or {}).get(c.get("household_id")) or {}
    for m in hh.get("members") or []:
        nd = ((chars.get(m) or {}).get("expectations") or {}).get("family_dinner_together")
        if nd and nd.get("status") != "satisfied":
            satisfy_expectation(chars[m], "family_dinner_together", world)
    return True


@action("check_on_kids")
def check_on_kids(c, world, attempt):
    """The bedtime check (systems/action_router.py): look in on the kids, send one who is still up to bed. Meets the
    expectation."""
    from systems.action_router import _route_check_on_kids
    before = ((c.get("expectations") or {}).get("child_bedtime_check") or {}).get("status")
    # name the child: the check's own fallback only looks at c["dependents"], which a household's children are not always in
    chars = world.get("characters") or {}
    hh = (world.get("households") or {}).get(c.get("household_id")) or {}
    kids = [chars[k] for k in (c.get("dependents") or []) + (hh.get("members") or []) if k in chars and k != c.get("id")
            and (chars[k].get("age") or 99) < 13 and chars[k].get("building_id") == c.get("building_id") and not chars[k].get("off_grid")]
    if not kids:
        return False
    _route_check_on_kids(c, world, {"type": "check_on_kids", "target_id": kids[0]["id"]})
    after = ((c.get("expectations") or {}).get("child_bedtime_check") or {}).get("status")
    return after == "satisfied" or (before is None and bool(c.get("activity")))


# what each old intention type means to say, in the words the model is woken with
_PURPOSES = {
    "apologize_to": "apologise to {name} and make it right",
    "apologize": "apologise to {name} and make it right",
    "check_in_on": "check in on {name} -- ask how they are doing",
    "suggest_doctor": "suggest that {name} sees a doctor",
    "suggest_hygiene": "tactfully let {name} know they could do with a shower",
    "confront": "have it out with {name}",
}


@action("pick_who")
def pick_who(c, world, attempt):
    """Whom this is about (the old intention's target) -- remembered on the character while the plan runs."""
    who = (attempt.get("vars") or {}).get("target_id")
    if not who or who not in (world.get("characters") or {}):
        return False
    c["_social_purpose"] = {"target": who, "since": world.get("tick", 0),
                            "type": (attempt.get("vars") or {}).get("raised_as")}
    return True


@action("go_to_them")
def go_to_them(c, world, attempt):
    """Walk over to them (systems/action_router.py's move to a character)."""
    t = (world.get("characters") or {}).get((c.get("_social_purpose") or {}).get("target"))
    if not t:
        return False
    from systems.action_router import _route_move
    _route_move(c, world, {"type": "move", "target": t["id"]})
    return bool(c.get("is_moving") or c.get("move_target"))


@action("say_it")
def say_it(c, world, attempt):
    """They are face to face: wake their model with what they came to say. The words are theirs (the model's); the plan
    waits until they have actually said something to the person."""
    sp = c.get("_social_purpose") or {}
    t = (world.get("characters") or {}).get(sp.get("target"))
    if not t:
        return False
    sp["since"] = world.get("tick", 0)
    what = _PURPOSES.get(sp.get("type") or "", "talk to {name}").format(name=t.get("first_name") or t.get("name", "them"))
    from brain.cognition_scheduler import wake_character
    wake_character(c, world, "social_purpose", {"line": f"You came to {what} -- {t.get('first_name') or t.get('name')} is right here. Say it now."})
    return True


@action("note_event")
def note_event(c, world, attempt):
    """Prepare for an Event: take note of it and of what it needs -- remembered, and not raised again until it moves into
    the next reminder band (systems/calendar_events.py). The concrete tasks (a gift, an outfit, a card) are intentions of
    their own."""
    v = attempt.get("vars") or {}
    eid = v.get("event_id")
    if not eid:
        return False
    c.setdefault("event_prep_noted", {})[eid] = v.get("band_days")
    days = v.get("days_until")
    when = "tomorrow" if days == 1 else f"in {days} days" if days else "soon"
    needs = [str(x).replace("_", " ") for x in (v.get("prep_requirements") or [])]
    line = f"{v.get('event_name') or 'An event'} is {when}." + (f" I'll need to: {', '.join(needs)}." if needs else " Nothing to get ready yet.")
    try:
        from brain.memory import store_memory
        store_memory(c, line, importance=0.3, tags=["calendar", "plan"], tick=world.get("tick", 0), source="internal")
    except Exception:                                  # noqa: BLE001
        pass
    attempt["vars"]["noted"] = line
    return True


@action("go_to_own_room")
def go_to_own_room(c, world, attempt):
    """Off to their own bedroom (systems/action_router.py's move to a room)."""
    from brain.actionplans.resolvers import _home_props, _room, _own_bedroom
    for p in _home_props(c, world, ("sleep",)):
        rid = _room(world, p["x"], p["y"])
        if rid and _own_bedroom(c, rid):
            from systems.action_router import _route_move
            _route_move(c, world, {"type": "move", "target": f"room:{rid}"})
            return bool(c.get("is_moving") or c.get("move_target"))
    return False


@action("me_time_done")
def me_time_done(c, world, attempt):
    """Spend Time Alone is met."""
    from systems.expectations import satisfy_expectation
    if (c.get("expectations") or {}).get("spend_time_alone") is None:
        return True
    satisfy_expectation(c, "spend_time_alone", world)
    return True


@action("invite_to_unwind")
def invite_to_unwind(c, world, attempt):
    """Ask their partner (or another grown-up at home) to come and sit down for a while: they sit down to relax too, if
    what they are doing can wait."""
    from brain.actionplans.resolvers import unwind_companion
    o = (world.get("characters") or {}).get((attempt.get("vars") or {}).get("unwind_with")) or unwind_companion(c, world)
    if not o:
        return False
    from systems.activities import ACTIVITIES, start_activity
    from systems.occupancy import interrupt_activity
    act = o.get("activity") or {}
    if act and not (ACTIVITIES.get(act.get("type")) or {}).get("interruptible"):
        return False
    try:
        from systems.action_router import apply_speech
        apply_speech(c, world, {"target": o["id"], "utterance": "Come and sit with me for a bit?", "speech_act": "invite", "scripted": True})
    except Exception:                                  # noqa: BLE001
        pass
    if act:
        interrupt_activity(o, world, reason="sat down to unwind together")
    # at home, a seat each; at a friend's, time together where they are (see "hang_out" in systems/activities.py)
    what = (attempt.get("vars") or {}).get("unwind_activity") or "sit_and_relax"
    if not start_activity(o, world, what):
        return False
    attempt["vars"]["unwind_with"] = o["id"]
    return True


@action("unwound_together")
def unwound_together(c, world, attempt):
    """They sat down together and the other is still home: Unwind with Someone is met."""
    o = (world.get("characters") or {}).get((attempt.get("vars") or {}).get("unwind_with"))
    if not o or o.get("building_id") != c.get("building_id") or o.get("off_grid"):
        attempt["vars"]["why"] = "they went off before we could sit together"
        return False
    from systems.expectations import satisfy_expectation
    if (c.get("expectations") or {}).get("relax_with_someone") is not None:
        satisfy_expectation(c, "relax_with_someone", world)
    return True


@action("pick_friend")
def pick_friend(c, world, attempt):
    """Nobody to unwind with at home: a friend nearby who is home and free -- the one they get on with best."""
    from brain.actionplans.resolvers import friend_to_visit
    f = friend_to_visit(c, world)
    if not f:
        return False
    attempt["vars"]["unwind_with"] = f["id"]
    attempt["vars"]["unwind_activity"] = "hang_out"
    c["_social_purpose"] = {"target": f["id"], "since": world.get("tick", 0), "type": "unwind"}
    return True
