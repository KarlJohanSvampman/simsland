# =========================================================
# ENSURE HOUSEHOLD RESOURCES
# =========================================================

def ensure_household_resources(

    household
):

    household.setdefault(

        "resources",

        {

            "food": 12,

            "quick_food": 4,

            "fresh_ingredients": 8,

            "drinks": 10,

            "hygiene_products": 5,

            "medicine": 1,

            "toilet_paper": 8
        }
    )


    # =========================================================
# GET RESOURCE
# =========================================================

def get_resource(

    household,

    resource
):

    ensure_household_resources(
        household
    )

    return household[
        "resources"
    ].get(resource, 0)


# =========================================================
# CONSUME RESOURCE
# =========================================================

def consume_resource(

    household,

    resource,

    amount=1
):

    ensure_household_resources(
        household
    )

    household[
        "resources"
    ][resource] = max(

        0,

        household[
            "resources"
        ].get(resource, 0)

        - amount
    )

# =========================================================
# ADD RESOURCE
# =========================================================

def add_resource(

    household,

    resource,

    amount=1
):

    ensure_household_resources(
        household
    )

    household[
        "resources"
    ][resource] += amount