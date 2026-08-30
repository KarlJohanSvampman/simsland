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

        building_id,

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