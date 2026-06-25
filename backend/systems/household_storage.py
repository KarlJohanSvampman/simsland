from systems.resource_runtime import (
    create_resource
)


# =========================================================
# ENSURE STORAGE
# =========================================================

def ensure_household_storage(

    household
):

    household.setdefault(

        "storage",

        {

            "resources": []
        }
    )


# =========================================================
# ADD RESOURCE
# =========================================================

def add_household_resource(

    household,

    resource
):

    ensure_household_storage(
        household
    )

    household[
        "storage"
    ][
        "resources"
    ].append(resource)


# =========================================================
# CREATE + ADD
# =========================================================

def create_household_resource(

    household,

    resource_type,

    quantity=1,

    container=None,

    **kwargs
):

    resource = create_resource(

        resource_type,

        quantity,

        container=container,

        **kwargs
    )

    add_household_resource(

        household,

        resource
    )

    return resource


# =========================================================
# FIND RESOURCE
# =========================================================

def find_household_resource(

    household,

    resource_type=None,

    category=None
):

    ensure_household_storage(
        household
    )

    for r in household[
        "storage"
    ][
        "resources"
    ]:

        if (

            resource_type

            and

            r[
                "resource_type"
            ]
            !=
            resource_type
        ):

            continue

        if category:

            rt = r.get(
                "resource_type"
            )

            if not rt.startswith(
                category
            ):

                continue

        return r

    return None


# =========================================================
# REMOVE RESOURCE
# =========================================================

def remove_household_resource(

    household,

    resource,

    quantity=1
):

    ensure_household_storage(
        household
    )

    resource[
        "quantity"
    ] -= quantity

    if resource[
        "quantity"
    ] <= 0:

        household[
            "storage"
        ][
            "resources"
        ].remove(resource)


# =========================================================
# COUNT
# =========================================================

def count_household_resources(

    household,

    resource_type
):

    ensure_household_storage(
        household
    )

    total = 0

    for r in household[
        "storage"
    ][
        "resources"
    ]:

        if (

            r[
                "resource_type"
            ]
            ==
            resource_type
        ):

            total += r[
                "quantity"
            ]

    return total


# =========================================================
# FIND BY CONTAINER
# =========================================================

def resources_in_container(

    household,

    container
):

    ensure_household_storage(
        household
    )

    results = []

    for r in household[
        "storage"
    ][
        "resources"
    ]:

        if r.get(
            "container"
        ) == container:

            results.append(r)

    return results