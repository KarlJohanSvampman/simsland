from systems.persistent_desires import (
    add_desire
)


# =========================================================
# UPDATE HOUSEHOLDS
# =========================================================

def update_household_chores(world):

    for household in world.get(
        "households",
        {}
    ).values():

        update_household_entropy(

            household,

            world
        )


# =========================================================
# ENTROPY
# =========================================================

def update_household_entropy(

    household,

    world
):

    household.setdefault(
        "cleanliness",
        1.0
    )

    household.setdefault(
        "trash_level",
        0.0
    )

    residents = len(

        household.get(
            "members",
            []
        )
    )

    entropy = (
        residents * 0.00001
    )

    household[
        "cleanliness"
    ] -= entropy

    household[
        "trash_level"
    ] += entropy

    household[
        "cleanliness"
    ] = max(

        0,

        household[
            "cleanliness"
        ]
    )

    household[
        "trash_level"
    ] = min(

        1.0,

        household[
            "trash_level"
        ]
    )

    generate_chores(

        household,

        world
    )

    update_food_decay(

        household,

        world
    )


# =========================================================
# CHORE PRESSURE
# =========================================================

def generate_chores(

    household,

    world
):

    members = household.get(
        "members",
        []
    )

    if not members:
        return

    responsible = members[0]

    # =====================================================
    # CLEANING
    # =====================================================

    if household[
        "cleanliness"
    ] < 0.45:

        add_desire(

            responsible,

            desire_type=
                "clean_house",

            target="house",

            importance=0.7
        )

    # =====================================================
    # TRASH
    # =====================================================

    if household[
        "trash_level"
    ] > 0.6:

        add_desire(

            responsible,

            desire_type=
                "take_out_trash",

            target="trash",

            importance=0.8
        )

    # =========================================================
    # FOOD DECAY
    # =========================================================

def update_food_decay(

    household,

    world
):

    fridge_quality = get_fridge_quality(
        household
    )

    for resource in household.get(
        "storage",
        {}
    ).get(
        "resources",
        []
    ):

        update_resource_decay(

            resource,

            fridge_quality
        )


    # =========================================================
    # RESOURCE DECAY
    # =========================================================

def update_resource_decay(

    resource,

    fridge_quality
):

    rt = resource.get(
        "resource_type"
    )

    freshness = resource.get(
        "freshness",
        1.0
    )

    decay = get_decay_rate(

        resource,

        fridge_quality
    )

    freshness -= decay

    freshness = max(
        0,
        freshness
    )

    resource[
        "freshness"
    ] = freshness

    # =====================================================
    # SPOILED
    # =====================================================

    if freshness <= 0.05:

        resource["spoiled"] = True

        resource["garbage"] = True


    # =========================================================
    # DECAY RATE
    # =========================================================

def get_decay_rate(

    resource,

    fridge_quality
):

    rt = resource.get(
        "resource_type"
    )

    container = resource.get(
        "container"
    )

    decay = 0.000002

    # =====================================================
    # STORED MEALS
    # =====================================================

    if rt == "STORED_MEAL":

        decay *= 4

    # =====================================================
    # FRESH INGREDIENTS
    # =====================================================

    elif rt in [

        "FOOD_PROTEIN",

        "FOOD_VEGETABLE",

        "DRINK_MILK"
    ]:

        decay *= 2.5

    # =====================================================
    # PANTRY STABLE
    # =====================================================

    elif rt in [

        "FOOD_CARB",

        "FOOD_SPICE",

        "DRINK_COFFEE",

        "DRINK_TEA"
    ]:

        decay *= 0.4

    # =====================================================
    # FRIDGE EFFECT
    # =====================================================

    if container == "fridge":

        decay *= (

            1.2 - fridge_quality
        )

    return decay


    # =========================================================
    # FRIDGE QUALITY
    # =========================================================

def get_fridge_quality(

    household
):

    fridges = [

        o

        for o in household.get(
            "owned_objects",
            []
        )

        if o.get(
            "object_type"
        ) == "fridge"
    ]

    if not fridges:

        return 0.2

    fridge = fridges[0]

    if fridge.get(
        "broken"
    ):

        return 0.1

    durability = fridge.get(
        "durability",
        1.0
    )

    quality = fridge.get(
        "quality",
        0.5
    )

    return (
        durability
        *
        quality
    )