from systems.household_storage import (
    add_household_resource
)

from systems.resource_runtime import (
    create_resource
)


# =========================================================
# GENERATE WASTE
# =========================================================

def generate_activity_waste(

    household,

    activity
):

    waste = activity.get(
        "waste",
        {}
    )

    for resource_type, quantity in waste.items():

        resource = create_resource(

            resource_type,

            quantity=quantity,

            container="garbage"
        )

        add_household_resource(

            household,

            resource
        )


# =========================================================
# TOTAL WASTE
# =========================================================

def total_waste(household):

    total = 0

    for r in household.get(
        "storage",
        {}
    ).get(
        "resources",
        []
    ):

        rt = r.get(
            "resource_type",
            ""
        )

        if not rt.startswith(
            "TRASH"
        ):
            continue

        total += r.get(
            "quantity",
            1
        )

    return total


# =========================================================
# MOVE WASTE TO BIN
# =========================================================

def move_waste_to_bin(

    household
):

    garbage = household.setdefault(

        "garbage_bin",

        {}
    )

    garbage.setdefault(
        "contents",
        []
    )

    resources = household.get(
        "storage",
        {}
    ).get(
        "resources",
        []
    )

    moved = []

    for r in resources:

        rt = r.get(
            "resource_type",
            ""
        )

        if not rt.startswith(
            "TRASH"
        ):
            continue

        garbage[
            "contents"
        ].append(r)

        moved.append(r)

    for r in moved:

        resources.remove(r)

    garbage[
        "fullness"
    ] = min(

        1.0,

        len(
            garbage[
                "contents"
            ]
        ) / 30
    )