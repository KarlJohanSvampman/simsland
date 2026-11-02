from systems.navigation import (

    get_room_at_position
)


# =========================================================
# ASSIGN SINGLE PROP
# =========================================================

def assign_prop_room(

    building,

    prop
):

    building_id = building["id"]

    room_id = get_room_at_position(

        building,

        prop["x"],

        prop["y"]
    )

    prop["room_id"] = room_id

    prop["building_id"] = building_id

    # A prop's household owner defaults to whichever household owns the
    # building's floorplan -- setdefault so a prop already explicitly
    # assigned elsewhere (e.g. a car/garage/bus prop under a specific
    # household by systems/vehicles.py) isn't silently overwritten.
    prop.setdefault("household_id", building.get("owner_household_id"))

    return room_id


# =========================================================
# ASSIGN ALL PROPS
# =========================================================

def assign_prop_rooms(

    building,

    props
):

    for prop in props:

        assign_prop_room(

            building,

            prop
        )


# =========================================================
# ASSIGN CHARACTER ROOM
# =========================================================

def assign_character_room(

    building,

    character
):

    building_id = building["id"]

    room_id = get_room_at_position(

        building,

        character["x"],

        character["y"]
    )

    character["room_id"] = room_id

    character["building_id"] = building_id

    return room_id


# =========================================================
# ASSIGN ALL CHARACTERS
# =========================================================

def assign_character_rooms(

    building,

    characters
):

    for c in characters:

        assign_character_room(

            building,

            c
        )


# =========================================================
# CLEAR OUTDOOR ENTITY
# =========================================================

def clear_outdoor_assignment(
    entity
):

    entity["room_id"] = None

    entity["building_id"] = None

# =========================================================
# KEEP A CHARACTER'S ROOM CURRENT
# =========================================================
# c["room_id"] used to be set once, at spawn, and never again -- so a character who had walked into the kitchen was
# still "in starter_house_2:dining_room_1" to the prompt ("You are indoors, in ...") and to everything that compares
# rooms (who is in the same room for a fight, a reaction, a chore, how muffled a voice is). Live, 2026-11-02: Robert
# Okafor, standing in the kitchen, was told he was in the dining room with Carol Lindqvist.

_ROOM_TILES = {}     # (building id, floorplan id) -> {(local x, local y): room id}


def _room_tiles(building, floorplan):
    key = (building["id"], floorplan.get("id"))
    lookup = _ROOM_TILES.get(key)
    if lookup is None:
        lookup = {}
        for room in floorplan.get("rooms") or []:
            for tile in room.get("tiles") or []:
                lookup[(int(tile["x"]), int(tile["y"]))] = room["id"]
        _ROOM_TILES[key] = lookup
    return lookup


def room_at(world, x, y):
    """The runtime room id ("<building>:<room>") of the floor tile at world (x, y), or None outdoors."""
    from systems.navigation import find_building_at, runtime_room_id
    from systems.transforms import world_to_local
    building, floorplan = find_building_at(world, int(round(x)), int(round(y)))
    if not building:
        return None
    lx, ly = world_to_local(building, int(round(x)), int(round(y)))
    room = _room_tiles(building, floorplan).get((lx, ly))
    return runtime_room_id(building["id"], room) if room else None


def refresh_character_room(c, world):
    """Set c["room_id"] from where c stands now. Cheap: only looks again when c is on a different tile."""
    if c.get("x") is None or c.get("y") is None:
        return
    tile = [int(round(c["x"])), int(round(c["y"]))]
    if c.get("_room_tile") == tile and "room_id" in c:
        return
    c["_room_tile"] = tile
    c["room_id"] = room_at(world, tile[0], tile[1])
