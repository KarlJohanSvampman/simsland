from systems.persistent_desires import (
    add_desire
)


# =========================================================
# UPDATE HOUSEHOLDS
# =========================================================

def update_household_monitoring(world):

    for household in world.get(
        "households",
        {}
    ).values():

        update_household(

            household,

            world
        )


# =========================================================
# UPDATE HOUSEHOLD
# =========================================================

def update_household(

    household,

    world
):

    monitor_food(
        household,
        world
    )

    monitor_hygiene(
        household,
        world
    )

    monitor_toilet_paper(
        household,
        world
    )

    monitor_appliances(
        household,
        world
    )

    monitor_meals(
        household,
        world
    )


# =========================================================
# FOOD
# =========================================================

def monitor_food(

    household,

    world
):

    resources = household.get(
        "storage",
        {}
    ).get(
        "resources",
        []
    )

    food_score = 0

    for r in resources:

        rt = r.get(
            "resource_type"
        )

        quantity = r.get(
            "quantity",
            1
        )

        if rt.startswith("FOOD"):

            food_score += quantity

        elif rt in [

            "MEAL",

            "STORED_MEAL",

            "PROCESSED_MEAL"
        ]:

            food_score += (
                quantity * 2
            )

    residents = len(

        household.get(
            "members",
            []
        )
    )

    threshold = max(

        6,

        residents * 4
    )

    if food_score >= threshold:
        return

    create_household_procurement_desire(

        household,

        world,

        desire_type=
            "buy_groceries",

        target=
            "groceries",

        importance=
            0.65
    )


# =========================================================
# HYGIENE
# =========================================================

def monitor_hygiene(

    household,

    world
):

    quantity = count_resource(

        household,

        "HYGIENE"
    )

    if quantity >= 4:
        return

    create_household_procurement_desire(

        household,

        world,

        desire_type=
            "buy_hygiene",

        target=
            "hygiene",

        importance=
            0.45
    )


# =========================================================
# TOILET PAPER
# =========================================================

def monitor_toilet_paper(

    household,

    world
):

    quantity = count_resource(

        household,

        "TOILET_PAPER"
    )

    if quantity >= 6:
        return

    create_household_procurement_desire(

        household,

        world,

        desire_type=
            "buy_toilet_paper",

        target=
            "hygiene",

        importance=
            0.85
    )


# =========================================================
# MEALS
# =========================================================

def monitor_meals(

    household,

    world
):

    meals = 0

    for r in household.get(
        "storage",
        {}
    ).get(
        "resources",
        []
    ):

        if r.get(
            "resource_type"
        ) in [

            "MEAL",

            "STORED_MEAL",

            "PROCESSED_MEAL"
        ]:

            meals += r.get(
                "quantity",
                1
            )

    residents = len(

        household.get(
            "members",
            []
        )
    )

    if meals >= residents:
        return

    create_household_procurement_desire(

        household,

        world,

        desire_type=
            "prepare_food",

        target=
            "meal_supply",

        importance=
            0.55
    )


# =========================================================
# APPLIANCES
# =========================================================

def monitor_appliances(

    household,

    world
):

    for obj in household.get(
        "owned_objects",
        []
    ):

        durability = obj.get(
            "durability",
            1.0
        )

        if durability > 0.25:
            continue

        object_type = obj.get(
            "object_type"
        )

        create_household_procurement_desire(

            household,

            world,

            desire_type=
                "replace_appliance",

            target=
                object_type,

            importance=
                0.8
        )


# =========================================================
# COUNT RESOURCE
# =========================================================

def count_resource(

    household,

    resource_type
):

    total = 0

    for r in household.get(
        "storage",
        {}
    ).get(
        "resources",
        []
    ):

        if r.get(
            "resource_type"
        ) == resource_type:

            total += r.get(
                "quantity",
                1
            )

    return total


# =========================================================
# CREATE HOUSEHOLD DESIRE
# =========================================================

def create_household_procurement_desire(

    household,

    world,

    desire_type,

    target,

    importance
):

    members = household.get(
        "members",
        []
    )

    if not members:
        return

    # =====================================================
    # RESPONSIBLE MEMBER
    # =====================================================

    chosen = choose_responsible_member(

        members,

        world
    )

    if not chosen:
        return

    add_desire(

        chosen,

        desire_type=
            desire_type,

        target=target,

        importance=importance
    )


# =========================================================
# RESPONSIBILITY
# =========================================================

def choose_responsible_member(

    members,

    world
):

    best = None
    best_score = -999

    for c in members:

        score = 0

        traits = c.get(
            "traits",
            []
        )

        if "responsible" in traits:
            score += 4

        if "organized" in traits:
            score += 3

        if "lazy" in traits:
            score -= 4

        if "careless" in traits:
            score -= 3

        score += c.get(
            "conscientiousness",
            0
        ) * 2

        if score > best_score:

            best_score = score
            best = c

    return best