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
