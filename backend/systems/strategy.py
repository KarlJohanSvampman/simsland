import random


# =========================================================
# RESOLVE STRATEGY
# =========================================================

def resolve_strategy(

    c,

    world,

    intention
):

    t = intention.get(
        "type"
    )

    # =====================================================
    # HUNGER
    # =====================================================

    if t == "satisfy_hunger":

        return resolve_hunger_strategy(

            c,

            world
        )

    # =====================================================
    # SOCIAL
    # =====================================================

    if t == "contact_person":

        return resolve_social_strategy(

            c,

            world,

            intention
        )

    # =====================================================
    # HYGIENE
    # =====================================================

    if t == "restore_hygiene":

        return resolve_hygiene_strategy(
            c
        )

    # =====================================================
    # FATIGUE
    # =====================================================

    if t == "restore_energy":

        return resolve_energy_strategy(
            c
        )

    return None


# =========================================================
# HUNGER
# =========================================================

def resolve_hunger_strategy(

    c,

    world
):

    household = world[
        "households"
    ].get(
        c.get("household_id")
    )

    if not household:
        return "eat_snack"

    from systems.household_storage import (
        find_household_resource
    )

    # =====================================================
    # READY MEALS
    # =====================================================

    meal = find_household_resource(

        household,

        resource_type="MEAL"
    )

    if meal:

        return "eat_meal"

    # =====================================================
    # STORED MEALS
    # =====================================================

    leftovers = find_household_resource(

        household,

        resource_type="STORED_MEAL"
    )

    if leftovers:

        return "heat_meal"

    # =====================================================
    # PROCESSED MEALS
    # =====================================================

    processed = find_household_resource(

        household,

        resource_type=
            "PROCESSED_MEAL"
    )

    if processed:

        return "heat_meal"

    # =====================================================
    # QUICK FOOD
    # =====================================================

    fruit = find_household_resource(

        household,

        resource_type=
            "FOOD_FRUIT"
    )

    if fruit:

        return "eat_snack"

    snacks = find_household_resource(

        household,

        resource_type=
            "FOOD_SNACK"
    )

    if snacks:

        return "eat_snack"

    # =====================================================
    # INGREDIENTS
    # =====================================================

    protein = find_household_resource(

        household,

        resource_type=
            "FOOD_PROTEIN"
    )

    carbs = find_household_resource(

        household,

        resource_type=
            "FOOD_CARB"
    )

    vegetables = find_household_resource(

        household,

        resource_type=
            "FOOD_VEGETABLE"
    )

    if protein and carbs and vegetables:

        return "cook_recipe"

    # =====================================================
    # NO FOOD
    # =====================================================

    money = c.get(
        "money",
        0
    )

    if money > 20:

        return random.choice([

            "buy_food",

            "order_takeout"
        ])

    return "eat_snack"
# =========================================================
# SOCIAL
# =========================================================

def resolve_social_strategy(

    c,

    world,

    intention
):

    target_id = intention.get(
        "target_id"
    )

    target = world[
        "characters"
    ].get(
        target_id
    )

    if not target:
        return None

    energy = c.get(
        "needs",
        {}
    ).get(
        "energy",
        1
    )

    insecurity = c.get(
        "insecurity",
        0
    )

    # =====================================================
    # TIRED
    # =====================================================

    if energy < 0.25:

        return "text_person"

    # =====================================================
    # INSECURE
    # =====================================================

    if insecurity > 70:

        return random.choice([

            "text_person",

            "browse_phone"
        ])

    # =====================================================
    # SAME BUILDING
    # =====================================================

    if (

        c.get("building_id")
        ==
        target.get("building_id")
    ):

        return random.choice([

            "conversation",

            "hangout"
        ])

    # =====================================================
    # DISTANT
    # =====================================================

    return random.choice([

        "call_person",

        "visit_person"
    ])


# =========================================================
# HYGIENE
# =========================================================

def resolve_hygiene_strategy(c):

    hygiene = c.get(
        "needs",
        {}
    ).get(
        "hygiene",
        1
    )

    if hygiene < 0.2:

        return "take_shower"

    return random.choice([

        "wash_hands",

        "brush_teeth"
    ])


# =========================================================
# ENERGY
# =========================================================

def resolve_energy_strategy(c):

    energy = c.get(
        "needs",
        {}
    ).get(
        "energy",
        1
    )

    if energy < 0.15:

        return "sleep"

    return "nap"