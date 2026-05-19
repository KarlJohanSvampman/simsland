# =========================================================
# GET ENTRANCES
# =========================================================

def get_building_entrances(

    building
):

    return building.get(
        "entrances",
        []
    )


# =========================================================
# PRIMARY ENTRANCE
# =========================================================

def get_primary_entrance(

    building
):

    entrances = get_building_entrances(
        building
    )

    if not entrances:
        return None

    return entrances[0]


# =========================================================
# FIND BUILDING
# =========================================================

def get_building_by_id(

    world,

    building_id
):

    for b in world.get(
        "buildings",
        []
    ):

        if b["id"] == building_id:
            return b

    return None     