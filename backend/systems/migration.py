import random

from systems.housing import (
    get_vacant_homes,
    assign_household_to_home,
    get_household_home
)


# =========================================================
# HOUSING SCORE
# =========================================================

def score_home(

    household,

    home,

    world
):

    income = household.get(
        "income",
        0
    )

    rent = home.get(
        "rent",
        1000
    )

    quality = home.get(
        "quality",
        0.5
    )

    crime = home.get(
        "crime_risk",
        0.5
    )

    affordability = max(
        0,
        1 - (rent / max(1,income+1))
    )

    return (

        affordability * 0.5 +

        quality * 0.4 +

        (1-crime) * 0.3
    )


# =========================================================
# SHOULD MOVE
# =========================================================

def should_consider_moving(

    household,

    world
):

    stress = household.get(
        "housing_stress",
        0
    )

    current = get_household_home(
        household,
        world
    )

    if not current:
        return True

    # remaining, not amount -- see eviction.py::check_household_for_eviction
    # for why (amount never decreases once a bill's paid down).
    debt = sum(

        b.get("remaining",0)

        for b in household.get(
            "bills_due",
            []
        )
    )

    if debt > 2000:
        return True

    if stress > 0.6:
        return True

    if random.random() < 0.001:
        return True

    return False


# =========================================================
# FIND BETTER HOME
# =========================================================

def find_better_home(

    household,

    world
):

    homes = get_vacant_homes(
        world
    )

    if not homes:
        return None

    scored = []

    for h in homes:

        scored.append(
            (
                score_home(
                    household,
                    h,
                    world
                ),
                h
            )
        )

    scored.sort(
        key=lambda x: x[0],
        reverse=True
    )

    if not scored:
        return None

    best_score, best = scored[0]

    if best_score < 0.3:
        return None

    return best


# =========================================================
# PROCESS MIGRATION
# =========================================================

def check_migration_desires(world):
    """
    Scan all households and emit 'household_wants_to_move' when the
    threshold is crossed. Replaces the old polling process_migration.
    """
    from core.event_bus import emit
    for hid, household in world.get("households", {}).items():
        if household.get("_migration_emitted"):
            continue
        if should_consider_moving(household, world):
            household["_migration_emitted"] = True
            emit("household_wants_to_move", {"household_id": hid})


def process_migration(world):
    """Legacy full-scan — kept for compatibility but no longer called from sim_loop."""
    for household in world.get("households", {}).values():
        if not should_consider_moving(household, world):
            continue
        _do_migrate(household, world)


def _do_migrate(household, world):
    new_home = find_better_home(household, world)
    if not new_home:
        return
    old = get_household_home(household, world)
    if old:
        old["vacant"]       = True
        old["household_id"] = None
    assign_household_to_home(household, new_home, world=world)
    household["housing_stress"]    *= 0.5
    household["_migration_emitted"] = False  # reset so threshold can re-fi
