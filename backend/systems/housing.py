# =========================================================
# GET HOME
# =========================================================

def get_home(

    world,

    home_id
):

    return world.get(
        "homes",
        {}
    ).get(
        home_id
    )


# =========================================================
# GET HOUSEHOLD HOME
# =========================================================

def get_household_home(

    household,

    world
):

    hid = household.get(
        "home_id"
    )

    if not hid:
        return None

    return get_home(
        world,
        hid
    )


# =========================================================
# VACANCY
# =========================================================

def is_home_vacant(home):

    return home.get(
        "vacant",
        False
    )


# =========================================================
# GET VACANT HOMES
# =========================================================

def get_vacant_homes(world):

    return [

        h

        for h in world.get(
            "homes",
            {}
        ).values()

        if h.get("vacant")
    ]


# =========================================================
# ASSIGN HOUSEHOLD
# =========================================================

def assign_household_to_home(

    household,

    home
):

    household["home_id"] = home["id"]

    home["household_id"] = household["id"]

    home["vacant"] = False


# =========================================================
# VACATE HOME
# =========================================================

def vacate_home(home):

    home["household_id"] = None

    home["vacant"] = True