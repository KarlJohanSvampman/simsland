from systems.housing import (
    get_household_home,
    vacate_home
)


# =========================================================
# EVICT HOUSEHOLD
# =========================================================

def evict_household(

    household,

    world
):

    home = get_household_home(
        household,
        world
    )

    if home:

        vacate_home(home)

    household["home_id"] = None

    household["evicted"] = True

    household["housing_stress"] = 1.0

    for cid in household.get(
        "members",
        []
    ):

        c = world.get(
            "characters",
            {}
        ).get(cid)

        if not c:
            continue

        c["stress"] = min(
            1.0,
            c.get("stress",0) + 0.5
        )

        c["housing_insecure"] = True


# =========================================================
# PROCESS EVICTIONS
# =========================================================

def process_evictions(world):

    for household in world.get(
        "households",
        {}
    ).values():

        debt = sum(

            bill.get(
                "amount",
                0
            )

            for bill in household.get(
                "bills_due",
                []
            )
        )

        if debt > 5000:

            evict_household(
                household,
                world
            )