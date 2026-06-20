from systems.service_vehicles import (
    spawn_service_vehicle
)


# =========================================================
# UPDATE POSTAL SERVICE
# =========================================================

def update_postal_service(world):

    calendar = world.get(
        "calendar",
        {}
    )

    hour = calendar.get(
        "hour",
        0
    )

    # =====================================================
    # DAILY MAIL ROUTE
    # =====================================================

    if hour != 11:
        return

    if world.get(
        "postal_spawned_today"
    ) == calendar.get("day"):

        return

    households = []

    for household in world[
        "households"
    ].values():

        if not household.get(
            "mail"
        ):
            continue

        households.append(
            household
        )

    if not households:
        return

    spawn_service_vehicle(

        world,

        service_type="postal",

        vehicle_model=
            "postal_truck",

        worker_model=
            "mailman",

        target_households=
            households
    )

    world[
        "postal_spawned_today"
    ] = calendar["day"]