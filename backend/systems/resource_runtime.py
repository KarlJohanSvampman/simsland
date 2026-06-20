import random

from data.resources import (
    RESOURCE_TYPES
)


# =========================================================
# CREATE RESOURCE INSTANCE
# =========================================================

def create_resource(

    resource_type,

    quantity=1,

    **kwargs
):

    r = {

        "resource_type":
            resource_type,

        "quantity":
            quantity,

        "freshness":
            1.0
    }

    r.update(kwargs)

    return r


# =========================================================
# STORE RESOURCE
# =========================================================

def store_resource(

    storage,

    resource
):

    storage.setdefault(
        "resources",
        []
    )

    storage[
        "resources"
    ].append(resource)


# =========================================================
# FIND RESOURCE
# =========================================================

def find_resource(

    storage,

    resource_type
):

    for r in storage.get(
        "resources",
        []
    ):

        if r[
            "resource_type"
        ] == resource_type:

            return r

    return None


# =========================================================
# CONSUME RESOURCE
# =========================================================

def consume_resource(

    storage,

    resource_type,

    quantity=1
):

    resources = storage.get(
        "resources",
        []
    )

    for r in resources:

        if r[
            "resource_type"
        ] != resource_type:

            continue

        r["quantity"] -= quantity

        if r["quantity"] <= 0:

            resources.remove(r)

        return True

    return False


# =========================================================
# STORE LEFTOVERS
# =========================================================

def convert_meal_to_leftovers(

    meal
):

    meal[
        "resource_type"
    ] = "STORED_MEAL"

    meal[
        "freshness"
    ] *= 0.85

    return meal


# =========================================================
# HEAT MEAL
# =========================================================

def heat_meal(

    resource
):

    rt = resource.get(
        "resource_type"
    )

    if rt not in [

        "PROCESSED_MEAL",

        "STORED_MEAL"
    ]:

        return resource

    resource[
        "resource_type"
    ] = "MEAL"

    resource[
        "heated"
    ] = True

    return resource


# =========================================================
# DECAY
# =========================================================

def decay_resources(storage):

    for r in storage.get(
        "resources",
        []
    ):

        decay = 0.0001

        if r.get(
            "resource_type"
        ) == "STORED_MEAL":

            decay *= 4

        r["freshness"] -= decay

        r["freshness"] = max(
            0,
            r["freshness"]
        )