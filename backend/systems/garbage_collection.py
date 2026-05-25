from systems.service_vehicles import (
    spawn_service_vehicle
)


# =========================================================
# UPDATE GARBAGE COLLECTION
# =========================================================

def update_garbage_collection(world):

    calendar = world.get(
        "calendar",
        {}
    )

    day = calendar.get(
        "day",
        0
    )

    hour = calendar.get(
        "hour",
        0
    )

    # =====================================================
    # COLLECTION DAY
    # =====================================================

    if day % 7 != 2:
        return

    if hour != 7:
        return

    if world.get(
        "garbage_collected_day"
    ) == day:

        return

    households = []

    for household in world[
        "households"
    ].values():

        bin_data = household.get(
            "garbage_bin",
            {}
        )

        if bin_data.get(
            "fullness",
            0
        ) <= 0.1:

            continue

        households.append(
            household
        )

    if not households:
        return

    spawn_service_vehicle(

        world,

        service_type=
            "garbage_collection",

        vehicle_model=
            "garbage_truck",

        worker_model=
            "garbage_worker",

        target_households=
            households
    )

    world[
        "garbage_collected_day"
    ] = day