"""
systems/newspaper_delivery.py

Paperboy delivery -- a daily route to every household with a newspaper
subscription, direct copy of postal_service.py's shape (own service_type/
models/trigger hour/household filter, reusing the exact same
service_vehicles.py/service_worker_runtime.py machinery). See that file's
comment for why this pattern (not a fix to the separately-dormant mail
system) is the right one to copy.
"""

from systems.service_vehicles import (
    spawn_service_vehicle
)


# =========================================================
# UPDATE NEWSPAPER DELIVERY
# =========================================================

def update_newspaper_delivery(world):

    calendar = world.get(
        "calendar",
        {}
    )

    hour = calendar.get(
        "hour",
        0
    )

    # =====================================================
    # DAILY NEWSPAPER ROUTE
    # =====================================================

    if hour != 7:
        return

    if world.get(
        "newspaper_spawned_today"
    ) == calendar.get("day"):

        return

    households = []

    for household in world[
        "households"
    ].values():

        if not household.get(
            "newspaper_subscription"
        ):
            continue

        households.append(
            household
        )

    if not households:
        return

    spawn_service_vehicle(

        world,

        service_type="newspaper",

        vehicle_model=
            "paperboy_bike",

        worker_model=
            "paperboy",

        target_households=
            households
    )

    world[
        "newspaper_spawned_today"
    ] = calendar["day"]
