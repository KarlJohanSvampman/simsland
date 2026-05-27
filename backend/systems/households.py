# =========================================================
# GET HOUSEHOLD
# =========================================================

def get_household(

    world,

    household_id
):

    return world.get(
        "households",
        {}
    ).get(
        household_id
    )


# =========================================================
# GET HOUSEHOLD MEMBERS
# =========================================================

def get_household_members(

    household,

    world
):

    results = []

    for cid in household.get(
        "members",
        []
    ):

        c = world.get(
            "characters",
            {}
        ).get(cid)

        if c:

            results.append(c)

    return results


# =========================================================
# VACANT HOME
# =========================================================

def mark_home_vacant(home):

    home["vacant"] = True

    home["household_id"] = None


# =========================================================
# OCCUPY HOME
# =========================================================

def occupy_home(

    home,

    household_id
):

    home["vacant"] = False

    home["household_id"] = household_id