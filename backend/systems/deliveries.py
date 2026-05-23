from systems.procurement import (
    acquire_product
)


# =========================================================
# UPDATE DELIVERIES
# =========================================================

def update_deliveries(world):

    deliveries = world.get(
        "deliveries",
        []
    )

    completed = []

    for delivery in deliveries:

        if delivery.get(
            "status"
        ) != "in_transit":

            continue

        if world["tick"] < delivery[
            "arrival_tick"
        ]:
            continue

        process_delivery(

            delivery,

            world
        )

        completed.append(
            delivery
        )

    # =====================================================
    # CLEANUP
    # =====================================================

    for d in completed:

        deliveries.remove(d)


# =========================================================
# PROCESS DELIVERY
# =========================================================

def process_delivery(

    delivery,

    world
):

    household = world[
        "households"
    ].get(

        delivery[
            "household_id"
        ]
    )

    if not household:
        return

    product = delivery.get(
        "product"
    )

    if not product:
        return

    # =====================================================
    # ACQUIRE
    # =====================================================

    acquire_product(

        household,

        product
    )

    # =====================================================
    # NOTIFICATION
    # =====================================================

    household.setdefault(
        "notifications",
        []
    )

    household[
        "notifications"
    ].append({

        "type":
            "delivery_arrived",

        "product":
            product,

        "tick":
            world["tick"]
    })

    delivery[
        "status"
    ] = "delivered"