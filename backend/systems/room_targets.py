"""
systems/room_targets.py

Rooms as somewhere to walk to. `move` / `jog_to` / `sneak_to` used to accept only a
person or a prop, so a character who decided "I head towards the kitchen" got a
failed target resolution, re-thought on the very next tick, decided the same thing
and never took a step (live report, 2026-11-01: Kathleen Okafor, "I head toward
towards the kitchen, to grab a glass of water." over and over, standing still).

brain/action_resolver.py falls back to match_room() when a move-type description
matches no nearby person or prop. The resolved target is a room id of the form
"room:<building_id>:<room_id>", which systems/action_router.py::_route_move()
turns into a walk to that room via room_destination().

Only rooms in the building the character is in are considered -- "the kitchen"
means the kitchen here, not one next door.
"""

import re

ROOM_TARGET_PREFIX = "room:"

# Words a model uses for a room -> the floorplan room `type`s they mean. Longer
# phrases are tried first, so "living room" wins over "room" and "dining room"
# over "dining". Only types that occur in floorplans are worth listing; an alias
# for a type the building doesn't have simply never matches.
_ROOM_ALIASES = {
    "kitchen": ("kitchen",),
    "kitchenette": ("kitchen",),
    "dining room": ("dining_room",),
    "dining area": ("dining_room",),
    "dining table": ("dining_room",),
    "living room": ("living_room",),
    "lounge": ("living_room",),
    "sitting room": ("living_room",),
    "family room": ("living_room",),
    "tv room": ("living_room",),
    "bedroom": ("bedroom",),
    "bathroom": ("bathroom", "restroom"),
    "restroom": ("restroom", "bathroom"),
    "toilet": ("restroom", "bathroom"),
    "washroom": ("restroom", "bathroom"),
    "loo": ("restroom", "bathroom"),
    "wc": ("restroom", "bathroom"),
    "laundry room": ("laundry",),
    "laundry": ("laundry",),
    "utility room": ("laundry",),
    "hallway": ("corridor",),
    "hall": ("corridor",),
    "corridor": ("corridor",),
    "garage": ("garage",),
    "office": ("office", "study"),
    "study": ("study", "office"),
}
_ALIASES_LONGEST_FIRST = sorted(_ROOM_ALIASES, key=len, reverse=True)


def _normalize(text):
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", (text or "").lower()).split())


def _building_and_rooms(world, building_id):
    if not building_id:
        return None, []
    from systems.building_entrances import get_building_by_id
    from systems.templates import get_floorplan_template
    building = get_building_by_id(world, building_id)
    if not building:
        return None, []
    floorplan = get_floorplan_template(world, building) or {}
    return building, [r for r in (floorplan.get("rooms") or []) if r.get("tiles")]


def _room_tile_nearest_centre(room):
    """The room's own tile closest to its centroid -- inside the room even when
    the room is L-shaped and the centroid itself is not."""
    tiles = room["tiles"]
    cx = sum(t["x"] for t in tiles) / len(tiles)
    cy = sum(t["y"] for t in tiles) / len(tiles)
    best = min(tiles, key=lambda t: (t["x"] - cx) ** 2 + (t["y"] - cy) ** 2)
    return best["x"], best["y"]


def _world_point(building, room):
    from systems.transforms import local_to_world
    lx, ly = _room_tile_nearest_centre(room)
    return local_to_world(building, lx, ly)


def match_room(c, world, description):
    """The room in the character's current building that `description` names,
    as a "room:<building_id>:<room_id>" target id -- or None.

    Several rooms of the named type (two laundry rooms, three bedrooms): the
    nearest one, unless the character is already standing in one of them, in
    which case another one (walking to the room you are in goes nowhere)."""
    desc = f" {_normalize(description)} "
    if not desc.strip():
        return None
    building_id = c.get("building_id")
    building, rooms = _building_and_rooms(world, building_id)
    if not rooms:
        return None

    for alias in _ALIASES_LONGEST_FIRST:
        if f" {alias} " not in desc:
            continue
        for room_type in _ROOM_ALIASES[alias]:
            candidates = [r for r in rooms if r.get("type") == room_type]
            if not candidates:
                continue
            here = (c.get("room_id") or "").split(":", 1)[-1]
            elsewhere = [r for r in candidates if r.get("id") != here] or candidates
            cx, cy = c.get("x", 0), c.get("y", 0)

            def _distance(room):
                wx, wy = _world_point(building, room)
                return (wx - cx) ** 2 + (wy - cy) ** 2

            room = min(elsewhere, key=_distance)
            return f"{ROOM_TARGET_PREFIX}{building['id']}:{room['id']}"
    return None


def is_room_target(target_id):
    return isinstance(target_id, str) and target_id.startswith(ROOM_TARGET_PREFIX)


def room_destination(world, target_id):
    """(x, y, room) a walk to this room target should head for, or None if the
    building or the room no longer exists."""
    if not is_room_target(target_id):
        return None
    try:
        building_id, room_id = target_id[len(ROOM_TARGET_PREFIX):].split(":", 1)
    except ValueError:
        return None
    building, rooms = _building_and_rooms(world, building_id)
    room = next((r for r in rooms if r.get("id") == room_id), None)
    if not building or not room:
        return None
    x, y = _world_point(building, room)
    return x, y, room


def describe_room_target(world, target_id):
    """'the kitchen' for "room:starter_house_2:kitchen_0" -- for narration."""
    dest = room_destination(world, target_id)
    if not dest:
        return "there"
    return "the " + (dest[2].get("type") or "room").replace("_", " ")


# =========================================================
# HOUSES -- walking to a household's home by name
# =========================================================
# "I hurry toward Susan Moreau's house" matched no nearby person or prop either.
# brain/action_resolver.py falls back to match_building() after match_room(); the
# target is "building:<building_id>", which _route_move() walks to via
# building_destination():
#   - someone else's home: the OUTSIDE of its front door -- a visitor doesn't walk
#     in uninvited; from there ring_doorbell / knock_on_door take over
#     (systems/doorbell.py)
#   - their own home: inside it

BUILDING_TARGET_PREFIX = "building:"

# Words that make a name mean the place rather than the person.
_HOUSE_WORDS = ("house", "home", "place", "household", "door", "front door", "doorstep", "porch", "yard", "flat",
                "apartment")
_OWN_HOME = ("my house", "my home", "our house", "our home", "home", "my place", "our place")


def _has_word(desc, phrase):
    return f" {phrase} " in desc


def _household_names(world, household):
    """Ways to name a household's home, as (strong, weak):
    strong -- enough on their own: the household's name and the family name in
              the plural ("the Moreau Household", "the Moreaus");
    weak   -- only next to a house word: the bare family name and each member's
              full and first name ("the Moreau house", "Susan's place"). On its
              own "Susan Moreau" is the person, not the house."""
    strong, weak = set(), set()
    name = _normalize(household.get("name"))
    if name:
        strong.add(name)
        bare = name.removeprefix("the ").removesuffix(" household").removesuffix(" family").strip()
        if bare and bare != name:
            strong.update({bare + "s", bare + "es"})
            weak.add(bare)
    for cid in household.get("members") or []:
        ch = (world.get("characters") or {}).get(cid) or {}
        surname = _normalize(ch.get("family_name"))
        if surname:
            strong.add(surname + "s")
            weak.add(surname)
        for n in (ch.get("name"), ch.get("first_name")):
            n = _normalize(n)
            if n:
                weak.add(n)
    return strong, weak


def _home_buildings(world):
    """[(household, building)] for every household with a home building."""
    from systems.building_entrances import get_building_by_id
    out = []
    for household in (world.get("households") or {}).values():
        bid = household.get("home_id") or next(iter(household.get("building_ids") or []), None)
        building = get_building_by_id(world, bid) if bid else None
        if building:
            out.append((household, building))
    return out


def match_building(c, world, description):
    """The home `description` names, as "building:<building_id>" -- or None.

    Matches, in order: their own home ("home", "my house"); a street address; a
    household or family name ("the Moreaus", "the Okafor household", "Moreau house");
    a member's name together with a house word ("Susan's house", "Susan Moreau's
    place"). A bare person's name is left alone -- that's the person, not the house.
    The building the character is already in never matches (nowhere to go)."""
    desc = f" {_normalize(description)} "
    if not desc.strip():
        return None
    here = c.get("building_id")
    homes = _home_buildings(world)

    def target(building):
        return None if building["id"] == here else f"{BUILDING_TARGET_PREFIX}{building['id']}"

    own = next((b for h, b in homes if h.get("id") == c.get("household_id")), None)
    if own and any(_has_word(desc, p) for p in _OWN_HOME) and not any(
            _has_word(desc, n) for h, b in homes if b is not own for n in set().union(*_household_names(world, h))):
        return target(own)

    for household, building in homes:
        address = _normalize(building.get("address"))
        if address and address in desc:
            return target(building)

    house_word = any(_has_word(desc, w) for w in _HOUSE_WORDS)
    best = None
    for household, building in homes:
        strong, weak = _household_names(world, household)
        names = strong | (weak if house_word else set())
        # longest name that appears wins ("susan moreau" over "susan")
        hits = [n for n in names if _has_word(desc, n)]
        if hits:
            length = max(len(n) for n in hits)
            if best is None or length > best[0]:
                best = (length, building)
    return target(best[1]) if best else None


def is_building_target(target_id):
    return isinstance(target_id, str) and target_id.startswith(BUILDING_TARGET_PREFIX)


def building_destination(world, c, target_id):
    """(x, y, inside) to walk to for a building target, or None. Inside for the
    character's own home, else the outside of the nearest front door."""
    if not is_building_target(target_id):
        return None
    from systems.building_entrances import get_building_by_id
    from systems.templates import resolve_floorplan
    building = get_building_by_id(world, target_id[len(BUILDING_TARGET_PREFIX):])
    if not building:
        return None
    floorplan = resolve_floorplan(world, building) or {}
    from systems.navigation import find_building_entrances
    entrances = find_building_entrances(building, floorplan) if floorplan.get("tiles") else []
    household = (world.get("households") or {}).get(building.get("owner_household_id")) or {}
    own_home = bool(household) and household.get("id") == c.get("household_id")
    cx, cy = c.get("x", 0), c.get("y", 0)
    if own_home:
        # somewhere to be, not the doormat: the living room if there is one, else just inside the door
        living = next((r for r in (floorplan.get("rooms") or [])
                       if r.get("type") == "living_room" and r.get("tiles")), None)
        if living:
            x, y = _world_point(building, living)
            return x, y, True
        if entrances:
            e = min(entrances, key=lambda e: abs(e["inside"][0] - cx) + abs(e["inside"][1] - cy))
            return e["inside"][0], e["inside"][1], True
        return None
    if not entrances:
        return None
    e = min(entrances, key=lambda e: abs(e["outside"][0] - cx) + abs(e["outside"][1] - cy))
    return e["outside"][0], e["outside"][1], False


def describe_building_target(world, target_id):
    from systems.building_entrances import get_building_by_id
    building = get_building_by_id(world, target_id[len(BUILDING_TARGET_PREFIX):]) if is_building_target(target_id) else None
    household = (world.get("households") or {}).get((building or {}).get("owner_household_id")) or {}
    return household.get("name") or (building or {}).get("address") or "there"
