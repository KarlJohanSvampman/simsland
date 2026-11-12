"""What each requirement asks of the world. Every resolver: fn(c, world) -> bool. A requirement in behaviour.json names
its resolver here; the checker refuses one that names nothing."""

RESOLVERS = {}


def resolver(name):
    def deco(fn):
        RESOLVERS[name] = fn
        return fn
    return deco


def _household(c, world):
    return (world.get("households") or {}).get(c.get("household_id"))


@resolver("food_served")
def food_served(c, world):
    """Someone has cooked and it is still being served, or there are leftover portions."""
    hh = _household(c, world)
    if not hh:
        return False
    from systems import cookware
    return bool(cookware.ready_vessel(hh, world.get("tick", 0)) or any(l.get("portions", 0) > 0 for l in hh.get("leftovers", [])))


@resolver("has_warm_ready_meal")
def has_warm_ready_meal(c, world):
    hh = _household(c, world)
    from systems import ready_meals
    return bool(hh and ready_meals.count(hh, "warm"))


@resolver("has_ready_meal")
def has_ready_meal(c, world):
    hh = _household(c, world)
    from systems import ready_meals
    return bool(hh and ready_meals.count(hh, "cold"))


@resolver("has_stored_meal")
def has_stored_meal(c, world):
    hh = _household(c, world)
    from systems.household_storage import find_household_resource
    return bool(hh and (find_household_resource(hh, resource_type="MEAL") or find_household_resource(hh, resource_type="STORED_MEAL")))


@resolver("has_snack")
def has_snack(c, world):
    hh = _household(c, world)
    if not hh:
        return False
    from systems.household_storage import find_household_resource
    return any(find_household_resource(hh, resource_type=t) for t in ("FOOD_FRUIT", "FOOD_BREAD", "FOOD_SNACK", "PROCESSED_MEAL"))


@resolver("has_ingredients")
def has_ingredients(c, world):
    hh = _household(c, world)
    from systems import cookware
    return bool(hh and cookware.feasible_recipes(hh, 1))


@resolver("can_cook")
def can_cook(c, world):
    from systems.food_habits import can_cook as _can
    return bool(_can(c))


@resolver("cookware_free")
def cookware_free(c, world):
    hh = _household(c, world)
    from systems import cookware
    return bool(hh and any(cookware.vessel_for(hh, k) for k in ("pot", "pan", "oven")))


@resolver("phone_usable")
def phone_usable(c, world):
    from systems.personal_items import phone_is_usable
    return bool(phone_is_usable(c))


@resolver("money_for_takeout")
def money_for_takeout(c, world):
    return (c.get("money") or 0) >= 25


@resolver("money_for_groceries")
def money_for_groceries(c, world):
    return (c.get("money") or 0) >= 20


@resolver("takeout_on_its_way")
def takeout_on_its_way(c, world):
    hh = _household(c, world)
    return bool(hh and hh.get("deliveries"))


def _anchor_offered(world, interaction):
    for p in world.get("props") or []:
        for a in p.get("anchors") or []:
            if a.get("interaction") == interaction:
                return True
    return False


@resolver("store_reachable")
def store_reachable(c, world):
    """Somewhere on the map offers food shopping (an anchor with the shop_food interaction)."""
    return _anchor_offered(world, "shop_food")


@resolver("restaurant_reachable")
def restaurant_reachable(c, world):
    return _anchor_offered(world, "eat_out")


@resolver("caretaker_home")
def caretaker_home(c, world):
    """An adult of the household is in the same building."""
    hh = _household(c, world)
    chars = world.get("characters") or {}
    return bool(hh and any(m != c.get("id") and m in chars and (chars[m].get("age") or 0) >= 18
                           and chars[m].get("building_id") == c.get("building_id") and not chars[m].get("off_grid")
                           for m in hh.get("members") or []))


# ── Reduce Pressure (bladder, bowels) and Relieve Sexual Tension ─────────────────────────────────────────────────

VIEW_TILES = 18             # how far someone out in the open could see you


def _alive_others(c, world):
    return [o for oid, o in (world.get("characters") or {}).items()
            if oid != c.get("id") and o.get("alive") is not False and not o.get("off_grid") and o.get("x") is not None]


def _room(world, x, y):
    from systems.room_assignment import room_at
    return room_at(world, x, y)


def _building_at(world, x, y):
    from systems.navigation import find_building_at
    b, _ = find_building_at(world, int(round(x)), int(round(y)))
    return b


def _home_ids(c, world):
    hh = _household(c, world) or {}
    return set(hh.get("building_ids") or []) | ({hh["home_id"]} if hh.get("home_id") else set())


def _dist(a, b):
    return ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5


def _home_props(c, world, interactions):
    homes = _home_ids(c, world)
    return [p for p in world.get("props") or [] if p.get("building_id") in homes and p.get("x") is not None
            and any(a.get("interaction") in interactions for a in p.get("anchors") or [])]


def _room_kind(room_id):
    return str(room_id or "").split(":")[-1].rsplit("_", 1)[0]


def _alone_in(c, world, room_id):
    return room_id is not None and not any(_room(world, o["x"], o["y"]) == room_id for o in _alive_others(c, world))


BATHROOM_KINDS = ("bathroom", "restroom", "washroom", "toilet")


def _own_bedroom(c, room_id):
    """Their assigned bedroom (systems/bedroom_assignment.py); with none assigned, any bedroom of their home."""
    if not room_id:
        return False
    mine = c.get("bedroom_id")
    if not mine:
        return _room_kind(room_id) == "bedroom"
    return room_id == mine or room_id.endswith(":" + str(mine).split(":")[-1])


@resolver("is_adult")
def is_adult(c, world):
    return (c.get("age") or 0) >= 18


@resolver("is_outdoors")
def is_outdoors(c, world):
    """Out in the open: not standing inside any building."""
    return c.get("x") is not None and _building_at(world, c["x"], c["y"]) is None


@resolver("nobody_in_view")
def nobody_in_view(c, world):
    """No one near enough, with a clear line of sight, to see them."""
    from brain.perception import can_see
    return not any(_dist(c, o) <= VIEW_TILES and can_see(o, c, world) for o in _alive_others(c, world))


@resolver("toilet_reachable")
def toilet_reachable(c, world):
    """A toilet at home, or in the building they are in."""
    here = (_building_at(world, c["x"], c["y"]) or {}).get("id") if c.get("x") is not None else None
    return any(p.get("building_id") in (_home_ids(c, world) | {here}) and
               any(a.get("interaction") == "use_toilet" for a in p.get("anchors") or [])
               for p in world.get("props") or [])


@resolver("private_here")
def private_here(c, world):
    """Indoors in their own bedroom or a bathroom, and nobody else in the room."""
    if c.get("x") is None:
        return False
    rid = _room(world, c["x"], c["y"])
    b = _building_at(world, c["x"], c["y"])
    if not rid or not b or b.get("id") not in _home_ids(c, world):
        return False
    return (_own_bedroom(c, rid) or _room_kind(rid) in BATHROOM_KINDS) and _alone_in(c, world, rid)


@resolver("own_bed_private")
def own_bed_private(c, world):
    """Their bed at home is in their own room, and nobody else is in that room now."""
    for p in _home_props(c, world, ("sleep",)):
        rid = _room(world, p["x"], p["y"])
        if _own_bedroom(c, rid) and _alone_in(c, world, rid):
            return True
    return False


@resolver("bathroom_private")
def bathroom_private(c, world):
    """A bathroom at home with nobody in it (a door that locks)."""
    for p in _home_props(c, world, ("use_toilet", "shower")):
        rid = _room(world, p["x"], p["y"])
        if rid and _alone_in(c, world, rid) and not p.get("occupied_by"):
            return True
    return False


@resolver("partner_available")
def partner_available(c, world):
    """Their partner or spouse is an adult, in the same building, awake and not busy with something they can't leave."""
    from systems.sexual_release import _find_partner
    p = _find_partner(c, world)
    if not p or (p.get("age") or 0) < 18 or p.get("alive") is False or p.get("building_id") != c.get("building_id"):
        return False
    act = (p.get("activity") or {}).get("type")
    return act not in ("sleep", "work", "use_toilet", "use_toilet_bowels", "take_shower")


@resolver("past_partner_reachable")
def past_partner_reachable(c, world):
    """Someone they have been intimate with before, who isn't their partner (a booty call by text)."""
    from systems.sexual_release import _fwb_candidates
    return bool(_fwb_candidates(c, world))


@resolver("tension_released")
def tension_released(c, world):
    return not (c.get("libido_state") or {}).get("spike_until_tick")


# ── distances (decision variables, in tiles; None when there is nowhere) ─────────────────────────────────────────

def _nearest(c, props):
    return round(min((_dist(c, p) for p in props), default=0) if props else 999)


def distance_home(c, world):
    if c.get("x") is None:
        return None
    here = _building_at(world, c["x"], c["y"])
    if here and here.get("id") in _home_ids(c, world):
        return 0
    homes = [b for b in world.get("buildings") or [] if b.get("id") in _home_ids(c, world)]
    toilets = _home_props(c, world, ("use_toilet",))
    return _nearest(c, toilets) if toilets else (_nearest(c, homes) if homes else 999)


def bed_distance(c, world):
    beds = [p for p in _home_props(c, world, ("sleep",)) if _own_bedroom(c, _room(world, p["x"], p["y"]))]
    return _nearest(c, beds) if c.get("x") is not None else None


def bathroom_distance(c, world):
    return _nearest(c, _home_props(c, world, ("use_toilet", "shower"))) if c.get("x") is not None else None


DISTANCES = {"distance_home": distance_home, "bed_distance": bed_distance, "bathroom_distance": bathroom_distance}


def closest_private_place(c, world):
    bed, bath = bed_distance(c, world), bathroom_distance(c, world)
    if bed is None or bed >= 999:
        return "bathroom"
    return "bed" if bath is None or bed <= bath else "bathroom"


DISTANCES["closest_private_place"] = closest_private_place


# ── Restore Energy, Get Clean, groceries ─────────────────────────────────────────────────────────────────────────

@resolver("grocery_open")
def grocery_open(c, world):
    """A food shop is open now (the off-grid grocery trip: systems/offgrid.py's shopping hours)."""
    from systems.offgrid import _errand_hours_ok
    return _errand_hours_ok("shopping", world)


@resolver("not_out_shopping")
def not_out_shopping(c, world):
    """Nobody from the household is already out buying food."""
    return (( _household(c, world) or {}).get("_shopping_until") or 0) <= world.get("tick", 0)


@resolver("bed_available")
def bed_available(c, world):
    """A bed at home (or in the building they are in) that someone can sleep in."""
    here = (_building_at(world, c["x"], c["y"]) or {}).get("id") if c.get("x") is not None else None
    return any(p.get("building_id") in (_home_ids(c, world) | {here}) and
               any(a.get("interaction") == "sleep" for a in p.get("anchors") or []) for p in world.get("props") or [])


@resolver("wants_bed")
def wants_bed_now(c, world):
    """It is their bedtime before a work or school day (systems/bedtime.py)."""
    from systems.bedtime import wants_bed
    return bool(wants_bed(c, world))


@resolver("rested")
def rested(c, world):
    """Not tired any more (fatigue under 25), or back asleep (a bathroom break in the night, then back to bed)."""
    if (c.get("activity") or {}).get("type") in ("sleep", "nap"):
        return True
    return ((c.get("body") or {}).get("fatigue") or 0) < 25


@resolver("shower_available")
def shower_available(c, world):
    return bool(_home_props(c, world, ("shower",)))


@resolver("sink_reachable")
def sink_reachable(c, world):
    """A sink with running water at home or in the building they are in (the "drink" / "wash_hands" anchors)."""
    here = (_building_at(world, c["x"], c["y"]) or {}).get("id") if c.get("x") is not None else None
    return any(p.get("building_id") in (_home_ids(c, world) | {here}) and
               any(a.get("interaction") in ("drink", "wash_hands") for a in p.get("anchors") or []) for p in world.get("props") or [])


@resolver("food_ready")
def food_ready(c, world):
    """Something to eat is ready now: served, leftovers, or a warm takeout or heated meal."""
    return bool(food_served(c, world) or has_warm_ready_meal(c, world))


@resolver("child_waiting_here")
def child_waiting_here(c, world):
    """A child of the household, in this building, is waiting for a grown-up to feed them."""
    from brain.actionplans.actions import _waiting_children
    return bool(_waiting_children(c, world))


DINNER_LEAD_SECONDS = 60 * 60      # start cooking an hour before the dinner window opens (it was ready half an hour late)


def _window_open(c, world, eid, lead):
    nd = (c.get("expectations") or {}).get(eid) or {}
    start, end, tick = nd.get("window_start_tick"), nd.get("window_end_tick"), world.get("tick", 0)
    if nd.get("status") == "satisfied" or start is None or end is None:
        return False
    return start - lead <= tick < end


@resolver("dinner_time")
def dinner_time(c, world):
    """Make Dinner's window is open (or opens within half an hour) and dinner is still to be made."""
    return _window_open(c, world, "make_dinner", DINNER_LEAD_SECONDS)


@resolver("family_dinner_time")
def family_dinner_time(c, world):
    """Family dinner's window is open (or opens within ten minutes) and it has not happened yet -- or dinner has just been
    made and is on the table, up to an hour early: sit down to it then, before the hungry ones have eaten it all."""
    if _window_open(c, world, "family_dinner_together", 10 * 60):
        return True
    if not _window_open(c, world, "family_dinner_together", 60 * 60):
        return False
    made = ((c.get("expectations") or {}).get("make_dinner") or {}).get("status") == "satisfied"
    return made and food_served(c, world)


DINNER_WAIT_SECONDS = 90 * 60     # family dinner this close: no meal of one's own first...
DINNER_WAIT_UNLESS_HUNGER = 80    # ...unless they're this hungry


@resolver("not_waiting_for_dinner")
def not_waiting_for_dinner(c, world):
    """Reduce Hunger may go ahead -- unless the household's family dinner is due within an hour and a half (or on now)
    and they aren't badly hungry: then they wait for it (24-hour run, 2026-11-12: a parent got peckish at five, ate
    on his own, and was "busy eating" when dinner together came round -- every day)."""
    if ((c.get("body") or {}).get("hunger") or 0) >= DINNER_WAIT_UNLESS_HUNGER:
        return True
    people = [c] + _household_others(c, world)
    if any(_window_open(p, world, "family_dinner_together", DINNER_WAIT_SECONDS) for p in people):
        return False
    return True


@resolver("bedtime_check_time")
def bedtime_check_time(c, world):
    """The kids' bedtime check is due (its window is open, or opens within ten minutes)."""
    return _window_open(c, world, "child_bedtime_check", 10 * 60)


def _household_others(c, world):
    chars = world.get("characters") or {}
    hh = _household(c, world) or {}
    return [chars[m] for m in hh.get("members") or [] if m in chars and m != c.get("id") and chars[m].get("alive") is not False]


@resolver("family_home")
def family_home(c, world):
    """Everyone of the household is home (in this building, not away)."""
    return all(o.get("building_id") == c.get("building_id") and not o.get("off_grid") for o in _household_others(c, world))


@resolver("kids_home")
def kids_home(c, world):
    """A child they look after is home (in this building)."""
    chars = world.get("characters") or {}
    kids = [chars[k] for k in c.get("dependents") or [] if k in chars] or [o for o in _household_others(c, world) if (o.get("age") or 99) < 13]
    return any(k.get("building_id") == c.get("building_id") and not k.get("off_grid") for k in kids)



# ── saying something to someone (Make Things Right, Check On Someone) ───────────────────────────────────────────────

def _purpose_target(c, world):
    sp = c.get("_social_purpose") or {}
    return (world.get("characters") or {}).get(sp.get("target")), sp


@resolver("target_here")
def target_here(c, world):
    """The person they mean to talk to is right here: the same room, or close by outdoors."""
    t, _ = _purpose_target(c, world)
    if not t or t.get("off_grid") or t.get("alive") is False or t.get("x") is None or c.get("x") is None:
        return False
    if c.get("room_id") and t.get("room_id"):
        return c["room_id"] == t["room_id"]
    return c.get("building_id") == t.get("building_id") and _dist(c, t) <= 6


@resolver("target_around")
def target_around(c, world):
    """The person is somewhere they can be walked to (on the map, not away)."""
    t, _ = _purpose_target(c, world)
    return bool(t) and not t.get("off_grid") and t.get("alive") is not False and t.get("x") is not None


@resolver("said_it")
def said_it(c, world):
    """They have spoken to that person since setting out to (a line of theirs in a conversation with them)."""
    t, sp = _purpose_target(c, world)
    if not t:
        return False
    since = sp.get("since", 0)
    for conv in (world.get("conversations") or {}).values():
        if t["id"] not in (conv.get("participants") or []) or c["id"] not in (conv.get("participants") or []):
            continue
        if any(h.get("speaker") == c["id"] and (h.get("tick") or 0) >= since for h in conv.get("history") or []):
            return True
    return False



# ── Spend Time Alone / Unwind with Someone ──────────────────────────────────────────────────────────────────────

@resolver("alone_here")
def alone_here(c, world):
    """Nobody else in the room with them (indoors)."""
    if c.get("x") is None:
        return False
    rid = _room(world, c["x"], c["y"])
    return bool(rid) and _alone_in(c, world, rid)


@resolver("evening")
def evening(c, world):
    """The evening (17:00-23:00): when people unwind."""
    h = (world.get("calendar") or {}).get("hour")
    return h is not None and 17 <= h < 23


# busy -- not to be asked to come and sit down: eating (dinner together was broken up by a friend calling round to
# unwind, 24-hour run 2026-11-12), cooking, asleep, at work, in the bathroom
NOT_FREE_TO_UNWIND = ("sleep", "nap", "work", "use_toilet", "use_toilet_bowels", "take_shower", "cook_recipe", "eat_meal", "eat_snack")


def unwind_companion(c, world):
    """Whom to unwind with: their partner if home and free, else another grown-up at home who is free."""
    def free(o):
        act = (o.get("activity") or {}).get("type")
        return (not o.get("off_grid") and o.get("alive") is not False and o.get("building_id") == c.get("building_id")
                and act not in NOT_FREE_TO_UNWIND)
    from systems.sexual_release import _find_partner
    p = _find_partner(c, world)
    if p and free(p):
        return p
    for o in _household_others(c, world):
        if (o.get("age") or 0) >= 18 and free(o):
            return o
    return None


@resolver("companion_free")
def companion_free(c, world):
    """Someone to unwind with is home and free."""
    return unwind_companion(c, world) is not None



def friend_to_visit(c, world):
    """A grown-up outside the household they know (a relationship on record, not hostile), home and free -- best liked first."""
    chars = world.get("characters") or {}
    hh = set((_household(c, world) or {}).get("members") or [])
    best = []
    for oid, rel in (c.get("relationships") or {}).items():
        o = chars.get(oid)
        if not o or oid in hh or (o.get("age") or 0) < 18 or o.get("off_grid") or o.get("alive") is False:
            continue
        if (rel.get("affection") or rel.get("trust") or 0) < 0 or "enemy" in (rel.get("labels") or []):
            continue
        home = set(((world.get("households") or {}).get(o.get("household_id")) or {}).get("building_ids") or [])
        act = (o.get("activity") or {}).get("type")
        if o.get("building_id") not in home or act in NOT_FREE_TO_UNWIND:
            continue
        best.append((rel.get("affection") or rel.get("trust") or 0, oid))
    best.sort(reverse=True)
    return chars[best[0][1]] if best else None


@resolver("friend_free")
def friend_free(c, world):
    """A friend nearby is home and free to unwind with."""
    return friend_to_visit(c, world) is not None
